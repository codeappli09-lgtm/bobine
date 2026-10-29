#!/usr/bin/env bash
# Installation unique, lancée par Codespaces à la création de l'espace.
set -e
cd "$(dirname "$0")/.."

echo "▶ Outils vidéo et voix de secours (ffmpeg, espeak-ng)"
sudo apt-get update -q
sudo apt-get install -y -q ffmpeg espeak-ng

echo "▶ Bibliothèques Python"
pip install --no-cache-dir -r requirements.txt

[ -f .env ] || cp .env.example .env
mkdir -p output music logs sources a-decouper

# shellcheck disable=SC1091
set -a; . ./.env; set +a
echo "▶ Modèle de transcription ${WHISPER_MODEL:-small} (pour redécouper tes vidéos)"
python3 -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL:-small}', device='cpu', compute_type='int8')" \
  || echo "⚠ Pas téléchargé maintenant : il le sera au premier redécoupage."

if [ "${LLM_PROVIDER:-ollama}" = "ollama" ]; then
  echo "▶ Ollama (pour faire tourner Qwen dans le Codespace)"
  if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  nohup ollama serve > logs/ollama.log 2>&1 &
  for _ in $(seq 1 30); do curl -s http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
  echo "▶ Téléchargement du modèle ${LLM_MODEL:-qwen3.5:4b} (quelques minutes)"
  ollama pull "${LLM_MODEL:-qwen3.5:4b}" || echo "⚠ Téléchargement raté : relance « ollama pull ${LLM_MODEL:-qwen3.5:4b} »"
fi

echo "✔ Installation terminée. Bobine démarre toute seule (port 8000)."
