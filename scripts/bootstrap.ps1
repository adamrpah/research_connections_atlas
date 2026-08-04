$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "uv is required. Install it from https://docs.astral.sh/uv/ and rerun."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  throw "Node.js >=22.13 is required."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "npm is required."
}

New-Item -ItemType Directory -Force -Path "data/Annual-Reports", "data/DigitalMeasure-Reports", ".secrets", "results" | Out-Null
uv sync
npm --prefix webapp ci
if (-not (Test-Path "webapp/public/data/manifest.json")) {
  New-Item -ItemType Directory -Force -Path "webapp/public/data" | Out-Null
  Copy-Item "webapp/public/data/demo/*.json" "webapp/public/data/"
}
uv run python scripts/doctor.py

Write-Host ""
Write-Host "Bootstrap complete. Run: python scripts/doctor.py --strict"
Write-Host "For topic modeling, also run: uv sync --extra topic"
