$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$virtualEnvironmentPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $virtualEnvironmentPython) {
    $python = $virtualEnvironmentPython
}
else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Python was not found. Install it and the dependencies from requirements-build.txt."
    }
    $python = $pythonCommand.Source
}

Push-Location -LiteralPath $projectRoot
try {
    & $python -m PyInstaller `
        --add-data "assets/Templates:assets/Templates" `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name "AddingFrameToPhotos" `
        --icon "assets/app.ico" `
        --add-data "assets/app.ico:assets" `
        --distpath "dist" `
        --workpath "build" `
        --specpath "." `
        "main.py"

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$executable = Join-Path $projectRoot "dist\AddingFrameToPhotos.exe"

# PyInstaller replaces the EXE directly. Refresh the Explorer icon cache so an
# already-open Explorer window does not keep showing a stale default icon.
if (-not ("ShellIconCacheRefresherV2" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class ShellIconCacheRefresherV2
{
    [DllImport("shell32.dll", EntryPoint = "SHChangeNotify", CharSet = CharSet.Unicode)]
    private static extern void NotifyPath(
        int eventId,
        uint flags,
        [MarshalAs(UnmanagedType.LPWStr)] string item1,
        IntPtr item2);

    [DllImport("shell32.dll", EntryPoint = "SHChangeNotify")]
    private static extern void NotifyShell(
        int eventId,
        uint flags,
        IntPtr item1,
        IntPtr item2);

    public static void RefreshFileIcon(string path)
    {
        const int UpdateItem = 0x00002000;
        const int AssociationsChanged = 0x08000000;
        const uint PathUnicodeAndFlush = 0x00001005;
        const uint Flush = 0x00001000;

        NotifyPath(UpdateItem, PathUnicodeAndFlush, path, IntPtr.Zero);
        NotifyShell(AssociationsChanged, Flush, IntPtr.Zero, IntPtr.Zero);
    }
}
"@
}

[ShellIconCacheRefresherV2]::RefreshFileIcon($executable)
Write-Host "Done: $executable"
