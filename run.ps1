$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Локальное окружение не найдено. Сначала выполните: python -m venv .venv"
    exit 1
}

& $python (Join-Path $PSScriptRoot "app.py")
