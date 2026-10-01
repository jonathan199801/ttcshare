#!/usr/bin/env bash
set -e
if [ ! -f .env ]; then
  echo "Falta .env. Copia .env.example a .env y completa tus credenciales."
  exit 1
fi
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
