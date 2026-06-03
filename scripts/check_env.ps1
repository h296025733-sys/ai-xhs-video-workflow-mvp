param(
    [switch]$InstallMissing
)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Add-FirstExistingPath($Candidates) {
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path $candidate) -and ($env:Path -notlike "*$candidate*")) {
            $env:Path = "$candidate;$env:Path"
        }
    }
}

Add-FirstExistingPath @(
    "$env:LOCALAPPDATA\Programs\Python\Python312",
    "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"
)

$ffmpegBins = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
    ForEach-Object { $_.DirectoryName } |
    Select-Object -Unique
Add-FirstExistingPath $ffmpegBins

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Check($Name, $Ok, $Detail = "") {
    $mark = if ($Ok) { "OK" } else { "MISSING" }
    Write-Host ("{0,-18} {1} {2}" -f $Name, $mark, $Detail)
}

Write-Host "Project root: $ProjectRoot"
Write-Check "Project path" (Test-Path (Join-Path $ProjectRoot "app\main.py")) "expected project root containing app\main.py"

$pythonOk = Test-Command "python"
if ($pythonOk) {
    $pythonVersion = (& python --version 2>&1)
    $pythonOk = ($LASTEXITCODE -eq 0)
}
Write-Check "Python" $pythonOk ($pythonVersion -join " ")

$pipOk = $false
if ($pythonOk) {
    & python -m pip --version *> $null
    $pipOk = ($LASTEXITCODE -eq 0)
}
Write-Check "pip" $pipOk

$ffmpegOk = Test-Command "ffmpeg"
Write-Check "ffmpeg" $ffmpegOk

$ffprobeOk = Test-Command "ffprobe"
Write-Check "ffprobe" $ffprobeOk

$sceneOk = $false
$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$scenePython = if (Test-Path $venvPython) { $venvPython } else { "python" }
if ($pythonOk -or (Test-Path $venvPython)) {
    & $scenePython -c "import scenedetect; print('scenedetect ok')" *> $null
    $sceneOk = ($LASTEXITCODE -eq 0)
}
Write-Check "scenedetect" $sceneOk "checked with $scenePython"

if ($InstallMissing -and (-not $pythonOk -or -not $ffmpegOk -or -not $ffprobeOk)) {
    if (-not (Test-Command "winget")) {
        Write-Host "winget is not available. Install Python 3.11+ and FFmpeg manually, then rerun this script."
        exit 1
    }
    if (-not $pythonOk) {
        Write-Host "Trying to install Python via winget..."
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    }
    if (-not $ffmpegOk -or -not $ffprobeOk) {
        Write-Host "Trying to install FFmpeg via winget..."
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    }
    Write-Host "Install attempt finished. Open a new PowerShell window if PATH was updated, then rerun scripts/check_env.ps1."
}

if (-not $pythonOk -or -not $ffmpegOk -or -not $ffprobeOk) {
    Write-Host "Missing required local tools. Required: Python, ffmpeg, ffprobe. No paid software or API key is needed."
    exit 1
}

exit 0
