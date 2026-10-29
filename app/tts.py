"""Voix off : Edge TTS (voix neuronales gratuites) avec timing de chaque mot.
Secours : espeak-ng (robotique, mais hors ligne)."""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path

from . import config
from .media import probe_duration

TICKS = 10_000_000  # edge-tts compte en unités de 100 ns


class TTSError(RuntimeError):
    pass


def _align(text: str, boundaries: list[dict]) -> list[dict]:
    """Recolle chaque mot prononcé sur le texte d'origine (ponctuation et majuscules)."""
    words: list[dict] = []
    low = text.lower()
    cursor = 0
    for b in boundaries:
        token = b["text"].strip()
        if not token:
            continue
        tl = token.lower()
        # Morceau d'un mot déjà affiché (ex. « l' » puis « abeille ») : on prolonge.
        if words and "_tok_end" in words[-1]:
            inside = low.find(tl, words[-1]["_tok_end"], cursor)
            if inside != -1:
                words[-1]["end"] = b["end"]
                words[-1]["_tok_end"] = inside + len(tl)
                continue
        pos = low.find(tl, cursor)
        if pos == -1:
            words.append({"text": token, "start": b["start"], "end": b["end"]})
            continue
        end = pos + len(tl)
        while end < len(text) and not text[end].isspace():
            end += 1
        tail = re.match(r"[ \u00a0\u202f]?[!?:;»]+", text[end:])  # « zéro ! »
        if tail:
            end += tail.end()
        words.append({"text": text[pos:end], "start": b["start"], "end": b["end"],
                      "_tok_end": pos + len(tl)})
        cursor = end
    for w in words:
        w.pop("_tok_end", None)
    return words


async def _edge(text: str, voice: str, rate: str, out_mp3: Path) -> list[dict]:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    boundaries = []
    with open(out_mp3, "wb") as fh:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS
                boundaries.append({"text": chunk["text"], "start": start,
                                   "end": start + chunk["duration"] / TICKS})
    return boundaries


def _estimate_words(text: str, duration: float, lead: float = 0.05) -> list[dict]:
    tokens = text.split()
    if not tokens:
        return []
    weights = [len(t) + 2 for t in tokens]
    usable = max(duration - 2 * lead, 0.3)
    unit = usable / sum(weights)
    t, words = lead, []
    for tok, w in zip(tokens, weights):
        words.append({"text": tok, "start": t, "end": t + w * unit * 0.92})
        t += w * unit
    return words


def _to_wav(src: Path, dst: Path) -> None:
    subprocess.run(
        [config.FFMPEG, "-y", "-loglevel", "error", "-i", str(src),
         "-ar", "44100", "-ac", "1", str(dst)],
        check=True,
    )


def synthesize(text: str, voice: str, rate: str, workdir: Path, name: str) -> dict:
    """Crée workdir/name.wav et renvoie {path, duration, words, engine}."""
    mp3, wav = workdir / f"{name}.mp3", workdir / f"{name}.wav"
    errors = []
    try:
        boundaries = asyncio.run(_edge(text, voice, rate, mp3))
        if mp3.stat().st_size == 0:
            raise TTSError("audio vide")
        _to_wav(mp3, wav)
        duration = probe_duration(wav)
        words = _align(text, boundaries) or _estimate_words(text, duration)
        return {"path": wav, "duration": duration, "words": words, "engine": "edge"}
    except Exception as exc:  # réseau coupé, service indisponible…
        errors.append(f"Edge TTS : {exc}")

    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak:
        speed = 165
        if rate.endswith("%"):
            try:
                speed = int(165 * (1 + int(rate.rstrip("%")) / 100))
            except ValueError:
                pass
        raw = workdir / f"{name}.raw.wav"
        subprocess.run([espeak, "-v", "fr", "-s", str(speed), "-w", str(raw), text], check=True)
        _to_wav(raw, wav)
        duration = probe_duration(wav)
        return {"path": wav, "duration": duration,
                "words": _estimate_words(text, duration), "engine": "espeak"}

    raise TTSError(" ; ".join(errors) + " ; aucune voix de secours (installe espeak-ng).")
