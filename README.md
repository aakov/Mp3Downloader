# Media Downloader

A single-video downloader using CustomTkinter, yt-dlp and FFmpeg. Python 3.11+.

The interface uses muted red accents and defaults to light mode on first run. Use the
**Dark mode** switch in the header to switch between dark and light themes.
The theme applies immediately, including during a download.

## Run

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main.py
```

FFmpeg **and FFprobe** must be on PATH, in `ffmpeg/bin` beside the app,
or in an existing `ffmpeg-*/bin` directory beside the app. Nothing is installed
automatically. The existing bundled FFmpeg directory is detected.

Paste a URL. For video, click **Check link** to load the source's available
resolutions. In audio mode, paste a link and click **Download audio**. There is
no Check link step or bitrate selector: yt-dlp chooses the best available audio.
**Original** is the default audio format. It preserves the encoded audio (typically
Opus or M4A); extracting it from a video container uses stream copying. If a codec
cannot be copied, the app reports an error instead of silently converting it.
Choose **MP3** explicitly if needed for compatibility; this uses high-quality VBR
encoding and introduces another lossy conversion.
Video uses an MKV merge container to accommodate the source codecs without
re-encoding; a combined source may keep its original container.

The progress bar, size and ETA refer to the **current stream**. Separate audio
and video streams can each start at 0%. Conversion and merging are separate
stages with unknown duration. Completion is reported only after yt-dlp returns.
F11 toggles fullscreen; Escape leaves it. The window can also be resized/maximized.
**Cancel** stops an active link check, download, or FFmpeg operation. Partial files
are retained; retrying the same URL and format can resume supported downloads.
Controls unlock after the worker exits and its process tree is terminated.
Closing the app cancels the active operation before exiting. On Windows, the worker
and its FFmpeg children belong to a kill-on-close Job Object; they also stop if the
parent app exits unexpectedly. Other platforms use a separate process group.
Live streams are rejected by Check link; playlists are not supported.

Preferences are saved automatically to `preferences.json` beside the source app
(beside the executable for packaged builds). This remembers the output folder,
audio/video mode, audio format, theme, and preferred video resolution. A remembered
resolution is applied only after checking a new link; the nearest lower available
resolution is selected when possible. Pasted URLs are not saved. Invalid settings
fall back to defaults, and saves replace the preferences file atomically.

## Validation

```powershell
.\venv\Scripts\python.exe -m unittest -v
```

Tests use actual Tk widgets, simulated UI jobs, real worker/child-process cancellation,
and generated local audio fixtures. FFprobe checks that Original preserves encoded
audio packets and that MP3 produces MP3 audio. No Internet downloads are required.
A display and the runtime dependencies are required; audio integration tests also
need FFmpeg/FFprobe. Tests keep preferences in temporary folders in the workspace.

## Next improvements

* Keep the GUI separate from download policy (`downloader.py`), process management
  (`jobs.py`, `worker.py`), and persisted settings (`preferences.py`).
* Add download history, an Open folder action, and a queue if needed.
* Add rotating diagnostic logs and display actionable extraction/network errors.
* Keep yt-dlp current: extraction changes as websites change. Validate updates on
  representative links, then lock tested versions for a release. Current official
  dependency guidance also covers FFmpeg and JavaScript support:
  https://github.com/yt-dlp/yt-dlp#dependencies
* Before distributing an executable, update and test `main.spec`, including
  CustomTkinter assets and an explicit FFmpeg distribution strategy. The old spec
  is retained but has not been validated for this version.
