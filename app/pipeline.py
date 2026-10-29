"""Chaîne complète : script → voix → visuels → sous-titres → vidéo finale."""
from __future__ import annotations

import json
import random
import shutil
import time
from pathlib import Path
from typing import Callable

from . import config, subtitles, tts, visuals
from .media import probe_duration, run_ffmpeg, x264

Progress = Callable[[str, float, str], None]
PAUSE = 0.14  # respiration entre deux plans (secondes)
MUSIC_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".aac"}


def list_music() -> list[str]:
    return sorted(p.name for p in config.MUSIC_DIR.iterdir()
                  if p.is_file() and p.suffix.lower() in MUSIC_EXT)


def _pick_music(choice: str) -> Path | None:
    tracks = list_music()
    if not choice or choice == "aucune" or not tracks:
        return None
    if choice == "auto":
        return config.MUSIC_DIR / random.choice(tracks)
    path = config.MUSIC_DIR / Path(choice).name
    return path if path.exists() else None


def _rate(speed: int) -> str:
    speed = max(-30, min(int(speed), 50))
    return f"{speed:+d}%"


def render(job_id: str, script: dict, options: dict, progress: Progress) -> dict:
    out_dir = config.OUTPUT_DIR / job_id
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    segments = script["segments"]
    n = len(segments)
    voice = options.get("voix") or config.VOICES[0]["id"]
    rate = _rate(options.get("vitesse", 8))
    started = time.time()

    # 1. Voix off, plan par plan ------------------------------------------------
    audio_parts, all_words, durations = [], [], []
    clock, engine = 0.0, "edge"
    silence = work / "pause.wav"
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(PAUSE),
                str(silence)], what="Silence")
    for i, seg in enumerate(segments):
        progress("voix", i / n, f"Voix off du plan {i + 1}/{n}")
        res = tts.synthesize(seg["texte"], voice, rate, work, f"voix{i:02d}")
        engine = res["engine"]
        for w in res["words"]:
            all_words.append({"text": w["text"], "start": clock + w["start"],
                              "end": clock + w["end"]})
        seg_len = res["duration"] + PAUSE
        durations.append(seg_len)
        audio_parts += [res["path"], silence]
        clock += seg_len
    total = clock

    voice_list = work / "voix.txt"
    voice_list.write_text("".join(f"file '{p.name}'\n" for p in audio_parts))
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", voice_list.name, "-c", "pcm_s16le",
                "voix.wav"], what="Assemblage de la voix", cwd=work)

    # 2. Visuels ----------------------------------------------------------------
    mode = options.get("fond", "auto")
    page_images = (script.get("source") or {}).get("images") or []
    if mode == "auto":
        if config.PEXELS_API_KEY:
            mode = "stock"
        elif page_images:
            mode = "images"
        else:
            mode = "degrade"

    downloaded: list[Path] = []
    if mode in ("images", "stock") and page_images:
        progress("visuels", 0, "Téléchargement des images du lien")
        for k, url in enumerate(page_images[:6]):
            img = visuals.download_image(url, work, f"page{k:02d}")
            if img:
                downloaded.append(img)

    seed = random.randint(0, 999)
    used_pexels: set[int] = set()
    clips, sources_used = [], []
    for i, (seg, dur) in enumerate(zip(segments, durations)):
        progress("visuels", i / n, f"Visuel du plan {i + 1}/{n}")
        clip = work / f"plan{i:02d}.mp4"
        made = False
        if mode == "stock":
            query = seg.get("visuel") or script.get("titre", "")
            vid = visuals.pexels_video(query, work, f"plan{i:02d}", used_pexels)
            if vid:
                visuals.video_to_clip(vid, dur, clip)
                sources_used.append("pexels")
                made = True
        if not made and downloaded:
            png = visuals.image_frame(downloaded[i % len(downloaded)], work / f"plan{i:02d}.png")
            visuals.still_to_clip(png, dur, clip, zoom_in=i % 2 == 0)
            sources_used.append("image")
            made = True
        if not made:
            png = visuals.gradient_frame(i, work / f"plan{i:02d}.png", seed=seed)
            visuals.still_to_clip(png, dur, clip, zoom_in=i % 2 == 0)
            sources_used.append("degrade")
        clips.append(clip)

    clip_list = work / "plans.txt"
    clip_list.write_text("".join(f"file '{c.name}'\n" for c in clips))
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", clip_list.name, "-c", "copy", "plans.mp4"],
               what="Assemblage des plans", cwd=work)

    # 3. Sous-titres --------------------------------------------------------------
    progress("sous-titres", 0, "Sous-titres mot à mot")
    subtitles.build_ass(
        all_words if options.get("sous_titres", True) else [], total, work / "sous-titres.ass",
        title=script.get("titre", "") if options.get("bandeau", True) else "",
        highlight=options.get("couleur", "#FFD23F"),
        upper=options.get("majuscules", True),
    )

    # 4. Montage final ------------------------------------------------------------
    progress("montage", 0, "Montage final")
    music = _pick_music(options.get("musique", "auto"))
    fonts = str(config.FONTS_DIR).replace("\\", "/").replace(":", "\\:")
    inputs = ["-i", "plans.mp4", "-i", "voix.wav"]
    vfilter = f"[0:v]ass=sous-titres.ass:fontsdir='{fonts}'[v]"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        fade_start = max(total - 1.5, 0)
        afilter = (
            f"[2:a]volume={float(options.get('volume_musique', 0.12)):.2f},"
            f"afade=t=out:st={fade_start:.2f}:d=1.5[m];"
            "[1:a][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2,"
            "loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        )
    else:
        afilter = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    final = out_dir / "video.mp4"
    run_ffmpeg([*inputs, "-filter_complex", f"{vfilter};{afilter}",
                "-map", "[v]", "-map", "[a]", *x264(21), "-c:a", "aac", "-b:a", "160k",
                "-ar", "44100", "-t", f"{total:.3f}", "-movflags", "+faststart",
                str(final)], what="Montage final", cwd=work)

    run_ffmpeg(["-ss", "0.8", "-i", str(final), "-frames:v", "1", "-vf", "scale=360:-2",
                str(out_dir / "miniature.jpg")], what="Miniature")

    meta = {
        "id": job_id,
        "cree_le": time.strftime("%Y-%m-%d %H:%M"),
        "titre": script.get("titre", ""),
        "legende": script.get("legende", ""),
        "hashtags": script.get("hashtags", []),
        "duree": round(probe_duration(final), 1),
        "voix": voice,
        "moteur_voix": engine,
        "fonds": sources_used,
        "musique": music.name if music else None,
        "script": script,
        "temps_de_calcul": round(time.time() - started, 1),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    if not options.get("garder_fichiers"):
        shutil.rmtree(work, ignore_errors=True)
    progress("termine", 1, "Vidéo prête")
    return meta
