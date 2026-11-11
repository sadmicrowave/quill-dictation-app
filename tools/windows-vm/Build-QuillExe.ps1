<#
.SYNOPSIS
  Build Quill.exe the way the release does (PyInstaller), from the code the Mac just synced; self-check it; put it in the share.

.DESCRIPTION
  Mac:   tools/windows-vm/sync-to-share.sh
  VM:    Build Quill exe.bat      (or this script;  -Start  starts the program when it is done)
  Result: <share>\out\Quill.exe and <share>\out\selfcheck-built.txt  (the Mac sees them in ~/Developer/QuillShare/out)
  A Windows program cannot be built on the Mac, which is why the build runs here.
#>
param([switch]$Start)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "QuillVm.ps1")

Copy-QuillSource
Initialize-QuillPython
Set-Location $Src
$env:PYTHONDONTWRITEBYTECODE = "1"

& $VenvPython tools\make_app_icon.py
& $VenvPython -m PyInstaller --noconfirm packaging\quill_win.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$exe = Join-Path $Src "dist\Quill.exe"
if (-not (Test-Path $exe)) { throw "dist\Quill.exe was not built" }

$out = Get-QuillOut
Copy-Item $exe (Join-Path $out "Quill.exe") -Force
Write-Host ("Built Quill.exe: {0} MB" -f [int]((Get-Item $exe).Length / 1MB))

$report = Join-Path $out "selfcheck-built.txt"
$run = Start-Process -FilePath $exe -ArgumentList "--selftest", "--out", $report -Wait -PassThru
if (Test-Path $report) { Get-Content $report }
Write-Host "Self-check exit code: $($run.ExitCode)  (0 = all fine, 1 = a check failed)"
Write-Host "In the share: $out"

if ($Start) { Start-Process -FilePath $exe }
