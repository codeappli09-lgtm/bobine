"""Sous-titres façon TikTok (fichier .ass) : 1 à 3 mots, le mot prononcé surligné."""
from __future__ import annotations

import re
from pathlib import Path

from . import config


def _ass_color(hex_color: str) -> str:
    """#RRGGBB → &HBBGGRR& (couleur ASS en ligne)."""
    h = hex_color.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "FFD23F"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{b}{g}{r}&".upper()


def _ts(seconds: float) -> str:
    cs = int(round(max(seconds, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _display(word: str, upper: bool) -> str:
    word = re.sub(r"[,.;:…»«\"“”]+$", "", word)
    word = re.sub(r"^[«\"“”(]+", "", word)
    word = word.replace("...", "")
    return word.upper() if upper else word


def chunk_words(words: list[dict], max_words: int = 3, max_chars: int = 16) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    for i, w in enumerate(words):
        if current:
            chars = sum(len(x["text"]) + 1 for x in current) + len(w["text"])
            gap = w["start"] - current[-1]["end"]
            if len(current) >= max_words or chars > max_chars or gap > 0.35:
                chunks.append(current)
                current = []
        current.append(w)
        if re.search(r"[.!?;:,…]$", w["text"]):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Inter Display Black,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,9,4,5,90,130,0,1
Style: Banner,Inter Display ExtraBold,58,&H00141414,&H00141414,&H00FFFFFF,&H64000000,0,0,0,0,100,100,0,0,3,20,0,8,110,110,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(words: list[dict], total: float, out: Path, title: str = "",
              highlight: str = "#FFD23F", upper: bool = True, size: int = 104,
              y: int = 1290) -> Path:
    hl = _ass_color(highlight)
    lines = [HEADER.format(w=config.WIDTH, h=config.HEIGHT, size=size)]

    if title.strip():
        banner = _esc(title.strip())
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(total)},Banner,,0,0,0,,{{\\fad(250,0)}}{banner}")

    chunks = chunk_words(words)
    for ci, chunk in enumerate(chunks):
        start = chunk[0]["start"]
        if ci + 1 < len(chunks):
            nxt = chunks[ci + 1][0]["start"]
            end = nxt if nxt - chunk[-1]["end"] < 0.6 else chunk[-1]["end"] + 0.25
        else:
            end = min(chunk[-1]["end"] + 0.5, total)
        texts = [_esc(_display(w["text"], upper)) for w in chunk]
        for wi, w in enumerate(chunk):
            w_start = start if wi == 0 else w["start"]
            w_end = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else end
            if w_end <= w_start:
                continue
            parts = []
            for k, t in enumerate(texts):
                if not t:
                    continue
                parts.append(f"{{\\c{hl}}}{t}{{\\c&HFFFFFF&}}" if k == wi else t)
            pop = "\\fscx78\\fscy78\\t(0,90,\\fscx100\\fscy100)" if wi == 0 else ""
            lines.append(
                f"Dialogue: 0,{_ts(w_start)},{_ts(w_end)},Sub,,0,0,0,,"
                f"{{\\an5\\pos({config.WIDTH // 2 - 20},{y}){pop}}}" + " ".join(parts)
            )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
