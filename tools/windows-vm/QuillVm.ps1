# Shared by the other scripts in this folder (dot-sourced). Runs inside the Windows VM.

$script:Share = if ($env:QUILL_SHARE) { $env:QUILL_SHARE } else { "\\vmware-host\Shared Folders\QuillShare" }
$script:Work = "C:\QuillTest"                 # a local copy: running from the share is slow, and the share is not where Python's files belong
$script:Src = Join-Path $Work "src"
$script:Venv = Join-Path $Work "venv"
$script:VenvPython = Join-Path $Venv "Scripts\python.exe"

function Copy-QuillSource {
    if (-not (Test-Path (Join-Path $Share "src\main.py"))) {
        throw "No Quill code at '$Share\src'. On the Mac run  tools/windows-vm/sync-to-share.sh  and check the VM's shared folder (Settings > Sharing)."
    }
    New-Item -ItemType Directory -Path $Work -Force | Out-Null
    robocopy (Join-Path $Share "src") $Src /MIR /XD __pycache__ build dist /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying the code from the share failed (robocopy exit code $LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
    $stamp = Join-Path $Src "quill\_build.py"
    if (Test-Path $stamp) { Write-Host (Get-Content $stamp) }
}

function Find-QuillPython {
    # Python 3.13: through the launcher, on the path, or in the places the installer puts it.
    $candidates = @()
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $candidates += @{ Path = $launcher.Source; Args = @("-3.13") } }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += @{ Path = $onPath.Source; Args = @() } }
    foreach ($folder in @("$env:LOCALAPPDATA\Programs\Python\Python313", "$env:ProgramFiles\Python313", "${env:ProgramFiles(x86)}\Python313")) {
        $exe = Join-Path $folder "python.exe"
        if (Test-Path $exe) { $candidates += @{ Path = $exe; Args = @() } }
    }
    foreach ($candidate in $candidates) {
        $version = & $candidate.Path @($candidate.Args) --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$version" -match "^Python 3\.13\.") { return $candidate }
    }
    return $null
}

function Initialize-QuillPython {
    if (-not (Test-Path $VenvPython)) {
        $python = Find-QuillPython
        if (-not $python) {
            throw "Python 3.13 was not found. Run:  winget install -e --id Python.Python.3.13 --source winget   then open a new PowerShell."
        }
        Write-Host "Making the Python environment (first time only), with $($python.Path) ..."
        & $python.Path @($python.Args) -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw "Could not make the Python environment" }
    }
    $wanted = (Get-FileHash (Join-Path $Src "requirements.txt")).Hash
    $marker = Join-Path $Venv "requirements.sha"
    if (-not (Test-Path $marker) -or (Get-Content $marker) -ne $wanted) {
        Write-Host "Installing the requirements (when they change) ..."
        & $VenvPython -m pip install --upgrade pip
        & $VenvPython -m pip install -r (Join-Path $Src "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "Installing the requirements failed" }
        Set-Content -Path $marker -Value $wanted
    }
}

function Get-QuillOut {
    $out = Join-Path $Share "out"
    New-Item -ItemType Directory -Path $out -Force | Out-Null
    return $out
}
