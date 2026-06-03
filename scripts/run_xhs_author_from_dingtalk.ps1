param(
  [Parameter(Mandatory=$true)]
  [string]$MessageFile,

  [string]$ApiBase = "http://127.0.0.1:8004"
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = $ProjectRoot + ";" + $env:PYTHONPATH
if (-not $env:XHS_DOWNLOADER_API_BASE_URL) { $env:XHS_DOWNLOADER_API_BASE_URL = "http://127.0.0.1:5556" }
if (-not $env:XHS_DOWNLOADER_PROJECT_DIR) { $env:XHS_DOWNLOADER_PROJECT_DIR = "D:\workspace\your-XHS-Downloader" }
if (-not $env:XHS_CREATOR_IMPORT_MODE) { $env:XHS_CREATOR_IMPORT_MODE = "auto" }
if (-not $env:XHS_CDP_URL) { $env:XHS_CDP_URL = "http://127.0.0.1:9222" }

if (!(Test-Path $MessageFile)) {
  Write-Host "错误：消息文件不存在：$MessageFile"
  exit 2
}

.\.venv\Scripts\python.exe .\scripts\openclaw_xhs_author.py `
  --message-file "$MessageFile" `
  --api-base "$ApiBase"
