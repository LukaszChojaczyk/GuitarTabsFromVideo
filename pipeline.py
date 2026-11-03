"""Video link (or local audio file) -> isolated guitar -> tab.

Every step caches its output in a job folder keyed by the source and time
range, so re-running with different tab settings skips download/separation.
"""
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

WORK_ROOT = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "guitar-tab-work", "jobs")


class Cancelled(Exception):
    pass


@dataclass
class Options:
    source: str  # video URL or local audio/video file
    start: float = 0.0  # seconds
    end: Optional[float] = None  # seconds, None = to the end
    separate: bool = True  # isolate guitar with Demucs
    min_pitch: int = 55
    bpm: Optional[float] = None


@dataclass
class Result:
    tab: str
    summary: str
    title: str
    txt_path: str
    mid_path: str
    pdf_path: str


def parse_time(text):
    """'1:23', '1:02:03' or '83' -> seconds. Empty -> None."""
    text = text.strip()
    if not text:
        return None
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}(\.\d+)?", text):
        raise ValueError(f"Can't read time '{text}'. Use m:ss, like 2:15.")
    secs = 0.0
    for part in text.split(":"):
        secs = secs * 60 + float(part)
    return secs


def _saved_path_dirs():
    """PATH as stored in the registry: programs started before an install
    (e.g. from an old Explorer/terminal) still have the stale PATH."""
    if sys.platform != "win32":
        return []
    import winreg
    dirs = []
    for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                dirs += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(os.pathsep)
        except OSError:
            pass
    return [d for d in dirs if d]


def find_ffmpeg():
    """Locate ffmpeg even if it was installed after this process started.
    Puts its folder on PATH for yt-dlp and child processes."""
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg", path=os.pathsep.join(_saved_path_dirs()))
    if not found:
        winget = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet")
        hits = glob.glob(os.path.join(winget, "Links", "ffmpeg.exe")) + \
            glob.glob(os.path.join(winget, "Packages", "*FFmpeg*", "*", "bin", "ffmpeg.exe"))
        found = hits[0] if hits else None
    if not found:
        raise RuntimeError("ffmpeg not found. Install it with: winget install Gyan.FFmpeg")
    folder = os.path.dirname(found)
    if folder not in os.environ["PATH"].split(os.pathsep):
        os.environ["PATH"] = folder + os.pathsep + os.environ["PATH"]
    return found


def _job_dir(key, opts):
    end = float(opts.end) if opts.end is not None else None
    raw = f"{key}|{float(opts.start)}|{end}"
    safe = re.sub(r"[^\w-]", "_", key)[:40]
    path = os.path.join(WORK_ROOT, f"{safe}_{hashlib.sha1(raw.encode()).hexdigest()[:8]}")
    os.makedirs(path, exist_ok=True)
    return path


def _fmt(secs):
    return f"{int(secs // 60)}:{int(secs % 60):02d}"


def fetch_clip(opts, log, cancel):
    """Return (clip_wav, job_dir, title)."""
    ffmpeg = find_ffmpeg()

    if os.path.isfile(opts.source):
        title = os.path.basename(opts.source)
        job = _job_dir(os.path.abspath(opts.source), opts)
        clip = os.path.join(job, "clip.wav")
        if not os.path.exists(clip):
            log(f"Cutting {title} ...")
            cmd = [ffmpeg, "-y", "-loglevel", "error", "-ss", str(opts.start), "-i", opts.source]
            if opts.end is not None:
                cmd += ["-t", str(opts.end - opts.start)]
            subprocess.run(cmd + ["-vn", "-ac", "2", "-ar", "44100", clip], check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return clip, job, title

    import yt_dlp
    from yt_dlp.utils import download_range_func

    class _Logger:
        def debug(self, msg):
            pass

        def info(self, msg):
            pass

        def warning(self, msg):
            if "JavaScript runtime" not in msg:  # harmless, and noisy
                log("yt-dlp: " + msg)

        def error(self, msg):
            log("yt-dlp: " + msg)

    log("Looking up video ...")
    with yt_dlp.YoutubeDL({"quiet": True, "logger": _Logger(), "noplaylist": True}) as ydl:
        info = ydl.extract_info(opts.source, download=False)
    title = info.get("title") or opts.source
    duration = info.get("duration") or 0
    end = opts.end if opts.end is not None else duration
    if duration and end > duration:
        end = duration
    if end <= opts.start:
        raise ValueError(f"End time must be after start (video is {_fmt(duration)} long).")
    opts.end = end
    log(f"Video: {title} ({_fmt(duration)}). Section {_fmt(opts.start)}-{_fmt(end)}.")

    job = _job_dir(info.get("id") or opts.source, opts)
    clip = os.path.join(job, "clip.wav")
    if os.path.exists(clip):
        log("Using cached audio.")
        return clip, job, title

    def hook(d):
        if cancel.is_set():
            raise Cancelled()
        if d.get("status") == "downloading":
            log(f"Downloading ... {d.get('_percent_str', '').strip()}", replace=True)

    ydl_opts = {
        "quiet": True,
        "logger": _Logger(),
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": os.path.join(job, "clip.%(ext)s"),
        "download_ranges": download_range_func(None, [(opts.start, end)]),
        "force_keyframes_at_cuts": True,
        "ffmpeg_location": os.path.dirname(ffmpeg),
        "progress_hooks": [hook],
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
    }
    log("Downloading audio ...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([opts.source])
    if not os.path.exists(clip):
        raise RuntimeError("Download finished but no audio file was produced.")
    return clip, job, title


def separate_guitar(clip, job, log, cancel):
    out = os.path.join(job, "sep")
    guitar = os.path.join(out, "htdemucs_6s", "clip", "guitar.wav")
    if os.path.exists(guitar):
        log("Using cached guitar track.")
        return guitar
    log("Isolating guitar with Demucs (takes a few minutes on CPU) ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "demucs", "-n", "htdemucs_6s", "--two-stems", "guitar", "-o", out, clip],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
        env={**os.environ, "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "PYTHONWARNINGS": "ignore"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    # tqdm redraws its bar with '\r', so split on both line endings
    buf, tail = b"", []
    while True:
        if cancel.is_set():
            proc.kill()
            raise Cancelled()
        ch = proc.stdout.read(1)
        if not ch:
            break
        if ch in b"\r\n":
            line = buf.decode(errors="replace").strip()
            buf = b""
            m = re.match(r"\s*(\d+)%", line)
            if m:
                log(f"Isolating guitar ... {m.group(1)}%", replace=True)
            elif line:
                tail = (tail + [line])[-5:]
        else:
            buf += ch
    if proc.wait() != 0 or not os.path.exists(guitar):
        raise RuntimeError("Demucs failed:\n" + "\n".join(tail))
    return guitar


def run(opts, log, cancel):
    clip, job, title = fetch_clip(opts, log, cancel)
    if cancel.is_set():
        raise Cancelled()
    guitar = separate_guitar(clip, job, log, cancel) if opts.separate else clip
    if cancel.is_set():
        raise Cancelled()
    log("Detecting notes and building tab ...")
    import pdf_export
    import tab_core

    prefix = os.path.join(job, "tab")
    layout, text, summary = tab_core.transcribe(guitar, prefix, mix_wav=clip, bpm=opts.bpm,
                                                min_pitch=opts.min_pitch, time_offset=opts.start)
    end = _fmt(opts.end) if opts.end is not None else "end"
    section = f"Guitar solo • section {_fmt(opts.start)}–{end}"
    source = opts.source if not os.path.isfile(opts.source) else None
    log("Laying out PDF ...")
    pdf_export.write_pdf(layout, prefix + ".pdf", title=title, subtitle=section, source=source)
    log("Done: " + summary)
    return Result(f"{title}\n{section}\n\n{text}", summary, title, prefix + ".txt", prefix + ".mid",
                  prefix + ".pdf")
