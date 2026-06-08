"""Render captions to SRT (landscape) and karaoke ASS (vertical)."""

from __future__ import annotations

from pathlib import Path

from ..config import (ASS_FONT, ASS_FONTSIZE, ASS_MARGIN_LR, ASS_MARGIN_V,
                      ASS_OUTLINE, HIGHLIGHT_COLOUR, LINE_MAX_CHARS, OUT_H, OUT_W)


def srt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _split_two_lines(tokens: list[str]) -> int:
    """Index where to break a caption into two balanced lines. 0 = single line."""
    if len(tokens) < 2 or len(" ".join(tokens)) <= LINE_MAX_CHARS:
        return 0
    best_i, best_diff = 1, None
    for i in range(1, len(tokens)):
        diff = abs(len(" ".join(tokens[:i])) - len(" ".join(tokens[i:])))
        if best_diff is None or diff < best_diff:
            best_diff, best_i = diff, i
    return best_i


def _layout(cap):
    """(word list, two-line break index) for a caption."""
    tokens = [t for _, _, t in cap]
    return tokens, _split_two_lines(tokens)


def write_srt(captions, path: Path):
    """Write captions as SRT (two lines max), one entry per caption."""
    blocks = []
    for i, cap in enumerate(captions, 1):
        tokens, brk = _layout(cap)
        text = " ".join(tokens) if not brk else \
            " ".join(tokens[:brk]) + "\n" + " ".join(tokens[brk:])
        blocks.append(
            f"{i}\n{srt_timestamp(cap[0][0])} --> {srt_timestamp(cap[-1][1])}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def _ass_ts(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(captions, path: Path):
    """Write a karaoke ASS file: the word being spoken is red, the others white;
    one event per word, at most two balanced lines."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{ASS_FONT},{ASS_FONTSIZE},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{ASS_OUTLINE},0,2,{ASS_MARGIN_LR},{ASS_MARGIN_LR},{ASS_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text
"""
    events = []
    for cap in captions:
        tokens, brk = _layout(cap)
        n = len(cap)
        for i in range(n):
            start = cap[i][0]
            end = cap[i + 1][0] if i + 1 < n else cap[i][1]
            if end <= start:
                end = start + 0.08
            rendered = [
                (r"{\1c" + HIGHLIGHT_COLOUR + r"}" + tok + r"{\1c&HFFFFFF&}")
                if j == i else tok
                for j, tok in enumerate(tokens)
            ]
            text = " ".join(rendered) if not brk else \
                " ".join(rendered[:brk]) + r"\N" + " ".join(rendered[brk:])
            events.append(
                f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Default,,0,0,0,,{text}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
