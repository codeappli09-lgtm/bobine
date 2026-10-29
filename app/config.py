"""Réglages de Bobine, lus depuis le fichier .env (voir .env.example)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- IA (écriture du script) -------------------------------------------------
# "ollama" : Qwen en local dans le Codespace (gratuit, rien à configurer)
# "openai" : n'importe quelle API compatible OpenAI (OpenRouter, Groq, DashScope…)
LLM_PROVIDER = env("LLM_PROVIDER", "ollama").lower()
OLLAMA_URL = env("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
LLM_BASE_URL = env("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
LLM_API_KEY = env("LLM_API_KEY")
LLM_MODEL = env("LLM_MODEL", "qwen3.5:4b")
LLM_TIMEOUT = int(env("LLM_TIMEOUT", "600"))

# --- Visuels -----------------------------------------------------------------
PEXELS_API_KEY = env("PEXELS_API_KEY")

# --- Vidéo -------------------------------------------------------------------
WIDTH, HEIGHT, FPS = 1080, 1920, 30
FFMPEG = env("FFMPEG", "ffmpeg")
FFPROBE = env("FFPROBE", "ffprobe")
# veryfast = bon compromis sur la petite machine gratuite de Codespaces
X264_PRESET = env("X264_PRESET", "veryfast")

# --- Redécoupage de vidéos existantes ----------------------------------------
# tiny < base < small < medium : plus c'est gros, plus c'est juste… et lent
WHISPER_MODEL = env("WHISPER_MODEL", "small")
WHISPER_LANG = env("WHISPER_LANG", "fr")
MAX_UPLOAD_GB = float(env("MAX_UPLOAD_GB", "4"))

# --- Dossiers ----------------------------------------------------------------
OUTPUT_DIR = ROOT / "output"
SOURCES_DIR = ROOT / "sources"
INBOX_DIR = ROOT / "a-decouper"  # grosses vidéos glissées directement dans le Codespace
MUSIC_DIR = ROOT / "music"
FONTS_DIR = ROOT / "fonts"
STATIC_DIR = ROOT / "static"
for d in (OUTPUT_DIR, MUSIC_DIR, SOURCES_DIR, INBOX_DIR):
    d.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

VOICES = [
    {"id": "fr-FR-DeniseNeural", "label": "Denise", "genre": "femme"},
    {"id": "fr-FR-HenriNeural", "label": "Henri", "genre": "homme"},
    {"id": "fr-FR-VivienneMultilingualNeural", "label": "Vivienne", "genre": "femme"},
    {"id": "fr-FR-RemyMultilingualNeural", "label": "Rémy", "genre": "homme"},
    {"id": "fr-CA-SylvieNeural", "label": "Sylvie (Québec)", "genre": "femme"},
    {"id": "fr-CA-AntoineNeural", "label": "Antoine (Québec)", "genre": "homme"},
]
