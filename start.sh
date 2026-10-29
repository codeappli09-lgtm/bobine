#!/usr/bin/env bash
# Démarre Bobine.   ./start.sh        → au premier plan (Ctrl+C pour arrêter)
#                   ./start.sh --fond → en arrière-plan (utilisé par Codespaces)
cd "$(dirname "$0")"
mkdir -p logs output music
[ -f .env ] || cp .env.example .env
# shellcheck disable=SC1091
set -a; . ./.env; set +a

MODEL="${LLM_MODEL:-qwen3.5:4b}"
if [ "${LLM_PROVIDER:-ollama}" = "ollama" ] && command -v ollama >/dev/null 2>&1; then
  if ! curl -s http://127.0.0.1:11434/api/tags >/dev/null; then
    echo "▶ Démarrage d'Ollama"
    nohup ollama serve > logs/ollama.log 2>&1 &
    for _ in $(seq 1 30); do curl -s http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
  fi
  if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
    echo "▶ Modèle $MODEL absent : téléchargement"
    ollama pull "$MODEL" || echo "⚠ Impossible de télécharger $MODEL (Bobine marchera en mode simple)"
  fi
fi

# Arrête une ancienne instance de Bobine si elle tourne encore
pkill -f "[u]vicorn app.main:app" 2>/dev/null && sleep 1

if [ "$1" = "--fond" ]; then
  nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > logs/bobine.log 2>&1 &
  echo "✔ Bobine tourne en arrière-plan sur le port 8000 (journal : logs/bobine.log)"
else
  echo "✔ Bobine démarre sur le port 8000 — ouvre l'onglet PORTS de Codespaces"
  exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
