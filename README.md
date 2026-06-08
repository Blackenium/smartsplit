# SmartSplit

**Download** source videos from **YouTube** and **Twitch**, then turn long
landscape videos into short, vertical **9:16** clips ready for **TikTok** and
**YouTube Shorts** — with automatic **face tracking** and burned-in **karaoke
subtitles**.

Subtitles are generated locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper); reframing and face
detection use [OpenCV](https://opencv.org/) (YuNet); downloading uses
[yt-dlp](https://github.com/yt-dlp/yt-dlp). Everything runs on your machine — no
API keys, no upload.

---

## Features

- **Scrapers** — fetch the latest upload(s) of a YouTube channel (by `@handle`,
  URL, or name) or VODs/clips from a Twitch channel, and optionally split them
  into clips in a single command (`--process`).
- **Vertical 9:16 output** (1080×1920), ready for phones.
- **Dynamic face tracking** — the crop follows the main speaker's face across
  each clip, with a smoothed path to avoid jitter (falls back to a center crop
  when no face is found).
- **Karaoke subtitles** — each word turns red as it is spoken; never more than
  two balanced lines on screen at once.
- **Per-platform output** — TikTok (clips longer than 60s) and YouTube Shorts
  (clips of 59s or less), each in its own subfolder.
- **Robust batch processing** — a corrupt or unreadable clip is skipped; the
  rest of the video keeps going.

---

## Project layout

```
smartsplit/                 Python package
├── __main__.py             enables `python3 -m smartsplit`
├── cli.py                  command-line interface (split | download)
├── config.py               all tunable constants
├── console.py              terminal progress bar + errors
├── ffmpeg.py               ffmpeg/ffprobe resolution + probing helpers
├── editor/                 the clip pipeline
│   ├── split.py            split a source into raw clips (stream copy)
│   ├── transcribe.py       faster-whisper → short captions
│   ├── captions.py         render SRT (landscape) and karaoke ASS (vertical)
│   ├── reframe.py          face tracking + 9:16 crop + subtitle burning
│   └── pipeline.py         per-video / per-platform orchestration
└── scrapers/               yt-dlp wrappers
    ├── common.py           list / extract / download helpers
    ├── youtube.py          channel resolution + upload selection
    └── twitch.py           VOD / clip selection
split_and_subtitle.py       backward-compatible shim → `smartsplit split`
models/                     bundled YuNet face-detection model
input_videos/               default download + input folder
```

Run it as `python3 -m smartsplit <command>`. The old
`python3 split_and_subtitle.py <video> ...` still works (it maps to `split`).

---

## Requirements

- **macOS or Linux**, **Python 3.8+** (3.10+ recommended — yt-dlp is dropping 3.9).
- **`ffmpeg-full`** (not the slim `ffmpeg`): burning subtitles uses the
  `subtitles`/`ass` filter, which depends on **libass**. Homebrew's default
  `ffmpeg` formula does **not** include libass; `ffmpeg-full` does.

  ```bash
  brew install ffmpeg-full
  ```

  `ffmpeg-full` is keg-only, so it installs alongside any existing `ffmpeg`
  without replacing it. SmartSplit detects it automatically; otherwise set the
  path with `FFMPEG=/path/to/ffmpeg`.

---

## Installation

```bash
git clone git@github.com:Blackenium/smartsplit.git
cd smartsplit
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Dependencies: `faster-whisper` (transcription), `opencv-python` (face detection
+ reframing), `yt-dlp` (downloads).

Face tracking uses the bundled YuNet model
(`models/face_detection_yunet_2023mar.onnx`). If it is missing, re-download it:

```bash
mkdir -p models
curl -fsSL -o models/face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
```

---

## Quick start

```bash
source venv/bin/activate

# 1) Split a local video into clips (both platforms, face tracking, FR subtitles)
python3 -m smartsplit split "input_videos/my_video.mp4"

# 2) Download the latest video from a YouTube channel
python3 -m smartsplit download youtube "@Inoxtag"

# 3) Download the 5 latest uploads AND split them into TikTok clips in one go
python3 -m smartsplit download youtube "@Inoxtag" --latest 5 --process --platform tiktok
```

Quote any name or path that contains spaces or special characters.

---

## Command: `split`

Turn a **local** video into vertical 9:16 clips.

```bash
# Default: both platforms (tiktok 90s + youtube 59s), 9:16, face tracking, FR subtitles
python3 -m smartsplit split "input_videos/my_video.mp4"

# A single platform
python3 -m smartsplit split "input_videos/my_video.mp4" --platform tiktok
python3 -m smartsplit split "input_videos/my_video.mp4" --platform youtube

# TikTok clip length (must be > 60)
python3 -m smartsplit split "input_videos/my_video.mp4" --tiktok-duration 120

# Better subtitle accuracy (slower)
python3 -m smartsplit split "input_videos/my_video.mp4" --model small

# Fixed center crop (no face detection)
python3 -m smartsplit split "input_videos/my_video.mp4" --reframe center

# Keep the original aspect ratio, subtitles only
python3 -m smartsplit split "input_videos/my_video.mp4" --reframe none
```

### Options

| Option | Default | Description |
|---|---|---|
| `--platform` | `both` | Platform(s) to generate: `tiktok`, `youtube`, or `both` |
| `--tiktok-duration` | `90` | Max TikTok clip length in seconds (should be > 60) |
| `--youtube-duration` | `59` | Max YouTube Shorts length in seconds (capped at 59) |
| `--max-duration` | – | *(deprecated)* alias for `--tiktok-duration` |
| `--model` | `base` | Whisper model: `tiny`/`base` (fast), `small` (better French), `medium`/`large-v3` (slow) |
| `--language` | `fr` | ISO language code, or `auto` to detect |
| `--reframe` | `track` | `track` = follow the face, `center` = fixed center crop, `none` = keep original |
| `--limit N` | – | Quick test: only process the first N clips (and only read the start of the source) |
| `--start SECONDS` | `0` | Start reading the source at this second (e.g. to skip an intro) |
| `--out-dir DIR` | `<video>_final/` | Output directory; the `tiktok/` and `youtube/` subfolders are created inside |
| `--keep-clips` | – | Keep the intermediate raw clip folders |

---

## Command: `download`

Fetch source videos with yt-dlp into `input_videos/` (override with `--dest`).
Add **`--process`** to split them into clips immediately, using the same editor
options as `split` (`--platform`, `--model`, `--reframe`, `--tiktok-duration`, …).

### `download youtube`

```bash
# The most recent upload of a channel (by @handle, URL, or name)
python3 -m smartsplit download youtube "@Inoxtag"
python3 -m smartsplit download youtube "Inoxtag"            # resolved by name
python3 -m smartsplit download youtube "https://www.youtube.com/watch?v=ID"  # one video

# The 10 most recent uploads
python3 -m smartsplit download youtube "@Inoxtag" --latest 10

# Only recent uploads whose title contains a word (scans the latest 100)
python3 -m smartsplit download youtube "@Inoxtag" --match "supercar"

# Download AND split into clips in one command
python3 -m smartsplit download youtube "@Inoxtag" --latest 5 --process --platform tiktok
```

| Option | Default | Description |
|---|---|---|
| `channel` | *(required)* | `@handle`, channel/video URL, or channel name |
| `--latest N` | `1` | Download the N most recent uploads |
| `--match TEXT` | – | Keep only uploads whose title contains TEXT (scans the latest 100) |
| `--dest DIR` | `input_videos/` | Download directory |
| `--process` | – | Split the downloaded videos into clips right away |

> **YouTube by name** picks the channel of the top search result, which is not
> always the official channel — prefer `@handle` or the channel URL when you can.

### `download twitch`

```bash
# Latest VODs / clips of a channel (login, URL, or name)
python3 -m smartsplit download twitch "anyme023" --kind vods  --latest 3
python3 -m smartsplit download twitch "anyme023" --kind clips --latest 10
python3 -m smartsplit download twitch "anyme023" --kind all   --latest 5

# A direct VOD or clip URL (most reliable — see caveat)
python3 -m smartsplit download twitch "https://www.twitch.tv/videos/123456789"

# Download AND split in one command
python3 -m smartsplit download twitch "anyme023" --kind clips --latest 10 --process
```

| Option | Default | Description |
|---|---|---|
| `channel` | *(required)* | Channel login, URL, or name (or a direct VOD/clip URL) |
| `--kind` | `vods` | What to fetch: `vods`, `clips`, or `all` |
| `--latest N` | `1` | Download the N most recent items |
| `--dest DIR` | `input_videos/` | Download directory |
| `--process` | – | Split the downloaded videos into clips right away |

> **Twitch caveat** — VODs expire after a while (often 7–60 days), so a channel
> can legitimately have none. Channel **clip listing** through yt-dlp can also
> return nothing when Twitch throttles its API. When listing comes up empty,
> pass a **direct VOD or clip URL** (it uses a different, more reliable
> extractor), or update yt-dlp: `pip install -U yt-dlp`.

With `--process`, all `split` options above are also accepted on the `download`
commands.

---

## Output

For `my_video.mp4` with `--platform both`:

```
my_video_final/
├── tiktok/
│   ├── my_video_01.mp4      # clips longer than 60s
│   └── my_video_02.mp4
└── youtube/
    ├── my_video_01.mp4      # Shorts, 59s or less
    └── my_video_02.mp4
```

All clips are 1080×1920 (H.264 + AAC) with burned-in subtitles. The intermediate
raw clip folders (`.clips_tiktok/`, `.clips_youtube/`) are removed at the end
unless `--keep-clips` is passed.

---

## How it works

1. **Split** the source into clips (stream copy, cut at keyframes).
2. **Transcribe** each clip with faster-whisper into short captions.
3. **Face analysis** — YuNet detects the main face on roughly 5 frames per
   second, builds the center path, and smooths it to avoid jitter. With no face
   on the clip, it falls back to a center crop.
4. **Reframe and burn** — each frame is cropped to 9:16 around the tracked face,
   resized to 1080×1920, then piped to ffmpeg, which burns the subtitles and
   remuxes the audio (a single re-encode).

---

## Subtitle appearance

In vertical mode (`track` / `center`), subtitles are rendered as **karaoke**: the
word currently being spoken turns red while the others stay white (an ASS file is
generated from word-level timestamps, one event per word). Captions are kept
short so that no more than two lines appear on screen at once.

Tunable constants live in `smartsplit/config.py`:

- `MAX_CAPTION_CHARS` / `MAX_CAPTION_WORDS` / `MAX_CAPTION_SECONDS` — caption size
- `LINE_MAX_CHARS` — target length of a single line (two-line balancing)
- `ASS_FONTSIZE` — font size (on a 1080×1920 canvas)
- `ASS_MARGIN_V` — distance from the bottom; `ASS_MARGIN_LR` — side margins;
  `ASS_OUTLINE` — outline thickness
- `HIGHLIGHT_COLOUR` — color of the spoken word, in ASS `\1c` order (Blue, Green,
  Red): red = `&H0000FF&`, yellow = `&H00FFFF&`, green = `&H00FF00&`,
  cyan = `&HFFFF00&`

If a caption ever exceeds two lines, `ASS_FONTSIZE` is too large for
`MAX_CAPTION_CHARS`: lower one of them.

In `--reframe none` mode (landscape), subtitles are plain white (no karaoke).

---

## Quick test

To preview the result on one or two videos without a full run, use `quicktest.sh`.
It processes only the first clip of each video, on a single platform (TikTok by
default), with the `tiny` model, and writes to `quicktest/` without touching your
real outputs.

```bash
./quicktest.sh                              # first 2 videos in input_videos/
./quicktest.sh "input_videos/my_video.mp4"  # a specific video
PLATFORM=both LIMIT=2 MODEL=small ./quicktest.sh
```

Environment variables: `MODEL` (default `tiny`), `LIMIT` (default `1`), `PLATFORM`
(default `tiktok`; `youtube` or `both`), `TIKTOKDUR` (default `90`), `START`
(default `120`, to skip the intro; set `START=0` for the very beginning),
`REFRAME` (default `track`).

Intros (title cards, music, channel branding) often contain no speech, so they
produce no subtitles. That is why the quick test starts at 120s by default, to
land on a spoken section.

---

## Notes

- **Speed** — `track` adds a face-analysis pass and one re-encode per clip, so it
  is noticeably slower than `--reframe none`. The Whisper model is downloaded on
  first run. Use `--model tiny` for speed, `--model small` for better French.
- **Clip lengths** — stream-copy splitting cuts at keyframes, so raw clips may
  run slightly over the target. The final clips are trimmed to the platform limit
  (this guarantees `<= 59s` for YouTube Shorts).
- **Disk space** — keep 2–3× the source video size free.
- A harmless `objc[...] Class AVF... libavdevice` warning may appear at startup
  because OpenCV and PyAV each bundle ffmpeg libraries; it does not affect output.
- Only download content you have the right to reuse, and respect each platform's
  terms of service.

---

## Acknowledgements

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — transcription
- [OpenCV Zoo — YuNet](https://github.com/opencv/opencv_zoo) — face detection
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube / Twitch downloads
- [FFmpeg](https://ffmpeg.org/) / [libass](https://github.com/libass/libass) —
  encoding and subtitles
