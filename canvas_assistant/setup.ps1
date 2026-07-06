# One-time setup for the Canvas Homework Assistant (Windows PowerShell).
# Run from inside the canvas_assistant folder:  .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

Write-Host "Installing dependencies (first run takes a few minutes)..."
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python -m playwright install chromium

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    $url = Read-Host "Your Canvas URL (press Enter for https://umd.instructure.com)"
    if ([string]::IsNullOrWhiteSpace($url)) { $url = "https://umd.instructure.com" }
    (Get-Content .env) -replace '^CANVAS_BASE_URL=.*', "CANVAS_BASE_URL=$url" | Set-Content .env
    Write-Host ".env created with CANVAS_BASE_URL=$url"
    Write-Host "(add ANTHROPIC_API_KEY to .env later to enable draft generation)"
}

Write-Host ""
Write-Host "Setup complete. Now run:" -ForegroundColor Green
Write-Host "  python main.py login          # Chrome opens -> log in -> press Enter here"
Write-Host "  python main.py session-debug  # quick check that it sees your courses"
Write-Host "  python main.py all --dry-run  # the whole detection run, downloads nothing"
