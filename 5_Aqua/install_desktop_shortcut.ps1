#requires -Version 5.1

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir = [System.IO.Path]::GetFullPath($PSScriptRoot)
$LauncherPath = Join-Path $ProjectDir "start_aqua.ps1"
if (-not (Test-Path -LiteralPath $LauncherPath -PathType Leaf)) {
    throw "Aqua launcher not found: $LauncherPath"
}

$DesktopDir = [Environment]::GetFolderPath(
    [Environment+SpecialFolder]::DesktopDirectory
)
if ([string]::IsNullOrWhiteSpace($DesktopDir)) {
    throw "The current user's Desktop directory could not be resolved."
}

$PowerShellExe = Join-Path $PSHOME "powershell.exe"
if (-not (Test-Path -LiteralPath $PowerShellExe -PathType Leaf)) {
    throw "Windows PowerShell was not found: $PowerShellExe"
}

$ShortcutPath = Join-Path $DesktopDir "Aqua Process Control.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)

try {
    $Shortcut.TargetPath = $PowerShellExe
    $Shortcut.Arguments = (
        '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ' +
        ('"{0}"' -f $LauncherPath)
    )
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.Description = "Launch Aqua Process Control"

    $RepositoryIcon = Get-ChildItem `
        -LiteralPath $ProjectDir `
        -Filter "*.ico" `
        -File `
        -Recurse `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if ($null -ne $RepositoryIcon) {
        $IconPath = $RepositoryIcon.FullName
    }
    else {
        $ParentDir = Split-Path -Parent $ProjectDir
        $PythonCandidates = @(
            (Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"),
            (Join-Path $ParentDir ".venv\Scripts\pythonw.exe")
        )
        $IconPath = $PythonCandidates |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1

        if (-not $IconPath) {
            $IconPath = $PowerShellExe
        }
    }

    $Shortcut.IconLocation = "$IconPath,0"
    $Shortcut.Save()
}
finally {
    if ($null -ne $Shortcut) {
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject(
            $Shortcut
        )
    }
    if ($null -ne $Shell) {
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject(
            $Shell
        )
    }
}

Write-Output "Shortcut created: $ShortcutPath"
Write-Output "Target: $PowerShellExe"
Write-Output "Working directory: $ProjectDir"
Write-Output "Icon: $IconPath"
