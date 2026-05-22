param(
  [string]$WorkspaceRoot = "D:\AI\omniauto"
)

$ErrorActionPreference = "Stop"

$seedRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$zipPath = Join-Path $seedRoot "test02_recorder_only_20260522_145033.zip"

if (!(Test-Path $zipPath)) {
  throw "Seed package not found: $zipPath"
}

$tempRoot = Join-Path $env:TEMP ("test02_recorder_seed_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
  Expand-Archive -LiteralPath $zipPath -DestinationPath $tempRoot -Force
  $importScript = Join-Path $tempRoot "import_test02_recorder_payload.ps1"
  if (!(Test-Path $importScript)) {
    throw "Import script not found in package: $importScript"
  }
  & $importScript -WorkspaceRoot $WorkspaceRoot
}
finally {
  if (Test-Path $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
  }
}
