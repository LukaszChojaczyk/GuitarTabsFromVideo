"""Transcribe a (preferably isolated) guitar recording into ASCII tab.

Usage:
    python tab_core.py GUITAR_WAV OUT_PREFIX [--mix FULL_MIX_WAV] [--bpm N]

Pipeline: basic-pitch note detection -> lead-line cleanup -> tempo/beat grid
-> fret assignment by dynamic programming -> 16th-note ASCII tab.
Writes OUT_PREFIX.txt (tab) and OUT_PREFIX.mid (raw detected notes).
"""
import argparse
import math
import os
from dataclasses import dataclass, field

import librosa
import numpy as np
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict

TUNING = [64, 59, 55, 50, 45, 40]  # e B G D A E (high to low), MIDI numbers
STRING_NAMES = ["e", "B", "G", "D", "A", "E"]
MAX_FRET = 22
STEPS_PER_BEAT = 4  # 16th notes
BEATS_PER_BAR = 4


def detect_notes(path):
    _, midi, events = predict(
        path,
        ICASSP_2022_MODEL_PATH,
        onset_threshold=0.6,
        frame_threshold=0.35,
        minimum_note_length=80,  # ms
        minimum_frequency=librosa.midi_to_hz(TUNING[-1] - 0.5),
        maximum_frequency=librosa.midi_to_hz(TUNING[0] + MAX_FRET + 0.5),
        multiple_pitch_bends=False,
        melodia_trick=True,
    )
    notes = []
    for start, end, pitch, amp, bends in events:
        # bends are in 1/3-semitone steps relative to the note's pitch
        bend = max(bends) / 3.0 if bends else 0.0
        notes.append(dict(t=float(start), end=float(end), pitch=int(pitch), amp=float(amp), bend=bend))
    notes.sort(key=lambda n: (n["t"], -n["pitch"]))
    return midi, notes


def clean_lead(notes, chord_window=0.035, min_amp=0.3, min_pitch=0):
    """Keep a lead line: drop quiet ghost notes and low rhythm-guitar notes,
    allow up to 2 simultaneous notes (double stops)."""
    notes = [n for n in notes if n["amp"] >= min_amp and n["pitch"] >= min_pitch]
    groups, cur = [], []
    for n in notes:
        if cur and n["t"] - cur[0]["t"] > chord_window:
            groups.append(cur)
            cur = []
        cur.append(n)
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        g = sorted(g, key=lambda n: -n["amp"])[:2]
        # a double stop wider than an octave is almost always a detection artifact
        if len(g) == 2 and abs(g[0]["pitch"] - g[1]["pitch"]) > 12:
            g = g[:1]
        out.append(sorted(g, key=lambda n: -n["pitch"]))
    return out


def beat_grid(path, bpm=None):
    y, sr = librosa.load(path, sr=22050, mono=True)
    if bpm:
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, bpm=bpm, units="time", tightness=400)
    else:
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    tempo = float(np.atleast_1d(tempo)[0])
    beats = np.asarray(beats, dtype=float)
    # pad the grid so notes before the first / after the last beat still land somewhere
    period = 60.0 / tempo
    pre = np.arange(beats[0] - period, -period, -period)[::-1] if len(beats) else np.array([])
    beats = np.concatenate([pre, beats])
    post = np.arange(beats[-1] + period, len(y) / sr + 2 * period, period)
    beats = np.concatenate([beats, post])
    steps = []
    for a, b in zip(beats[:-1], beats[1:]):
        steps.extend(a + (b - a) * k / STEPS_PER_BEAT for k in range(STEPS_PER_BEAT))
    return tempo, np.array(steps)


def candidates(pitch):
    return [(s, pitch - open_) for s, open_ in enumerate(TUNING) if 0 <= pitch - open_ <= MAX_FRET]


def assign_frets(groups):
    """Viterbi over playable fingerings: minimise hand movement, prefer the
    5th-12th fret blues box area, keep double stops on adjacent strings."""
    def options(group):
        if len(group) == 1:
            return [((c,),) for c in candidates(group[0]["pitch"])]
        opts = []
        for a in candidates(group[0]["pitch"]):
            for b in candidates(group[1]["pitch"]):
                if a[0] < b[0] and abs(a[1] - b[1]) <= 4:
                    opts.append(((a, b),))
        return opts or [((c,),) for c in candidates(group[0]["pitch"])]

    def pos(opt):
        frets = [f for _, f in opt[0] if f > 0]
        return sum(frets) / len(frets) if frets else None

    def local_cost(opt):
        p = pos(opt)
        cost = 0.0
        if p is not None:
            cost += 0.15 * max(0, 5 - p) + 0.1 * max(0, p - 15)
        # open strings rarely belong in a fretted blues lead line
        cost += 1.5 * sum(1 for _, f in opt[0] if f == 0)
        if len(opt[0]) == 2:
            cost += 2 * (opt[0][1][0] - opt[0][0][0] - 1)
        return cost

    def trans_cost(prev, opt, prev_pos):
        p = pos(opt)
        if p is None or prev_pos is None:
            return 0.0
        jump = abs(p - prev_pos)
        return 0.0 if jump <= 3 else (jump - 3) * 1.0

    layers = [options(g) for g in groups]
    costs = [[local_cost(o) for o in layers[0]]]
    back = [[None] * len(layers[0])]
    for i in range(1, len(layers)):
        row, brow = [], []
        for o in layers[i]:
            best, arg = math.inf, 0
            for j, po in enumerate(layers[i - 1]):
                c = costs[-1][j] + trans_cost(po, o, pos(po))
                if c < best:
                    best, arg = c, j
            row.append(best + local_cost(o))
            brow.append(arg)
        costs.append(row)
        back.append(brow)
    idx = int(np.argmin(costs[-1]))
    path = []
    for i in range(len(layers) - 1, -1, -1):
        path.append(layers[i][idx][0])
        idx = back[i][idx] if back[i][idx] is not None else 0
    return path[::-1]


@dataclass
class Bar:
    time: float  # seconds into the source video where the bar starts
    cells: dict  # step within bar -> {string index: (fret, bend semitones)}


@dataclass
class TabLayout:
    tempo: float
    key: str
    steps_per_bar: int
    bars: list = field(default_factory=list)


NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
# Krumhansl-Kessler key profiles
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def detect_key(groups):
    hist = np.zeros(12)
    for g in groups:
        for n in g:
            hist[n["pitch"] % 12] += (n["end"] - n["t"]) * n["amp"]
    if not hist.any():
        return "?"
    best, name = -2.0, "?"
    for tonic in range(12):
        for profile, mode in ((MAJOR_PROFILE, "major"), (MINOR_PROFILE, "minor")):
            r = np.corrcoef(hist, np.roll(profile, tonic))[0, 1]
            if r > best:
                best, name = r, f"{NOTE_NAMES[tonic]} {mode}"
    return name


def layout(groups, fingerings, steps, tempo, time_offset=0.0):
    steps_per_bar = STEPS_PER_BEAT * BEATS_PER_BAR
    tab = TabLayout(tempo=tempo, key=detect_key(groups), steps_per_bar=steps_per_bar)
    cells = {}
    for g, fing in zip(groups, fingerings):
        st = int(np.argmin(np.abs(steps - g[0]["t"])))
        for note, (s, f) in zip(g, fing):
            # bend in semitones: 0 none, 1 half-step, 2 whole-step ("full")
            bend = 2 if note["bend"] >= 1.5 else 1 if note["bend"] >= 0.75 else 0
            cells.setdefault(st, {})[s] = (f, bend)
    if not cells:
        return tab
    for b in range(min(cells) // steps_per_bar, max(cells) // steps_per_bar + 1):
        t = max(0.0, steps[min(b * steps_per_bar, len(steps) - 1)]) + time_offset
        bar_cells = {k: cells[b * steps_per_bar + k] for k in range(steps_per_bar)
                     if b * steps_per_bar + k in cells}
        tab.bars.append(Bar(t, bar_cells))
    return tab


def fmt_time(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def render_text(tab, bars_per_line=4):
    if not tab.bars:
        return "No lead notes detected in this section.\n"
    width = 3
    out = [f"Key: {tab.key} (estimated). Tempo ~{tab.tempo:.0f} BPM, 4/4, each column = 1/16 note.",
           "Standard tuning (EADGBe). b = bend (roughly a semitone or more).",
           "Bar labels show the time in the recording.", ""]
    for i in range(0, len(tab.bars), bars_per_line):
        bars = tab.bars[i:i + bars_per_line]
        out.append("  " + "".join(fmt_time(b.time).ljust(tab.steps_per_bar * width + 1) for b in bars).rstrip())
        for s, name in enumerate(STRING_NAMES):
            row = name + "|"
            for b in bars:
                for k in range(tab.steps_per_bar):
                    cell = b.cells.get(k, {}).get(s)
                    txt = f"{cell[0]}{'b' if cell[1] else ''}" if cell else "-"
                    row += txt.ljust(width, "-")
                row += "|"
            out.append(row)
        out.append("")
    return "\n".join(out)


def transcribe(guitar_wav, out_prefix, mix_wav=None, bpm=None, min_pitch=55, time_offset=0.0):
    """Run the whole audio -> tab step. Writes OUT_PREFIX.txt/.mid and returns
    (TabLayout, tab_text, summary). time_offset shifts bar labels, for clips cut from a longer video."""
    midi, notes = detect_notes(guitar_wav)
    midi.write(out_prefix + ".mid")
    groups = clean_lead(notes, min_pitch=min_pitch)
    if not groups:
        tab = TabLayout(tempo=0.0, key="?", steps_per_bar=STEPS_PER_BEAT * BEATS_PER_BAR)
    else:
        tempo, steps = beat_grid(mix_wav or guitar_wav, bpm)
        tab = layout(groups, assign_frets(groups), steps, tempo, time_offset=time_offset)
    text = render_text(tab)
    with open(out_prefix + ".txt", "w", encoding="utf-8") as f:
        f.write(text)
    summary = f"{len(groups)} notes, key {tab.key}, tempo {tab.tempo:.0f} BPM, {len(tab.bars)} bars"
    return tab, text, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guitar_wav")
    ap.add_argument("out_prefix")
    ap.add_argument("--mix", help="full mix used for beat tracking (defaults to the guitar file)")
    ap.add_argument("--bpm", type=float, help="tempo hint for beat tracking")
    ap.add_argument("--min-pitch", type=int, default=55,
                    help="drop notes below this MIDI pitch (default 55 = G3) to filter rhythm guitar")
    args = ap.parse_args()

    tab, _, summary = transcribe(args.guitar_wav, args.out_prefix, args.mix, args.bpm, args.min_pitch)
    import pdf_export
    pdf_export.write_pdf(tab, args.out_prefix + ".pdf", title=os.path.basename(args.guitar_wav))
    print(summary)


if __name__ == "__main__":
    main()
