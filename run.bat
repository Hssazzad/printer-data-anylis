@echo off
echo Starting FastAPI Printer Analytics Dashboard...
.\venv\Scripts\uvicorn.exe main:app --reload --host 127.0.0.1 --port 8000
pause
