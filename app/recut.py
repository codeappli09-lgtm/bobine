"""Redécoupage : vidéo existante → transcription → meilleurs moments → clips verticaux."""
from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable

from . import config, llm, moments, reframe, subtitles, transcribe
from .media import probe_duration, run_ffmpeg, x264

Progress = Callable[[str, float, str], None]
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[\w-]{4,64}", value or ""):
        raise ValueError("Identifiant invalide.")
    return value


def source_dir(source_id: str) -> Path:
    return config.SOURCES_DIR / _safe_id(source_id)


def source_file(source_id: str) -> Path:
    folder = source_dir(source_id)
    for p in folder.glob("source.*"):
        return p
    raise ValueError("Vidéo source introuvable : renvoie le fichier.")


def register(source_id: str, original_name: str) -> dict:
    """Vérifie le fichier reçu et note ses caractéristiques."""
    path = source_file(source_id)
    info = reframe.probe(path)
    if info["duration"] < 5:
        raise ValueError("Cette vidéo est trop courte pour être redécoupée.")
    if not info["audio"]:
        raise ValueError("Cette vidéo n'a pas de son : impossible de trouver les moments forts.")
    info.update({"id": source_id, "nom": original_name, "recu_le": time.strftime("%Y-%m-%d %H:%M")})
    (source_dir(source_id) / "info.json").write_text(
        json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def source_info(source_id: str) -> dict:
    return json.loads((source_dir(source_id) / "info.json").read_text(encoding="utf-8"))


def list_sources() -> list[dict]:
    items = []
    for f in config.SOURCES_DIR.glob("*/info.json"):
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        info["transcrite"] = (f.parent / "transcription.json").exists()
        items.append(info)
    return sorted(items, key=lambda i: i["id"], reverse=True)


# --- Étape 1 : trouver les moments ------------------------------------------------
def analyse(source_id: str, count: int, length: str, use_ai: bool, progress: Progress) -> dict:
    path = source_file(source_id)
    info = source_info(source_id)
    transcript = transcribe.transcribe(
        path, source_dir(source_id),
        lambda frac, msg: progress("transcription", frac, msg))

    ai_ok = use_ai and llm.status()["ok"]
    note = "" if ai_ok or not use_ai else "IA indisponible : passages repérés sans IA."
    progress("moments", 0, "Recherche des meilleurs moments")
    clips, ph, extra_note = moments.find_moments(
        transcript, count, length, ai_ok,
        lambda frac, msg: progress("moments", frac, msg))
    note = note or extra_note

    progress("cadrage", 0, "Repérage du cadrage de chaque clip")
    for n, clip in enumerate(clips):
        progress("cadrage", n / max(len(clips), 1), f"Cadrage du clip {n + 1}/{len(clips)}")
        mode, face_x = reframe.choose_mode(path, info, clip["start"], clip["end"])
        clip["cadrage_auto"] = mode
        clip["cadrage"] = "auto"
        clip["visage_x"] = round(face_x, 3)

    return {"source": info, "clips": clips, "note": note,
            "duree_parlee": round(sum(p["end"] - p["start"] for p in ph))}


# --- Étape 2 : monter les clips ------------------------------------------------------
def _words_between(source_id: str, start: float, end: float) -> list[dict]:
    data = json.loads((source_dir(source_id) / "transcription.json").read_text(encoding="utf-8"))
    words = []
    for seg in data["segments"]:
        if seg["end"] < start or seg["start"] > end:
            continue
        for w in seg.get("words", []):
            if w["start"] >= start - 0.05 and w["end"] <= end + 0.15:
                words.append({"text": w["text"], "start": max(w["start"] - start, 0),
                              "end": max(w["end"] - start, 0.05)})
    return words


def render_clip(source_id: str, clip: dict, options: dict, clip_id: str, lot: str) -> dict:
    path = source_file(source_id)
    info = source_info(source_id)
    start = max(0.0, float(clip["start"]))
    end = min(float(clip["end"]), info["duration"])
    if end - start < 2:
        raise ValueError(f"Le clip « {clip.get('titre', '')} » dure moins de 2 secondes.")
    dur = end - start

    mode = clip.get("cadrage") or "auto"
    face_x = float(clip.get("visage_x") or 0.5)
    if mode == "auto":
        mode = clip.get("cadrage_auto") or ""
        if mode not in ("visage", "ecran", "centre"):
            mode, face_x = reframe.choose_mode(path, info, start, end)
    elif mode == "visage" and not clip.get("visage_x"):
        detected = reframe.detect_face_x(path, start, end)
        face_x = detected if detected is not None else 0.5

    out_dir = config.OUTPUT_DIR / clip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    title = clip.get("titre", "") if options.get("bandeau", True) else ""
    words = _words_between(source_id, start, end) if options.get("sous_titres", True) else []

    vf = reframe.video_filter(info, mode, face_x)
    if words or title:
        subtitles.build_ass(words, dur, out_dir / "sous-titres.ass", title=title,
                            highlight=options.get("couleur", "#FFD23F"),
                            upper=options.get("majuscules", True))
        fonts = str(config.FONTS_DIR).replace("\\", "/").replace(":", "\\:")
        vf += f";[v0]ass=sous-titres.ass:fontsdir='{fonts}'[v]"
        vout = "[v]"
    else:
        vout = "[v0]"

    args = ["-ss", f"{start:.3f}", "-i", str(path), "-t", f"{dur:.3f}",
            "-filter_complex", vf, "-map", vout]
    if info.get("audio"):
        args += ["-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                 "-c:a", "aac", "-b:a", "160k", "-ar", "44100"]
    args += [*x264(21), "-movflags", "+faststart", "video.mp4"]
    run_ffmpeg(args, what="Montage du clip", cwd=out_dir)
    (out_dir / "sous-titres.ass").unlink(missing_ok=True)

    final = out_dir / "video.mp4"
    run_ffmpeg(["-ss", str(min(1.0, dur / 2)), "-i", str(final), "-frames:v", "1",
                "-vf", "scale=360:-2", str(out_dir / "miniature.jpg")], what="Miniature")
    meta = {
        "id": clip_id,
        "type": "clip",
        "lot": lot,
        "cree_le": time.strftime("%Y-%m-%d %H:%M"),
        "titre": clip.get("titre", ""),
        "legende": clip.get("legende", ""),
        "hashtags": clip.get("hashtags", []),
        "duree": round(probe_duration(final), 1),
        "source": {"id": source_id, "nom": info.get("nom", ""), "debut": round(start, 2),
                   "fin": round(end, 2)},
        "cadrage": mode,
        "texte": clip.get("texte", ""),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return meta


def render_all(lot: str, source_id: str, clips: list[dict], options: dict,
               progress: Progress) -> dict:
    started = time.time()
    metas = []
    for n, clip in enumerate(clips):
        progress("montage", n / len(clips), f"Montage du clip {n + 1}/{len(clips)}")
        metas.append(render_clip(source_id, clip, options, f"{lot}-{n + 1:02d}", lot))
    progress("termine", 1, "Clips prêts")
    return {"lot": lot, "clips": metas, "temps_de_calcul": round(time.time() - started, 1)}


def lot_zip(lot: str) -> Path:
    """Tous les clips d'un lot + leurs légendes, dans un seul fichier."""
    _safe_id(lot)
    metas = []
    for f in config.OUTPUT_DIR.glob(f"{lot}-*/meta.json"):
        meta = json.loads(f.read_text(encoding="utf-8"))
        if meta.get("lot") == lot:
            metas.append(meta)
    if not metas:
        raise ValueError("Aucun clip pour ce lot.")
    metas.sort(key=lambda m: m["id"])
    zpath = config.OUTPUT_DIR / f"{lot}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        lines = []
        for n, m in enumerate(metas, 1):
            name = re.sub(r"[^\w -]", "", (m.get("titre") or "clip").replace("'", " ")).strip()[:40] or "clip"
            z.write(config.OUTPUT_DIR / m["id"] / "video.mp4", f"{n:02d} - {name}.mp4")
            lines.append(f"{n:02d} - {m.get('titre', '')}\n{m.get('legende', '')}\n"
                         f"{' '.join(m.get('hashtags', []))}\n")
        z.writestr("legendes.txt", "\n".join(lines))
    return zpath


def inbox_files() -> list[dict]:
    return [{"nom": p.name, "taille": p.stat().st_size}
            for p in sorted(config.INBOX_DIR.iterdir())
            if p.is_file() and p.suffix.lower() in VIDEO_EXT]


def import_from_inbox(name: str, source_id: str) -> dict:
    """Déplace une vidéo du dossier a-decouper vers les sources (sans copie)."""
    src = config.INBOX_DIR / Path(name).name
    if not src.is_file() or src.suffix.lower() not in VIDEO_EXT:
        raise ValueError("Vidéo introuvable dans le dossier a-decouper.")
    folder = config.SOURCES_DIR / _safe_id(source_id)
    folder.mkdir(parents=True)
    src.rename(folder / f"source{src.suffix.lower()}")
    try:
        return register(source_id, src.name)
    except ValueError:
        (folder / f"source{src.suffix.lower()}").rename(src)  # on remet le fichier en place
        shutil.rmtree(folder, ignore_errors=True)
        raise


def delete_source(source_id: str) -> None:
    shutil.rmtree(source_dir(source_id), ignore_errors=True)
