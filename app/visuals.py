"""Fonds vidéo de chaque plan : vidéos Pexels, images du lien, ou dégradés animés."""
from __future__ import annotations

import io
import math
import random
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import config
from .media import run_ffmpeg, x264

W, H = config.WIDTH, config.HEIGHT
SS = 2        # images fixes dessinées en 2x : le zoom reste fluide, sans tremblement
ZOOM = 0.12   # zoom lent de 12 % sur la durée du plan

PALETTES = [
    ((20, 24, 82), (229, 54, 122)),
    ((8, 56, 74), (255, 196, 61)),
    ((52, 16, 92), (61, 214, 208)),
    ((96, 20, 30), (255, 140, 66)),
    ((14, 40, 30), (180, 236, 81)),
    ((30, 30, 46), (120, 140, 255)),
]


# --- Pexels ------------------------------------------------------------------
def pexels_video(query: str, workdir: Path, name: str, used: set[int],
                 min_duration: float = 3) -> Path | None:
    if not config.PEXELS_API_KEY or not query.strip():
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "orientation": "portrait", "size": "medium",
                    "per_page": 15},
            headers={"Authorization": config.PEXELS_API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
    except Exception:
        return None

    for video in videos:
        if video.get("id") in used or video.get("duration", 0) < min_duration:
            continue
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 1000
                 and (f.get("height") or 0) <= 2600]
        if not files:
            continue
        best = min(files, key=lambda f: abs((f.get("width") or 0) - 1080))
        dest = workdir / f"{name}.pexels.mp4"
        try:
            with requests.get(best["link"], stream=True, timeout=60) as resp:
                resp.raise_for_status()
                size = 0
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(1 << 16):
                        size += len(chunk)
                        if size > 80 * 1024 * 1024:
                            raise ValueError("vidéo trop lourde")
                        fh.write(chunk)
        except Exception:
            dest.unlink(missing_ok=True)
            continue
        used.add(video["id"])
        return dest
    return None


# --- Images ------------------------------------------------------------------
def download_image(url: str, workdir: Path, name: str) -> Path | None:
    try:
        r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=15)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return None
    if img.width < 320 or img.height < 200:
        return None
    dest = workdir / f"{name}.jpg"
    img.save(dest, quality=92)
    return dest


def _cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(img, size, Image.LANCZOS, centering=(0.5, 0.5))


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *img.size), radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def image_frame(src: Path, out_png: Path) -> Path:
    """Image du lien posée sur un fond flouté de la même image (format vertical)."""
    cw, ch = W * SS, H * SS
    img = Image.open(src).convert("RGB")
    ratio = img.width / img.height

    if ratio < 0.75:  # déjà verticale : plein écran
        canvas = _cover(img, (cw, ch))
        canvas.save(out_png)
        return out_png

    bg = _cover(img, (cw // 4, ch // 4)).filter(ImageFilter.GaussianBlur(12))
    bg = bg.resize((cw, ch), Image.LANCZOS)
    bg = Image.blend(bg, Image.new("RGB", bg.size, (10, 10, 20)), 0.45)

    card_w = int(cw * 0.86)
    card_h = min(int(card_w / ratio), int(ch * 0.42))
    card = _cover(img, (card_w, card_h))
    card = _rounded(card, 36 * SS)

    pad = 60 * SS
    shadow = Image.new("RGBA", (card_w + 2 * pad, card_h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 10 * SS, pad + card_w, pad + card_h),
                                             radius=40 * SS, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28 * SS))

    x = (cw - card_w) // 2
    y = int(ch * 0.40) - card_h // 2
    canvas = bg.convert("RGBA")
    canvas.alpha_composite(shadow, (x - pad, y - pad))
    canvas.alpha_composite(card, (x, y))
    canvas.convert("RGB").save(out_png)
    return out_png


def gradient_frame(index: int, out_png: Path, seed: int = 0) -> Path:
    """Dégradé avec halos de lumière, une couleur différente par plan."""
    cw, ch = W * SS, H * SS
    rng = random.Random(seed * 101 + index)
    dark, light = PALETTES[(seed + index) % len(PALETTES)]
    small = (cw // 6, ch // 6)
    base = Image.new("RGB", small, dark)
    px = base.load()
    for yy in range(small[1]):
        t = yy / small[1]
        for xx in range(small[0]):
            k = 0.25 * t + 0.1 * math.sin(xx / small[0] * math.pi)
            px[xx, yy] = tuple(int(d + (l - d) * k) for d, l in zip(dark, light))
    glow = Image.new("RGBA", small, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for _ in range(4):
        r = rng.randint(small[0] // 4, small[0] // 2)
        cx, cy = rng.randint(0, small[0]), rng.randint(0, small[1])
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*light, rng.randint(60, 120)))
    glow = glow.filter(ImageFilter.GaussianBlur(small[0] // 7))
    img = base.convert("RGBA")
    img.alpha_composite(glow)
    img = img.convert("RGB").resize((cw, ch), Image.BICUBIC)
    noise = Image.effect_noise((cw, ch), 18).convert("RGB")
    img = Image.blend(img, noise, 0.04)
    img.save(out_png)
    return out_png


# --- Clips -------------------------------------------------------------------
def still_to_clip(png: Path, duration: float, out: Path, zoom_in: bool = True) -> Path:
    """Image fixe → clip avec un zoom lent et centré (effet Ken Burns)."""
    d = max(duration, 0.5)
    frames = max(int(round(d * config.FPS)), 1)
    if zoom_in:
        z = f"1+{ZOOM}*on/{frames}"
    else:
        z = f"{1 + ZOOM}-{ZOOM}*on/{frames}"
    vf = (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}"
          f":s={W}x{H}:fps={config.FPS},setsar=1,format=yuv420p")
    run_ffmpeg(["-i", str(png), "-vf", vf, "-frames:v", str(frames), *x264(20), "-an",
                str(out)], what=f"Animation de {png.name}")
    return out


def video_to_clip(src: Path, duration: float, out: Path) -> Path:
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
          f"fps={config.FPS},eq=brightness=-0.03:saturation=1.08,format=yuv420p")
    run_ffmpeg(["-stream_loop", "-1", "-i", str(src), "-t", f"{max(duration, 0.5):.3f}",
                "-vf", vf, *x264(20), "-an", str(out)], what="Découpe de la vidéo Pexels")
    return out
