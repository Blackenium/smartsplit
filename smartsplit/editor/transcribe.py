"""Transcribe a clip with faster-whisper and group words into short captions."""

from __future__ import annotations

from pathlib import Path

from ..config import MAX_CAPTION_CHARS, MAX_CAPTION_SECONDS, MAX_CAPTION_WORDS
from ..console import step_done, step_progress


def _merge_words(words):
    """faster-whisper words -> (start, end, text), re-gluing elisions and attached
    punctuation (t + 'es -> t'es ; l' + eau -> l'eau ; word + , -> word,)."""
    out: list[tuple[float, float, str]] = []
    for w in words:
        txt = w.word.strip()
        if not txt:
            continue
        glue_to_prev = out and (
            txt[0] in "'’,.!?;:…)»"      # starts with apostrophe/punctuation
            or out[-1][2][-1] in "'’("            # or previous ends with an apostrophe
        )
        if glue_to_prev:
            ps, _, pt = out[-1]
            out[-1] = (ps, w.end, pt + txt)
        else:
            out.append((w.start, w.end, txt))
    return out


def _chunk_words(merged):
    """Group (start, end, word) tuples into captions (list of word lists)."""
    captions, buf = [], []

    def chars():
        return sum(len(t) for _, _, t in buf) + max(0, len(buf) - 1)

    def flush():
        if buf:
            captions.append(buf.copy())
        buf.clear()

    for s, e, txt in merged:
        if buf and (
            chars() + 1 + len(txt) > MAX_CAPTION_CHARS
            or len(buf) >= MAX_CAPTION_WORDS
            or (e - buf[0][0]) > MAX_CAPTION_SECONDS
        ):
            flush()
        buf.append((s, e, txt))
        if txt.endswith((".", "!", "?", "…", ":")):
            flush()
    flush()
    return captions


def transcribe(model, clip: Path, language) -> tuple[list, str]:
    """Transcribe a clip into short captions. Returns (captions, language).

    captions: list of captions; each caption is a list of (start, end, word).
    """
    segments, info = model.transcribe(str(clip), language=language, beam_size=5,
                                      vad_filter=True, word_timestamps=True)
    dur = info.duration or 1.0
    captions = []
    for seg in segments:
        step_progress("transcribing", seg.end / dur)
        if seg.words:
            captions.extend(_chunk_words(_merge_words(seg.words)))
        elif seg.text.strip():            # fallback if no word timestamps
            captions.append([(seg.start, seg.end, seg.text.strip())])
    step_done("transcribing")
    return captions, info.language
