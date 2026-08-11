#requires -Version 5.1

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

$ProjectDir = [System.IO.Path]::GetFullPath($PSScriptRoot)
$ParentDir = Split-Path -Parent $ProjectDir
$LogDir = Join-Path $ProjectDir "logs"
$LauncherLog = Join-Path $LogDir "launcher.log"
$PythonErrorLog = Join-Path $LogDir "pythonw-stderr.log"
$MaximumLauncherLogBytes = 1MB

function Show-AquaMessage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,

        [System.Windows.Forms.MessageBoxIcon]$Icon = (
            [System.Windows.Forms.MessageBoxIcon]::Error
        )
    )

    [void][System.Windows.Forms.MessageBox]::Show(
        $Message,
        "Aqua Process Control",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        $Icon
    )
}

function Initialize-LauncherLog {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

    if (
        (Test-Path -LiteralPath $LauncherLog -PathType Leaf) -and
        (Get-Item -LiteralPath $LauncherLog).Length -ge (
            $MaximumLauncherLogBytes
        )
    ) {
        $BackupPath = "$LauncherLog.1"
        if (Test-Path -LiteralPath $BackupPath) {
            Remove-Item -LiteralPath $BackupPath -Force
        }
        Move-Item -LiteralPath $LauncherLog -Destination $BackupPath
    }
}

function Write-LauncherLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    Add-Content -LiteralPath $LauncherLog -Encoding UTF8 -Value (
        "$Timestamp | $Message"
    )
}

$Mutex = $null
$OwnsMutex = $false

try {
    Initialize-LauncherLog
    Write-LauncherLog "Launcher invoked from '$ProjectDir'."

    $PythonCandidates = @(
        (Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"),
        (Join-Path $ParentDir ".venv\Scripts\pythonw.exe")
    )
    $PythonExe = $PythonCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1

    if (-not $PythonExe) {
        $Message = @"
Aqua could not be started because the Python environment was not found.

Expected a .venv installation in or above the 5_Aqua directory.

Please contact the system maintainer.
"@
        Write-LauncherLog "Python environment not found."
        Show-AquaMessage -Message $Message
        exit 1
    }

    $CreatedNew = $false
    $Mutex = [System.Threading.Mutex]::new(
        $true,
        "Local\AquaProcessControl",
        [ref]$CreatedNew
    )
    if (-not $CreatedNew) {
        Write-LauncherLog "A second launch was blocked."
        Show-AquaMessage -Message (
            "Aqua Process Control is already running."
        ) -Icon ([System.Windows.Forms.MessageBoxIcon]::Information)
        exit 0
    }
    $OwnsMutex = $true

    Set-Location -LiteralPath $ProjectDir
    Write-LauncherLog "Using Python '$PythonExe'."
    Write-LauncherLog "Starting GUI module 'gui.app'."

    # main.py is the hardware-facing command-line process. The operator
    # shortcut must start the GUI module, which does not operate hardware
    # until the operator explicitly connects and starts a run.
    $Process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "gui.app") `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden `
        -RedirectStandardError $PythonErrorLog `
        -PassThru `
        -Wait

    Write-LauncherLog "GUI process exited with code $($Process.ExitCode)."
    if ($Process.ExitCode -ne 0) {
        Show-AquaMessage -Message @"
Aqua closed during startup (exit code $($Process.ExitCode)).

Diagnostic details are available in:
$PythonErrorLog

Please contact the system maintainer.
"@
        exit $Process.ExitCode
    }
}
catch {
    $Detail = $_.Exception.Message
    try {
        Initialize-LauncherLog
        Write-LauncherLog "Launcher failure: $Detail"
    }
    catch {
        # The GUI message remains the last-resort diagnostic if logging fails.
    }

    Show-AquaMessage -Message @"
Aqua could not be started.

$Detail

Please contact the system maintainer.
"@
    exit 1
}
finally {
    if ($OwnsMutex -and $null -ne $Mutex) {
        $Mutex.ReleaseMutex()
    }
    if ($null -ne $Mutex) {
        $Mutex.Dispose()
    }
}
