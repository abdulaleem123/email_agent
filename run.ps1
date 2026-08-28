# InboxPilot — one-command local start (Windows)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Redis = Join-Path $Root "redis-portable\redis-server.exe"

Write-Host "Starting InboxPilot Email Agent..." -ForegroundColor Cyan

# Redis
if (Test-Path $Redis) {
    Start-Process -FilePath $Redis -WindowStyle Minimized
    Start-Sleep -Seconds 1
}

# Backend API
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Backend'; .\venv\Scripts\uvicorn app.main:app --port 8000" -WindowStyle Normal

# Celery worker + beat
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Backend'; .\venv\Scripts\celery -A app.celery_app.celery worker --loglevel=info --pool=solo" -WindowStyle Normal
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Backend'; .\venv\Scripts\celery -A app.celery_app.celery beat --loglevel=info" -WindowStyle Normal

# Frontend (auto-connects — no API key paste needed)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Frontend'; npm run dev" -WindowStyle Normal

Start-Sleep -Seconds 4
Write-Host ""
Write-Host "Open http://192.168.0.104:5173 — connects automatically." -ForegroundColor Green
Write-Host "Upload sample_clients.xlsx from the project root to test leads." -ForegroundColor Green
