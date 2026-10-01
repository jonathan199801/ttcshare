@echo off
if not exist .env (
  echo Falta .env. Copia .env.example a .env y completa tus credenciales.
  exit /b 1
)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
