"""Guitar Tabber: paste a video link, get a draft guitar tab."""
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline  # noqa: E402  (stdlib-only at import time, so the window opens fast)

LOWEST_NOTE = {
    "G3 - lead only (default)": 55,
    "E3": 52,
    "C4 - high lead only": 60,
    "E2 - everything": 40,
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Guitar Tabber")
        self.geometry("1100x720")
        self.minsize(760, 480)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.result = None
        self._last_was_progress = False
        self._build()
        self.after(100, self._poll)

    def _build(self):
        pad = {"padx": 6, "pady": 4}
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Video link or file:").grid(row=0, column=0, sticky="w", **pad)
        self.source = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.source)
        entry.grid(row=0, column=1, columnspan=6, sticky="ew", **pad)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self.start())
        ttk.Button(top, text="Browse...", command=self.browse).grid(row=0, column=7, **pad)

        ttk.Label(top, text="Start:").grid(row=1, column=0, sticky="w", **pad)
        self.start_t = tk.StringVar(value="0:00")
        ttk.Entry(top, textvariable=self.start_t, width=8).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(top, text="End:").grid(row=1, column=2, sticky="e", **pad)
        self.end_t = tk.StringVar(value="1:00")
        ttk.Entry(top, textvariable=self.end_t, width=8).grid(row=1, column=3, sticky="w", **pad)

        ttk.Label(top, text="BPM hint:").grid(row=1, column=4, sticky="e", **pad)
        self.bpm = tk.StringVar()
        ttk.Entry(top, textvariable=self.bpm, width=6).grid(row=1, column=5, sticky="w", **pad)

        ttk.Label(top, text="Lowest note:").grid(row=2, column=0, sticky="w", **pad)
        self.lowest = tk.StringVar(value=next(iter(LOWEST_NOTE)))
        ttk.Combobox(top, textvariable=self.lowest, values=list(LOWEST_NOTE), state="readonly",
                     width=24).grid(row=2, column=1, columnspan=3, sticky="w", **pad)
        self.separate = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Isolate guitar first (slower, much cleaner)",
                        variable=self.separate).grid(row=2, column=4, columnspan=3, sticky="w", **pad)
        top.columnconfigure(6, weight=1)

        bar = ttk.Frame(self, padding=(8, 0))
        bar.pack(fill="x")
        self.go_btn = ttk.Button(bar, text="Generate tab", command=self.start)
        self.go_btn.pack(side="left", padx=6)
        self.cancel_btn = ttk.Button(bar, text="Cancel", command=self.stop, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=6)
        self.status = tk.StringVar(value="Paste a link, pick a section, press Generate tab.")
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=6)

        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="none", font=("Consolas", 10), undo=False)
        ys = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        xs = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        bottom = ttk.Frame(self, padding=(8, 0, 8, 8))
        bottom.pack(fill="x")
        self.open_pdf_btn = ttk.Button(bottom, text="Open PDF / Print", command=self.open_pdf, state="disabled")
        self.open_pdf_btn.pack(side="left", padx=6)
        self.save_pdf_btn = ttk.Button(bottom, text="Save PDF...", command=self.save_pdf, state="disabled")
        self.save_pdf_btn.pack(side="left", padx=6)
        self.save_tab_btn = ttk.Button(bottom, text="Save text tab...", command=self.save_tab, state="disabled")
        self.save_tab_btn.pack(side="left", padx=6)
        self.save_mid_btn = ttk.Button(bottom, text="Save MIDI...", command=self.save_midi, state="disabled")
        self.save_mid_btn.pack(side="left", padx=6)
        ttk.Label(bottom, text="Draft transcription: check it by ear.",
                  foreground="#666").pack(side="right", padx=6)

    # ---- actions -------------------------------------------------------
    def browse(self):
        path = filedialog.askopenfilename(filetypes=[
            ("Audio/video", "*.wav *.mp3 *.flac *.m4a *.ogg *.mp4 *.mkv *.webm"), ("All files", "*.*")])
        if path:
            self.source.set(path)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            src = self.source.get().strip().strip('"')
            if not src:
                raise ValueError("Paste a video link or choose a file first.")
            start = pipeline.parse_time(self.start_t.get()) or 0.0
            end = pipeline.parse_time(self.end_t.get())
            if end is not None and end <= start:
                raise ValueError("End time must be after start time.")
            bpm = float(self.bpm.get()) if self.bpm.get().strip() else None
        except ValueError as e:
            messagebox.showerror("Guitar Tabber", str(e))
            return
        if end is None or end - start > 600:
            if not messagebox.askyesno("Guitar Tabber", "That's a long section (over 10 minutes or to the end "
                                       "of the video). It may take a long time. Continue?"):
                return
        opts = pipeline.Options(source=src, start=start, end=end, separate=self.separate.get(),
                                min_pitch=LOWEST_NOTE[self.lowest.get()], bpm=bpm)
        self.cancel.clear()
        self.result = None
        self.text.delete("1.0", "end")
        self._set_running(True)
        self.worker = threading.Thread(target=self._work, args=(opts,), daemon=True)
        self.worker.start()

    def stop(self):
        self.cancel.set()
        self.status.set("Cancelling ...")

    def _work(self, opts):
        def log(msg, replace=False):
            self.events.put(("log", msg, replace))
        try:
            self.events.put(("done", pipeline.run(opts, log, self.cancel)))
        except pipeline.Cancelled:
            self.events.put(("cancelled",))
        except Exception as e:  # surface any failure to the user instead of dying silently
            self.events.put(("error", f"{type(e).__name__}: {e}"))

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "log":
                    _, msg, replace = ev
                    self.status.set(msg)
                    # progress updates overwrite the previous progress line
                    if replace and self._last_was_progress:
                        self.text.delete("end-2l", "end-1c")
                    self._last_was_progress = replace
                    self.text.insert("end", msg + "\n")
                    self.text.see("end")
                elif kind == "done":
                    self.result = ev[1]
                    self.text.delete("1.0", "end")
                    self.text.insert("1.0", self.result.tab)
                    self.status.set(self.result.summary)
                    self._set_running(False)
                elif kind == "cancelled":
                    self.status.set("Cancelled.")
                    self._set_running(False)
                elif kind == "error":
                    self.status.set("Failed.")
                    self._set_running(False)
                    messagebox.showerror("Guitar Tabber", ev[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _set_running(self, running):
        self.go_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")
        done = "normal" if (self.result and not running) else "disabled"
        for btn in (self.open_pdf_btn, self.save_pdf_btn, self.save_tab_btn, self.save_mid_btn):
            btn.configure(state=done)
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _default_name(self):
        name = "".join(c for c in self.result.title if c.isalnum() or c in " -_").strip()
        return (name or "tab")[:60]

    def open_pdf(self):
        # opens in the default PDF viewer, which has Print
        if sys.platform == "win32":
            os.startfile(self.result.pdf_path)
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", self.result.pdf_path])

    def save_pdf(self):
        path = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=self._default_name() + ".pdf",
                                            filetypes=[("PDF", "*.pdf")])
        if path:
            shutil.copyfile(self.result.pdf_path, path)

    def save_tab(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=self._default_name() + ".txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text.get("1.0", "end-1c"))  # keeps any hand edits made in the window

    def save_midi(self):
        path = filedialog.asksaveasfilename(defaultextension=".mid", initialfile=self._default_name() + ".mid",
                                            filetypes=[("MIDI", "*.mid")])
        if path:
            shutil.copyfile(self.result.mid_path, path)


REQUIRED_MODULES = ("yt_dlp", "demucs", "basic_pitch", "librosa", "reportlab")
VENV_SCRIPTS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "guitar-tab-venv", "Scripts")


def ensure_environment():
    """If started with a Python that lacks the app's packages (e.g. by
    double-clicking app.py), relaunch in the app's own environment, or say
    how to create it instead of failing halfway through a run."""
    import importlib.util
    missing = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    if not missing:
        return
    venv_python = os.path.join(VENV_SCRIPTS, "pythonw.exe")
    if os.path.exists(venv_python) and not os.environ.get("GUITAR_TABBER_RELAUNCHED"):
        import subprocess
        subprocess.Popen([venv_python, os.path.abspath(__file__)],
                         env={**os.environ, "GUITAR_TABBER_RELAUNCHED": "1"})
        sys.exit(0)
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Guitar Tabber",
        "Guitar Tabber's Python packages are not installed (missing: " + ", ".join(missing) + ").\n\n"
        "Start the app with 'Guitar Tabber.bat' instead of app.py. It installs everything "
        "on its first run.")
    sys.exit(1)


if __name__ == "__main__":
    ensure_environment()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()
