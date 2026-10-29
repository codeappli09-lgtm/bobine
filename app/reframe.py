"""Passage du 16:9 au 9:16 : recadrage sur le visage, ou écran entier sur fond flou."""
from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path

from . import config

W, H = config.WIDTH, config.HEIGHT
MODES = ("auto", "visage", "ecran", "centre")


def probe(path: Path) -> dict:
    proc = subprocess.run(
        [config.FFPROBE, "-v", "error", "-show_entries",
         "stream=codec_type,width,height:stream_tags=rotate:stream_side_data=rotation"
         ":format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ValueError("Ce fichier n'est pas une vidéo lisible.")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    if not video:
        raise ValueError("Ce fichier ne contient pas d'image vidéo.")
    w, h = int(video.get("width") or 0), int(video.get("height") or 0)
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(float(sd["rotation"]))
    rotation = rotation or int((video.get("tags") or {}).get("rotate", 0) or 0)
    if abs(rotation) in (90, 270):
        w, h = h, w  # vidéo de téléphone tournée
    return {"width": w, "height": h, "duration": float(data["format"].get("duration") or 0),
            "audio": audio}


def detect_face_x(video: Path, start: float, end: float, samples: int = 7) -> float | None:
    """Position horizontale (0 à 1) du visage principal, ou None si pas de face caméra."""
    try:
        import cv2
    except ImportError:
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():  # OpenCV 5 ne fournit plus ce fichier : garder opencv < 5
        return None
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return None
    xs, seen = [], 0
    dur = max(end - start, 0.1)
    for k in range(samples):
        t = start + dur * (k + 0.5) / samples
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        seen += 1
        fh, fw = frame.shape[:2]
        scale = 640 / fw
        small = cv2.resize(frame, (640, int(fh * scale)))
        gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                         minSize=(int(640 * 0.08), int(640 * 0.08)))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + w / 2) / 640)
    cap.release()
    if seen and len(xs) >= max(2, seen // 2):
        return statistics.median(xs)
    return None


def choose_mode(video: Path, info: dict, start: float, end: float) -> tuple[str, float]:
    """Mode « auto » : visage si une personne est filmée de près, sinon écran entier."""
    if info["width"] / max(info["height"], 1) < 0.8:
        return "centre", 0.5  # déjà vertical
    x = detect_face_x(video, start, end)
    if x is None:
        return "ecran", 0.5
    return "visage", x


def video_filter(info: dict, mode: str, face_x: float = 0.5) -> str:
    """Chaîne de filtres ffmpeg qui sort une image 1080×1920 nommée [v0]."""
    w, h = info["width"], info["height"]
    if mode in ("visage", "centre") or w / max(h, 1) < 0.8:
        crop_w = min(w, int(h * 9 / 16) // 2 * 2)
        crop_h = min(h, int(crop_w * 16 / 9) // 2 * 2)
        x = int(min(max(face_x * w - crop_w / 2, 0), w - crop_w))
        y = int((h - crop_h) / 2)
        return (f"[0:v]crop={crop_w}:{crop_h}:{x}:{y},scale={W}:{H}:flags=lanczos,"
                f"setsar=1[v0]")
    # Écran entier : l'image complète au milieu, la même floutée derrière
    fg_y = int(H * 0.42)
    return (f"[0:v]split=2[bgs][fgs];"
            f"[bgs]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,"
            f"crop={W // 4}:{H // 4},boxblur=12:2,eq=brightness=-0.12,scale={W}:{H}[bg];"
            f"[fgs]scale={W}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:{fg_y}-h/2,setsar=1[v0]")
