# GuitarTabsFromVideo

**Guitar Tabber** is a desktop app that turns a guitar solo in a video into a printable PDF tab sheet.
Paste a YouTube link (or pick a local audio/video file), choose the section, press
**Generate tab**.

How it works:

1. **yt-dlp** downloads just the chosen section's audio.
2. **Demucs** (`htdemucs_6s`) isolates the guitar from the band.
3. **basic-pitch** detects the notes; low notes (rhythm guitar) and ghost notes are filtered out.
4. **librosa** tracks the beat; notes are quantised to a 16th-note grid.
5. A dynamic-programming fingering pass picks string/fret positions that keep the hand in one area of the neck.
6. **reportlab** lays out an A4 PDF: key/tempo/tuning header, six-line TAB staves, bend arrows (½ / full),
   bar numbers and the video timestamp of every bar.

You also get a plain-text tab and a MIDI file of the detected notes.

## Setup (Windows)

```
winget install Python.Python.3.11
winget install Gyan.FFmpeg
```

Then double-click **`Guitar Tabber.bat`**. The first run creates a virtual environment in
`%LOCALAPPDATA%\guitar-tab-venv` and installs the requirements (about 3 GB, mostly PyTorch).

Manual setup on any OS:

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # .venv\Scripts\pip on Windows
.venv/bin/python app.py
```

Command line, for an already-separated guitar track:

```
python tab_core.py guitar.wav out/solo --mix full_mix.wav
```

## Limitations

The output is a **draft** to check by ear:

- Only bends are detected. Slides, hammer-ons, pull-offs and vibrato are not.
- Fingering is a best guess and may differ from what the player actually did.
- Tempo detection can land on double or half time, and triplet or shuffle feel is forced onto a 16th grid.
  Use the *BPM hint* field if the bars look wrong.
- Lead and rhythm guitar end up in the same separated track. *Lowest note* filters out most of the rhythm part.

Processing caches each step in `%LOCALAPPDATA%\guitar-tab-work\jobs`, so re-running the same section
with different settings is fast.

Only download videos you have the right to download. Generated tabs are for personal practice.
