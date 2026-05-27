# SmartSplit

Turn a long landscape video into short, vertical (9:16) clips ready for
**TikTok** and **YouTube Shorts**, with automatic **face tracking** and burned-in
**karaoke subtitles**. Subtitles are generated locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper); reframing and face
detection use [OpenCV](https://opencv.org/) (YuNet).

## Features

- **Vertical 9:16 output** (1080x1920), ready for phones.
- **Dynamic face tracking**: the crop follows the main speaker's face across each
  clip, with a smoothed path to avoid jitter (falls back to a center crop when no
  face is found).
- **Karaoke subtitles**: each word turns red as it is spoken; never more than two
  balanced lines on screen at once.
- **Per-platform output**: TikTok (clips longer than 60s) and YouTube Shorts
  (clips of 59s or less), each in its own subfolder.
- **Robust batch processing**: a corrupt or unreadable clip is skipped, the rest
  of the video keeps going.

## Requirements

- macOS or Linux, Python 3.8+
- **`ffmpeg-full`** (not the slim `ffmpeg`): burning subtitles uses the
  `subtitles`/`ass` filter, which depends on **libass**. Homebrew's default
  `ffmpeg` formula does **not** include libass; `ffmpeg-full` does.

  ```bash
  brew install ffmpeg-full
  ```

  `ffmpeg-full` is keg-only, so it installs alongside any existing `ffmpeg`
  without replacing it. SmartSplit detects it automatically; otherwise set the
  path with `FFMPEG=/path/to/ffmpeg`.

## Installation

```bash
git clone git@github.com:Blackenium/smartsplit.git
cd smartsplit
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Face tracking uses the bundled YuNet model
(`models/face_detection_yunet_2023mar.onnx`). If it is missing, re-download it:

```bash
mkdir -p models
curl -fsSL -o models/face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
```

## Usage

```bash
source venv/bin/activate

# Default: both platforms (tiktok 90s + youtube 59s), 9:16, face tracking, FR subtitles
python3 split_and_subtitle.py "input_videos/my_video.mp4"

# A single platform
python3 split_and_subtitle.py "input_videos/my_video.mp4" --platform tiktok
python3 split_and_subtitle.py "input_videos/my_video.mp4" --platform youtube

# TikTok clip length (must be > 60)
python3 split_and_subtitle.py "input_videos/my_video.mp4" --tiktok-duration 120

# Better subtitle accuracy (slower)
python3 split_and_subtitle.py "input_videos/my_video.mp4" --model small

# Fixed center crop (no face detection)
python3 split_and_subtitle.py "input_videos/my_video.mp4" --reframe center

# Keep the original aspect ratio, subtitles only
python3 split_and_subtitle.py "input_videos/my_video.mp4" --reframe none
```

Quote the file name if it contains spaces or special characters.

### Options

| Option | Default | Description |
|---|---|---|
| `--platform` | `both` | Platform(s) to generate: `tiktok`, `youtube`, or `both` |
| `--tiktok-duration` | `90` | Max TikTok clip length in seconds (should be > 60) |
| `--youtube-duration` | `59` | Max YouTube Shorts length in seconds (capped at 59) |
| `--max-duration` | - | *(deprecated)* alias for `--tiktok-duration` |
| `--model` | `base` | Whisper model: `tiny`/`base` (fast), `small` (better French), `medium`/`large-v3` (slow) |
| `--language` | `fr` | ISO language code, or `auto` to detect |
| `--reframe` | `track` | `track` = follow the face, `center` = fixed center crop, `none` = keep original |
| `--limit N` | - | Quick test: only process the first N clips per platform |
| `--start SECONDS` | `0` | Start reading the source at this second (e.g. to skip an intro) |
| `--out-dir DIR` | - | Output directory (default `<video>_final/`); the `tiktok/` and `youtube/` subfolders are created inside |
| `--keep-clips` | - | Keep the intermediate raw clip folders |

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

All clips are 1080x1920 (H.264 + AAC) with burned-in subtitles. The intermediate
raw clip folders (`.clips_tiktok/`, `.clips_youtube/`) are removed at the end
unless `--keep-clips` is passed.

## How face tracking works

1. Split the source into clips (stream copy, cut at keyframes).
2. Transcribe each clip with faster-whisper into short captions.
3. **Face analysis**: YuNet detects the main face on roughly 5 frames per second,
   builds the center path, and smooths it to avoid jitter. With no face on the
   clip, it falls back to a center crop.
4. **Reframe and burn**: each frame is cropped to 9:16 around the tracked face,
   resized to 1080x1920, then piped to ffmpeg, which burns the subtitles and
   remuxes the audio (a single re-encode).

## Subtitle appearance

In vertical mode (`track` / `center`), subtitles are rendered as **karaoke**: the
word currently being spoken turns red while the others stay white (an ASS file is
generated from word-level timestamps, one event per word). Captions are kept short
so that no more than two lines appear on screen at once.

Tunable constants at the top of `split_and_subtitle.py`:

- `MAX_CAPTION_CHARS` / `MAX_CAPTION_WORDS` / `MAX_CAPTION_SECONDS` - caption size
- `LINE_MAX_CHARS` - target length of a single line (two-line balancing)
- `ASS_FONTSIZE` - font size (on a 1080x1920 canvas)
- `ASS_MARGIN_V` - distance from the bottom; `ASS_MARGIN_LR` - side margins; `ASS_OUTLINE` - outline
- `HIGHLIGHT_COLOUR` - color of the spoken word, in ASS `\1c` order (Blue, Green, Red):
  red = `&H0000FF&`, yellow = `&H00FFFF&`, green = `&H00FF00&`, cyan = `&HFFFF00&`

If a caption ever exceeds two lines, `ASS_FONTSIZE` is too large for
`MAX_CAPTION_CHARS`: lower one of them.

In `--reframe none` mode (landscape), subtitles are plain white (no karaoke).

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

## Notes

- **Speed**: `track` adds a face-analysis pass and one re-encode per clip, so it
  is noticeably slower than `--reframe none`. The Whisper model is downloaded on
  first run. Use `--model tiny` for speed, `--model small` for better French.
- **Clip lengths**: stream-copy splitting cuts at keyframes, so raw clips may run
  slightly over the target. The final clips are trimmed to the platform limit
  (this guarantees `<= 59s` for YouTube Shorts).
- **Disk space**: keep 2-3x the source video size free.
- A harmless `objc[...] Class AVF... libavdevice` warning may appear at startup
  because OpenCV and PyAV each bundle ffmpeg libraries; it does not affect output.

## Acknowledgements

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) - transcription
- [OpenCV Zoo - YuNet](https://github.com/opencv/opencv_zoo) - face detection
- [FFmpeg](https://ffmpeg.org/) / [libass](https://github.com/libass/libass) - encoding and subtitles
