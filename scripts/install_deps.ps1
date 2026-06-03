$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Python\Python312", "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts")) {
    if ((Test-Path $candidate) -and ($env:Path -notlike "*$candidate*")) {
        $env:Path = "$candidate;$env:Path"
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is not available. Run scripts/check_env.ps1 -InstallMissing first."
}

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host ""
Write-Host "Dependencies installed."
Write-Host "Next: .\scripts\run_api.ps1"
