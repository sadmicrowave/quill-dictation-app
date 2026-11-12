<#
.SYNOPSIS
  Fetch the newest Quill dev build from GitHub, run its self-check, and (optionally) start it. Run inside the Windows test VM.

.DESCRIPTION
  One-time setup in the VM (see docs/windows-vm.md):
      winget install --id GitHub.cli
      gh auth login          # GitHub.com, HTTPS, "Login with a web browser"

  Then, every test:
      .\Get-QuillDevBuild.ps1                      # newest successful dev build of develop
      .\Get-QuillDevBuild.ps1 -Branch fix/foo      # a branch (started with: gh workflow run "dev build" --ref fix/foo)
      .\Get-QuillDevBuild.ps1 -Start               # ... and start Quill when the self-check is done
      .\Get-QuillDevBuild.ps1 -Send                # ... and send the self-check report to the support repo as an issue

  The build lands in  $HOME\QuillTest\<run number>\  (Quill.exe, the self-check report).
#>
param(
    [string]$Branch = "develop",
    [string]$Repo = "sadmicrowave/quill-dictation-app",
    [switch]$Start,
    [switch]$Send
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub's command line tool is not installed: run  winget install --id GitHub.cli  and then  gh auth login"
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { throw "Not signed in to GitHub: run  gh auth login" }

# The newest dev build of that branch that finished green.
$runId = gh run list --repo $Repo --workflow dev-build.yml --branch $Branch --status success --limit 1 --json databaseId --jq ".[0].databaseId"
if (-not $runId) { throw "No successful dev build of '$Branch' yet. Start one:  gh workflow run 'dev build' --ref $Branch --repo $Repo" }
$commit = gh run view $runId --repo $Repo --json headSha --jq ".headSha"
Write-Host "Dev build of '$Branch': run $runId, commit $($commit.Substring(0, 7))"

$folder = Join-Path $HOME "QuillTest\$runId"
if (Test-Path $folder) { Remove-Item $folder -Recurse -Force }
New-Item -ItemType Directory -Path $folder | Out-Null
gh run download $runId --repo $Repo --name Quill-windows-dev --dir $folder
if ($LASTEXITCODE -ne 0) { throw "Could not download the build (the artifact is kept 14 days)" }

$zip = Join-Path $folder "Quill-windows-dev.zip"
Expand-Archive -Path $zip -DestinationPath $folder -Force
$exe = Join-Path $folder "Quill.exe"
if (-not (Test-Path $exe)) { throw "Quill.exe is not in the download" }

# The packaged program checks itself (a window-free run that writes a report).
$report = Join-Path $folder "this-machine-selfcheck.txt"
$run = Start-Process -FilePath $exe -ArgumentList "--selftest", "--out", $report -Wait -PassThru
if (Test-Path $report) { Get-Content $report } else { Write-Host "No report was written" }
Write-Host "Self-check exit code: $($run.ExitCode)  (0 = all fine, 1 = a check failed)"

if ($Send) {
    Start-Process -FilePath $exe -ArgumentList "--selftest", "--send" -Wait
    Write-Host "Report sent: it is an issue in the support repo."
}
if ($Start) {
    Start-Process -FilePath $exe
    Write-Host "Quill started."
}
Write-Host "Build folder: $folder"
