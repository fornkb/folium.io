$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $foliumPython = $localPython }
elseif (Test-Path -LiteralPath $bundledPython) { $foliumPython = $bundledPython }
else { $foliumPython = 'python' }
& $foliumPython -c 'import pypdf, pypdfium2, PIL'
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Install the PDF dependencies first: python -m pip install -r requirements.txt'
    exit 1
}
& $foliumPython app.py @args
