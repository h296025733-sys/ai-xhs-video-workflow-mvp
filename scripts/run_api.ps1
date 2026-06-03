$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Python\Python312", "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts")) {
    if ((Test-Path $candidate) -and ($env:Path -notlike "*$candidate*")) {
        $env:Path = "$candidate;$env:Path"
    }
}

$ffmpegBins = @()
foreach ($root in @("$env:LOCALAPPDATA\Microsoft\WinGet\Packages", "$env:USERPROFILE\.real\.bin\ffmpeg", "$env:USERPROFILE\.real\.bin\ffmpeg\ffmpeg")) {
    if (Test-Path $root) {
        $ffmpegBins += Get-ChildItem -Path $root -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
            ForEach-Object { $_.DirectoryName }
    }
}
$ffmpegBins = $ffmpegBins | Select-Object -Unique
foreach ($candidate in $ffmpegBins) {
    if ((Test-Path $candidate) -and ($env:Path -notlike "*$candidate*")) {
        $env:Path = "$candidate;$env:Path"
    }
}

$env:PYTHONIOENCODING = "utf-8"
if (-not $env:XHS_DOWNLOADER_API_BASE_URL) { $env:XHS_DOWNLOADER_API_BASE_URL = "http://127.0.0.1:5556" }
if (-not $env:XHS_DOWNLOADER_PROJECT_DIR) { $env:XHS_DOWNLOADER_PROJECT_DIR = "D:\workspace\your-XHS-Downloader" }
if (-not $env:XHS_CREATOR_IMPORT_MODE) { $env:XHS_CREATOR_IMPORT_MODE = "auto" }

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    throw ".venv not found. Run scripts/install_deps.ps1 first."
}

& ".\.venv\Scripts\Activate.ps1"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8004
