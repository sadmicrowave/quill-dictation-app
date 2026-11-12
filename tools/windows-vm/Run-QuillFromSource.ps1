<#
.SYNOPSIS
  Run the Quill code the Mac just synced, as plain Python (no build). The fastest loop: edit on the Mac, sync, run here.

.DESCRIPTION
  Mac:   tools/windows-vm/sync-to-share.sh
  VM:    Run Quill from source.bat      (or this script)
  -SelfTest   run the self-check instead of the window; the report goes to the share's out folder
#>
param([switch]$SelfTest)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "QuillVm.ps1")

Copy-QuillSource
Initialize-QuillPython
Set-Location $Src
$env:PYTHONDONTWRITEBYTECODE = "1"
if ($SelfTest) {
    $report = Join-Path (Get-QuillOut) "selfcheck-source.txt"
    & $VenvPython main.py --selftest --out $report
    if (Test-Path $report) { Get-Content $report }
    Write-Host "Report: $report"
} else {
    & $VenvPython main.py
}
