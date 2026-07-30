# ApplyPilot - Quick Install (Windows PowerShell)
# Downloads and installs ApplyPilot for local use.
#
# Usage: .\install.ps1
# Or:    powershell -ExecutionPolicy Bypass -File install.ps1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  ApplyPilot - Instalador Windows" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$ErrorActionPreference = "Stop"

# ---- Check Python ----
Write-Host "[1/4] Verificando Python 3.11+..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "  OK: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERRO: Python nao encontrado." -ForegroundColor Red
    Write-Host "  Instale Python 3.11+ de https://python.org" -ForegroundColor Red
    exit 1
}

# ---- Install ApplyPilot ----
Write-Host "[2/4] Instalando ApplyPilot..." -ForegroundColor Yellow
pip install applypilot
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERRO ao instalar. Se voce clonou o repositorio, use:" -ForegroundColor Yellow
    Write-Host "  pip install -e ." -ForegroundColor White
    pip install -e .
}

# ---- Install python-jobspy (separate due to numpy pin) ----
Write-Host "[3/4] Instalando python-jobspy..." -ForegroundColor Yellow
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex

# ---- Run setup (launches web browser) ----
Write-Host "[4/4] Iniciando interface de configuracao..." -ForegroundColor Yellow
Write-Host ""
Write-Host "Uma janela do navegador vai abrir para configurar:" -ForegroundColor Cyan
Write-Host "  1. Seu curriculo (upload ou texto)" -ForegroundColor White
Write-Host "  2. Perfil profissional" -ForegroundColor White
Write-Host "  3. Cargos, locais e sites de busca" -ForegroundColor White
Write-Host "  4. Preferencias de pontuacao (categoria, senioridade, skills)" -ForegroundColor White
Write-Host "  5. Chave de API LLM (opcional, Gemini e gratuito)" -ForegroundColor White
Write-Host ""

applypilot-gui

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Instalacao concluida!" -ForegroundColor Green
Write-Host ""
Write-Host "  Para buscar vagas:       applypilot run" -ForegroundColor White
Write-Host "  Para ver status:          applypilot status" -ForegroundColor White
Write-Host "  Para dashboard web:       applypilot dashboard" -ForegroundColor White
Write-Host "  Para ajuda:               applypilot --help" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
