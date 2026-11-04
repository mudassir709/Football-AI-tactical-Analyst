# Build thesis.pdf from thesis.tex (Windows, MiKTeX).
#
#     powershell -ExecutionPolicy Bypass -File build.ps1
#
# LaTeX needs several passes: the first one collects references and the
# bibliography entries, biber builds the bibliography, and the last passes put
# the correct page numbers into the contents, lists and cross-references.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# MiKTeX's programs (installed per user by default).
$bin = "$env:LOCALAPPDATA\Programs\MiKTeX\miktex\bin\x64"
if (-not (Test-Path "$bin\pdflatex.exe")) { $bin = "C:\Program Files\MiKTeX\miktex\bin\x64" }

# Stop on the first LaTeX error, and show where it is.
function Run($program, $arguments) {
    & "$bin\$program.exe" @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$program failed; the end of thesis.log shows why:" -ForegroundColor Red
        Get-Content thesis.log -Tail 30
        exit 1
    }
}

$latex = @("-interaction=nonstopmode", "-halt-on-error", "thesis.tex")
Run "pdflatex" $latex
Run "biber" @("thesis")
Run "pdflatex" $latex
Run "pdflatex" $latex
Write-Host "Built thesis.pdf" -ForegroundColor Green
