<#
.SYNOPSIS
Installs what this workspace needs on Windows 10/11 and is missing (Python 3.11, Git; the Visual C++
runtime with -Proc), then runs scripts\setup.py. Safe to re-run.

.DESCRIPTION
Uses winget (App Installer) when it is there, else the official installers from python.org and
git-for-windows. Python and Git are installed for the current user where possible. Windows PowerShell 5.1
or PowerShell 7. Run it from the repository:

    powershell -ExecutionPolicy Bypass -File scripts\install\install_prereqs_windows.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install\install_prereqs_windows.ps1 -NoMonitor
    powershell -ExecutionPolicy Bypass -File scripts\install\install_prereqs_windows.ps1 -DryRun

Arguments that are not options of this script go to setup.py (for example --skip-media).

.PARAMETER DryRun
Print the plan, change nothing.
.PARAMETER Monitor
Accepted for older command lines: MPF Monitor is installed by default.
.PARAMETER NoMonitor
Leave MPF Monitor out (setup.py --no-monitor).
.PARAMETER Proc
The real machine: also the Visual C++ 2015-2022 runtime that MPF's pypinproc needs, and a check for FTDI's D2XX driver.
.PARAMETER NoSetup
Prerequisites only, no setup.py.
.PARAMETER NoWinget
Use the downloaded installers even when winget is there.
.PARAMETER Yes
No questions.
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Monitor,
    [switch]$NoMonitor,
    [switch]$Proc,
    [switch]$NoSetup,
    [switch]$NoWinget,
    [switch]$Yes,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$SetupArgs
)

$ErrorActionPreference = 'Stop'
# Run from a clone, it sets up that clone. Run on its own (irm ... | iex, README "Install"), it first clones the
# repository into $env:TRON_DIR (default ~\Tron-Legacy-MPF, outside OneDrive), branch $env:TRON_BRANCH (default
# main), from $env:TRON_REPO; an existing clone gets a git pull.
$Clone = -not ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot '..\setup.py')))
$Root = if (-not $Clone) { Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
        elseif ($env:TRON_DIR) { $env:TRON_DIR } else { Join-Path $HOME 'Tron-Legacy-MPF' }
$RepoUrl = if ($env:TRON_REPO) { $env:TRON_REPO } else { 'https://github.com/Ashram56/Tron-Legacy-MPF.git' }
$RepoBranch = if ($env:TRON_BRANCH) { $env:TRON_BRANCH } else { 'main' }

# The last Python 3.11 release with Windows installers (later 3.11 releases are source-only security fixes)
$PyOrgVersion = '3.11.9'
$GitVersion = '2.47.1'
$GitUrl = "https://github.com/git-for-windows/git/releases/download/v$GitVersion.windows.1/Git-$GitVersion-64-bit.exe"
$FtdiUrl = 'https://ftdichip.com/drivers/d2xx-drivers/'

$OnWindows = $env:OS -eq 'Windows_NT'
$Arm = $env:PROCESSOR_ARCHITECTURE -eq 'ARM64'
$PyOrgArch = if ($Arm) { 'arm64' } else { 'amd64' }
$PyOrgUrl = "https://www.python.org/ftp/python/$PyOrgVersion/python-$PyOrgVersion-$PyOrgArch.exe"
$VcArch = if ($Arm) { 'arm64' } else { 'x64' }
$VcUrl = "https://aka.ms/vs/17/release/vc_redist.$VcArch.exe"

function Write-Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" }
function Write-Note([string]$Text) { Write-Host "    $Text" }

function Invoke-Step {
    param([string]$Exe, [string[]]$Arguments = @())
    Write-Host ('    $ ' + $Exe + ' ' + ($Arguments -join ' '))
    if ($DryRun) { return }
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed (exit code $LASTEXITCODE)" }
}

function Confirm-Step([string]$Question) {
    if ($DryRun -or $Yes) { return }
    $answer = Read-Host "    $Question [Y/n]"
    if ($answer -match '^[nN]') { throw 'cancelled' }
}

function Invoke-Installer {
    # Download an installer to %TEMP% and run it silently
    param([string]$Url, [string]$Arguments)
    $file = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetFileName($Url))
    Write-Host "    download $Url"
    Write-Host "    $ $file $Arguments"
    if ($DryRun) { return }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $Url -OutFile $file -UseBasicParsing
    $p = Start-Process -FilePath $file -ArgumentList $Arguments -Wait -PassThru
    Remove-Item $file -ErrorAction SilentlyContinue
    # 3010: success, a reboot is pending; 1638: a newer version is already installed
    if ($p.ExitCode -notin 0, 3010, 1638) { throw "$file failed (exit code $($p.ExitCode))" }
}

function Test-Python([string]$Exe) {
    if (-not $Exe -or -not (Test-Path $Exe)) { return $false }
    & $Exe -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)' 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Find-Python {
    # The py launcher first (it knows every registered install), then the default install folders.
    # Never the bare "python": on a fresh Windows that is the Microsoft Store stub.
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $exe = & $py.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Python $exe)) { return $exe }
    }
    $suffix = if ($Arm) { '-arm64' } else { '' }
    foreach ($dir in @("$env:LOCALAPPDATA\Programs\Python\Python311$suffix", "$env:ProgramFiles\Python311$suffix")) {
        $exe = Join-Path $dir 'python.exe'
        if (Test-Python $exe) { return $exe }
    }
    return $null
}

function Find-Git {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) { return $git.Source }
    foreach ($exe in @("$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
        if (Test-Path $exe) { return $exe }
    }
    return $null
}

function Test-VcRuntime {
    foreach ($key in @("HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\$VcArch",
                       "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\$VcArch")) {
        $item = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
        if ($item -and $item.Installed -eq 1) { return $true }
    }
    return $false
}

try {
    if (-not $OnWindows) {
        if (-not $DryRun) { throw 'this script is for Windows (macOS and Linux: the install_prereqs_*.sh scripts)' }
        Write-Note 'not Windows: showing the plan only'
    }
    $winget = $null
    if (-not $NoWinget) { $winget = Get-Command winget -ErrorAction SilentlyContinue }
    $mode = if ($DryRun) { ', dry run' } else { '' }
    Write-Step "Tron Legacy MPF prerequisites on Windows ($env:PROCESSOR_ARCHITECTURE$mode)"
    if ($winget) { Write-Note "winget: $($winget.Source)" } else { Write-Note 'winget: not used (downloaded installers)' }
    $wingetArgs = @('--exact', '--silent', '--accept-package-agreements', '--accept-source-agreements', '--source', 'winget')

    # ---------------------------------------------------------------- Git
    Write-Step 'Git'
    $git = Find-Git
    if ($git) {
        Write-Note "in place: $git"
    } else {
        Confirm-Step 'Install Git?'
        if ($winget) {
            Invoke-Step $winget.Source (@('install', '--id', 'Git.Git') + $wingetArgs)
        } else {
            Invoke-Installer $GitUrl '/VERYSILENT /NORESTART /NOCANCEL /SP- /SUPPRESSMSGBOXES'
        }
        $env:Path = "$env:ProgramFiles\Git\cmd;$env:Path"
        if (-not $DryRun -and -not (Find-Git)) { throw 'Git is still missing after the install' }
    }

    # ---------------------------------------------------------------- Python 3.11
    Write-Step 'Python 3.11'
    $python = Find-Python
    if ($python) {
        Write-Note "in place: $python"
    } else {
        Confirm-Step "Install Python $PyOrgVersion for this user?"
        if ($winget) {
            Invoke-Step $winget.Source (@('install', '--id', 'Python.Python.3.11', '--scope', 'user') + $wingetArgs)
        } else {
            Invoke-Installer $PyOrgUrl 'InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 /quiet'
        }
        if ($DryRun) {
            $python = 'py -3.11'
        } else {
            $python = Find-Python
            if (-not $python) { throw 'Python 3.11 is still missing after the install (open a new terminal and retry)' }
        }
        Write-Note "Python: $python"
    }

    # ---------------------------------------------------------------- PATH
    # winget's per-user Python and an older install may leave python.exe off PATH: put Python and its
    # Scripts folder first in the user PATH (ahead of the Microsoft Store "python" stub in WindowsApps)
    Write-Step 'Python 3.11 on the user PATH'
    $pyDir = if ($python -and (Test-Path $python)) { Split-Path -Parent $python } else { "$env:LOCALAPPDATA\Programs\Python\Python311" }
    $want = @($pyDir, (Join-Path $pyDir 'Scripts'))
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { $userPath = '' }
    $parts = @($userPath -split ';' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') })
    $missing = @($want | Where-Object { $parts -notcontains $_.TrimEnd('\') })
    if ($missing.Count -eq 0) {
        Write-Note "in place: $($want -join ';')"
    } else {
        Write-Note "add to the user PATH: $($missing -join ';')"
        if (-not $DryRun) {
            [Environment]::SetEnvironmentVariable('Path', ((@($missing) + $parts) -join ';'), 'User')
            $env:Path = ($missing -join ';') + ';' + $env:Path
            Write-Note 'done (terminals opened from now on see it; close and reopen this one)'
        }
    }

    # ---------------------------------------------------------------- long paths
    # Windows limits paths to 260 characters unless LongPathsEnabled is set (machine-wide, needs administrator);
    # pip, Godot's import cache and the asset submodule can go past it
    Write-Step 'Windows long path support'
    $fsKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem'
    $longPaths = (Get-ItemProperty -Path $fsKey -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
    if ($longPaths -eq 1) {
        Write-Note 'in place (LongPathsEnabled = 1)'
    } else {
        Confirm-Step 'Enable long paths? (machine setting: Windows asks for administrator rights)'
        $setCmd = "Set-ItemProperty -Path '$fsKey' -Name LongPathsEnabled -Value 1 -Type DWord"
        Write-Host "    $ $setCmd"
        if (-not $DryRun) {
            $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
                [Security.Principal.WindowsBuiltInRole]::Administrator)
            try {
                if ($admin) {
                    Invoke-Expression $setCmd
                } else {
                    Start-Process -FilePath 'powershell' -Verb RunAs -Wait -WindowStyle Hidden `
                        -ArgumentList @('-NoProfile', '-Command', $setCmd)
                }
            } catch {
                Write-Note "could not change it ($($_.Exception.Message))"
            }
            $longPaths = (Get-ItemProperty -Path $fsKey -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
            if ($longPaths -eq 1) { Write-Note 'enabled' }
            else { Write-Note 'warning: still off; run this script once from an administrator PowerShell, or keep the repository in a short folder such as C:\tron' }
        }
    }
    $gitExe = Find-Git
    if ($gitExe -and -not $DryRun) {
        $gitLong = & $gitExe config --global --get core.longpaths 2>$null
        if ($gitLong -ne 'true') { Invoke-Step $gitExe @('config', '--global', 'core.longpaths', 'true') }
        else { Write-Note 'git core.longpaths: in place' }
    } else {
        Write-Note '$ git config --global core.longpaths true'
    }

    # ---------------------------------------------------------------- P-ROC
    if ($Proc) {
        Write-Step 'Visual C++ 2015-2022 runtime (MPF''s pypinproc needs MSVCP140.dll)'
        if (Test-VcRuntime) {
            Write-Note 'in place'
        } elseif ($winget) {
            Invoke-Step $winget.Source (@('install', '--id', "Microsoft.VCRedist.2015+.$VcArch") + $wingetArgs)
        } else {
            Invoke-Installer $VcUrl '/install /quiet /norestart'
        }
        Write-Step 'FTDI D2XX driver (the P-ROC''s USB driver)'
        if (Test-Path "$env:SystemRoot\System32\ftd2xx.dll") {
            Write-Note 'in place (ftd2xx.dll)'
        } else {
            Write-Note "not found: install it from $FtdiUrl, then plug in the P-ROC"
        }
        if ($Arm) { Write-Note 'warning: MPF has no pypinproc for Windows on ARM; the P-ROC needs an x64 PC' }
    }

    # ---------------------------------------------------------------- repository (run on its own: clone it)
    if ($Clone) {
        Write-Step "Repository: $RepoUrl ($RepoBranch) in $Root"
        $gitExe = Find-Git
        if (-not $gitExe) { $gitExe = 'git' }
        if (Test-Path (Join-Path $Root '.git')) { Invoke-Step $gitExe @('-C', $Root, 'pull', '--ff-only') }
        else { Invoke-Step $gitExe @('clone', '--branch', $RepoBranch, $RepoUrl, $Root) }
    }

    # ---------------------------------------------------------------- workspace
    if ($NoSetup) {
        Write-Note "skipping scripts\setup.py (-NoSetup): run  $python scripts\setup.py  when ready"
    } else {
        Write-Step 'Workspace (scripts\setup.py)'
        $cmdArgs = @("$Root\scripts\setup.py")
        if ($NoMonitor) { $cmdArgs += '--no-monitor' }
        if ($DryRun) { $cmdArgs += '--dry-run' }
        if ($SetupArgs) { $cmdArgs += $SetupArgs }
        Invoke-Step $python $cmdArgs
    }

    $suffix = if ($DryRun) { ' (dry run: nothing was changed)' } else { '' }
    Write-Step "Done$suffix"
    if (-not $NoSetup) {
        $mon = if ($NoMonitor) { '' } else { ' --monitor' }
        Write-Note "In ${Root}:"
        Write-Note "Start the game:  .venv\Scripts\python scripts\run.py$mon"
        Write-Note 'Run the tests:   .venv\Scripts\python -m pytest -q tests'
    }
    exit 0
} catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
