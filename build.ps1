$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$virtualEnvironmentPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $virtualEnvironmentPython) {
    $python = $virtualEnvironmentPython
}
else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Не найден Python. Установите его и зависимости из requirements-build.txt."
    }
    $python = $pythonCommand.Source
}

Push-Location -LiteralPath $projectRoot
try {
    & $python -m PyInstaller `
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
        throw "PyInstaller завершился с кодом $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$executable = Join-Path $projectRoot "dist\AddingFrameToPhotos.exe"

# PyInstaller заменяет EXE напрямую, поэтому уже открытый Проводник может
# продолжать показывать закэшированный стандартный значок для этого пути.
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
Write-Host "Готово: $executable"
