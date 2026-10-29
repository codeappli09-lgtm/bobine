"""Transcription mot à mot d'une vidéo (faster-whisper, gratuit, sur le processeur)."""
from __future__ import annotations

import gc
import json
import threading
from pathlib import Path
from typing import Callable

from . import config
from .media import run_ffmpeg

_MODEL = None
_MODEL_LOCK = threading.Lock()


class TranscribeError(RuntimeError):
    pass


def _model():
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscribeError(
                    "faster-whisper n'est pas installé : lance « pip install -r requirements.txt »."
                ) from exc
            try:
                _MODEL = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
            except Exception as exc:
                raise TranscribeError(
                    f"Impossible de charger le modèle de transcription « {config.WHISPER_MODEL} ». "
                    "Au premier usage il se télécharge (quelques centaines de Mo) : "
                    "vérifie que le Codespace a accès à Internet, puis réessaie."
                ) from exc
        return _MODEL


def release_model() -> None:
    global _MODEL
    with _MODEL_LOCK:
        _MODEL = None
    gc.collect()


def transcribe(video: Path, workdir: Path, progress: Callable[[float, str], None]) -> dict:
    """Renvoie {duration, language, segments:[{start,end,text,words:[{text,start,end}]}]}.
    Le résultat est gardé dans workdir/transcription.json pour ne pas recommencer."""
    cache = workdir / "transcription.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("model") == config.WHISPER_MODEL:
            progress(1.0, "Transcription déjà faite")
            return data

    audio = workdir / "audio16k.wav"
    progress(0.0, "Extraction du son")
    run_ffmpeg(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)],
               what="Extraction du son")

    progress(0.0, f"Chargement du modèle de transcription ({config.WHISPER_MODEL})")
    model = _model()
    lang = config.WHISPER_LANG or None
    segments_iter, info = model.transcribe(
        str(audio), language=lang, word_timestamps=True, vad_filter=True, beam_size=5,
    )
    total = max(info.duration, 0.1)
    segments = []
    for seg in segments_iter:
        words = [{"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
                 for w in (seg.words or []) if w.word.strip()]
        text = seg.text.strip()
        if not text:
            continue
        segments.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                         "text": text, "words": words})
        done = min(seg.end / total, 1.0)
        progress(done, f"Transcription : {int(seg.end // 60)} min {int(seg.end % 60):02d} "
                       f"sur {int(total // 60)} min {int(total % 60):02d}")
    audio.unlink(missing_ok=True)
    del model, segments_iter
    release_model()  # rend la mémoire pour Qwen et le montage
    if not segments:
        raise TranscribeError("Aucune parole détectée dans cette vidéo.")
    data = {"model": config.WHISPER_MODEL, "language": info.language,
            "duration": total, "segments": segments}
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data
