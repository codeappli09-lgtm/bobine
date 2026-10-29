"""Bobine — serveur web (FastAPI). Lancement : ./start.sh"""
from __future__ import annotations

import json
import secrets
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, extract, llm, pipeline, recut, scriptgen

app = FastAPI(title="Bobine")
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
SCRIPT_POOL = ThreadPoolExecutor(max_workers=1)
RENDER_POOL = ThreadPoolExecutor(max_workers=1)  # une vidéo à la fois sur 2 cœurs

STEP_RANGES = {"voix": (0.0, 0.25), "visuels": (0.25, 0.62), "sous-titres": (0.62, 0.66),
               "montage": (0.66, 0.98), "termine": (1.0, 1.0)}
ANALYSE_RANGES = {"transcription": (0.0, 0.75), "moments": (0.75, 0.93),
                  "cadrage": (0.93, 0.99), "termine": (1.0, 1.0)}
CLIPS_RANGES = {"montage": (0.0, 0.99), "termine": (1.0, 1.0)}


def _progress_for(job_id: str, ranges: dict):
    def progress(step: str, frac: float, message: str) -> None:
        lo, hi = ranges.get(step, (0, 1))
        _update(job_id, step=step, progress=round(lo + (hi - lo) * frac, 3), message=message)
    return progress


def _new_job(kind: str) -> str:
    job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    with LOCK:
        JOBS[job_id] = {"id": job_id, "kind": kind, "state": "attente", "step": "",
                        "progress": 0.0, "message": "En file d'attente", "result": None,
                        "error": None}
    return job_id


def _update(job_id: str, **fields) -> None:
    with LOCK:
        JOBS[job_id].update(fields)


# --- Modèles de requêtes -------------------------------------------------------
class ScriptRequest(BaseModel):
    source: str = Field(..., max_length=20000)
    duree: int = 45
    ton: str = "choc"
    cta: str = Field("", max_length=200)
    ia: bool = True


class Segment(BaseModel):
    texte: str = Field(..., max_length=500)
    visuel: str = Field("", max_length=80)


class Script(BaseModel):
    titre: str = Field("", max_length=120)
    segments: list[Segment]
    legende: str = Field("", max_length=400)
    hashtags: list[str] = []
    source: dict = {}


class VideoRequest(BaseModel):
    script: Script
    options: dict = {}


class AnalyseRequest(BaseModel):
    source: str
    nombre: int = 5
    longueur: str = "moyen"
    ia: bool = True


class Clip(BaseModel):
    start: float
    end: float
    titre: str = Field("", max_length=120)
    legende: str = Field("", max_length=400)
    hashtags: list[str] = []
    cadrage: str = "auto"
    cadrage_auto: str = ""
    visage_x: float | None = None
    texte: str = ""


class ClipsRequest(BaseModel):
    source: str
    clips: list[Clip]
    options: dict = {}


# --- Tâches de fond ------------------------------------------------------------
def _run_script(job_id: str, req: ScriptRequest) -> None:
    try:
        _update(job_id, state="en_cours", step="lecture", progress=0.1,
                message="Lecture du lien" if extract.is_url(req.source) else "Lecture de l'idée")
        source = extract.from_input(req.source)
        use_ai = req.ia
        note = ""
        if use_ai and not llm.status()["ok"]:
            use_ai, note = False, "IA indisponible : script simple tiré de la source."
        _update(job_id, step="ecriture", progress=0.35,
                message=f"Écriture du script avec {config.LLM_MODEL}" if use_ai
                else "Écriture du script (mode simple)")
        try:
            script = scriptgen.write_script(source, req.duree, req.ton, req.cta, use_ai=use_ai)
        except llm.LLMError as exc:
            script = scriptgen.write_script(source, req.duree, req.ton, req.cta, use_ai=False)
            note = f"L'IA a échoué ({exc}) : script simple tiré de la source."
        script["note"] = note
        _update(job_id, state="ok", step="termine", progress=1.0, message="Script prêt",
                result=script)
    except Exception as exc:
        traceback.print_exc()
        _update(job_id, state="erreur", message=str(exc), error=str(exc))


def _run_analyse(job_id: str, req: AnalyseRequest) -> None:
    try:
        _update(job_id, state="en_cours", message="Préparation")
        result = recut.analyse(req.source, req.nombre, req.longueur, req.ia,
                               _progress_for(job_id, ANALYSE_RANGES))
        _update(job_id, state="ok", step="termine", progress=1.0,
                message="Moments trouvés", result=result)
    except Exception as exc:
        traceback.print_exc()
        _update(job_id, state="erreur", message=str(exc), error=str(exc))


def _run_clips(job_id: str, req: ClipsRequest) -> None:
    try:
        _update(job_id, state="en_cours", message="Préparation")
        lot = job_id
        clips = [c.model_dump() for c in req.clips][:15]
        result = recut.render_all(lot, req.source, clips, req.options,
                                  _progress_for(job_id, CLIPS_RANGES))
        _update(job_id, state="ok", progress=1.0, message="Clips prêts", result=result)
    except Exception as exc:
        traceback.print_exc()
        _update(job_id, state="erreur", message=str(exc), error=str(exc))


def _run_render(job_id: str, req: VideoRequest) -> None:
    progress = _progress_for(job_id, STEP_RANGES)
    try:
        _update(job_id, state="en_cours", message="Préparation")
        script = req.script.model_dump()
        script["segments"] = [s for s in script["segments"] if s["texte"].strip()]
        if not script["segments"]:
            raise ValueError("Le script est vide.")
        script["segments"] = [
            {"texte": scriptgen.clean_spoken(s["texte"]), "visuel": s["visuel"]}
            for s in script["segments"][:20]
        ]
        meta = pipeline.render(job_id, script, req.options, progress)
        _update(job_id, state="ok", progress=1.0, message="Vidéo prête", result=meta)
    except Exception as exc:
        traceback.print_exc()
        _update(job_id, state="erreur", message=str(exc), error=str(exc))


# --- API -------------------------------------------------------------------------
@app.get("/api/etat")
def etat():
    return {
        "ia": llm.status(),
        "pexels": bool(config.PEXELS_API_KEY),
        "voix": config.VOICES,
        "musiques": pipeline.list_music(),
        "tons": list(scriptgen.TONES.keys()),
    }


@app.post("/api/script")
def create_script(req: ScriptRequest):
    if not req.source.strip():
        raise HTTPException(400, "Colle un lien ou écris une idée de vidéo.")
    job_id = _new_job("script")
    SCRIPT_POOL.submit(_run_script, job_id, req)
    return {"job": job_id}


@app.post("/api/video")
def create_video(req: VideoRequest):
    if not req.script.segments:
        raise HTTPException(400, "Le script est vide.")
    job_id = _new_job("video")
    RENDER_POOL.submit(_run_render, job_id, req)
    return {"job": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Tâche introuvable (le serveur a peut-être redémarré).")
    return job


@app.get("/api/videos")
def videos():
    items = []
    for meta_file in config.OUTPUT_DIR.glob("*/meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta.pop("script", None)
        items.append(meta)
    return sorted(items, key=lambda m: m["id"], reverse=True)


@app.get("/api/videos/{video_id}")
def video_detail(video_id: str):
    meta_file = config.OUTPUT_DIR / video_id / "meta.json"
    if "/" in video_id or ".." in video_id or not meta_file.exists():
        raise HTTPException(404, "Vidéo introuvable.")
    return json.loads(meta_file.read_text(encoding="utf-8"))


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str):
    folder = config.OUTPUT_DIR / video_id
    if "/" in video_id or ".." in video_id or not folder.is_dir():
        raise HTTPException(404, "Vidéo introuvable.")
    shutil.rmtree(folder)
    return {"supprime": video_id}


# --- Redécoupage -----------------------------------------------------------------
@app.post("/api/sources")
async def upload_source(request: Request, nom: str = "video.mp4"):
    """Reçoit le fichier brut (corps de la requête), sans copie intermédiaire."""
    ext = Path(nom).suffix.lower()
    if ext not in recut.VIDEO_EXT:
        raise HTTPException(400, "Format non pris en charge : envoie un .mp4, .mov, .mkv ou .webm.")
    source_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    folder = config.SOURCES_DIR / source_id
    folder.mkdir(parents=True)
    dest = folder / f"source{ext}"
    limit = int(config.MAX_UPLOAD_GB * 1024 ** 3)
    size = 0
    try:
        with open(dest, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Fichier trop lourd (plus de {config.MAX_UPLOAD_GB:g} Go).")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "Le fichier reçu est vide.")
        return recut.register(source_id, Path(nom).name)
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except ValueError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(400, str(exc))


@app.get("/api/sources")
def sources():
    return recut.list_sources()


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str):
    try:
        recut.source_dir(source_id)
    except ValueError:
        raise HTTPException(404, "Vidéo source introuvable.")
    recut.delete_source(source_id)
    return {"supprime": source_id}


@app.get("/api/dossier")
def inbox():
    return recut.inbox_files()


@app.post("/api/dossier/import")
def inbox_import(nom: str):
    source_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    try:
        return recut.import_from_inbox(nom, source_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/decoupe/analyse")
def analyse(req: AnalyseRequest):
    try:
        recut.source_file(req.source)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    job_id = _new_job("analyse")
    RENDER_POOL.submit(_run_analyse, job_id, req)
    return {"job": job_id}


@app.post("/api/decoupe/clips")
def make_clips(req: ClipsRequest):
    if not req.clips:
        raise HTTPException(400, "Choisis au moins un clip.")
    try:
        recut.source_file(req.source)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    job_id = _new_job("clips")
    RENDER_POOL.submit(_run_clips, job_id, req)
    return {"job": job_id}


@app.get("/api/lots/{lot}/zip")
def lot_zip(lot: str):
    try:
        path = recut.lot_zip(lot)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(path, filename=f"clips-{lot}.zip", media_type="application/zip")


app.mount("/output", StaticFiles(directory=config.OUTPUT_DIR), name="output")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")
