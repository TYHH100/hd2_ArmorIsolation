param(
    [string]$Python,
    [string]$Source,
    [switch]$SmokeTest
)

$ErrorActionPreference = 'Stop'
$guiPath = Join-Path $PSScriptRoot 'tools\armor_isolation_gui.py'
if (-not (Test-Path -LiteralPath $guiPath -PathType Leaf)) {
    throw "GUI entry point not found: $guiPath"
}

$candidates = @()
if ($Python) {
    $candidates += $Python
} else {
    $candidates += (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
    $candidates += (Join-Path (Split-Path $PSScriptRoot -Parent) 'hd2-lua_mods_test\.venv\Scripts\python.exe')
    foreach ($commandName in @('py.exe', 'python.exe', 'python3.exe')) {
        $found = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($found) { $candidates += $found.Source }
    }
}

$selectedPython = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $resolvedCommand = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($resolvedCommand) { $candidate = $resolvedCommand.Source }
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
        $probeOutput = & $candidate -X utf8 -B -c 'import sys, tkinter, lz4.block; assert sys.version_info >= (3, 11); print(''ISOLATION_READY'')' 2>&1
    } catch {
        continue
    }
    if ($LASTEXITCODE -eq 0 -and ($probeOutput -contains 'ISOLATION_READY')) {
        $selectedPython = $candidate
        break
    }
}
if (-not $selectedPython) {
    throw 'Python 3.11+ with tkinter and lz4 is required. Run with -Python <python.exe> to select an interpreter.'
}

$guiArguments = @('-X', 'utf8', '-B', $guiPath)
if ($Source) { $guiArguments += @('--source', $Source) }
if ($SmokeTest) { $guiArguments += '--smoke-test' }
& $selectedPython @guiArguments
if ($LASTEXITCODE -ne 0) {
    throw "Armor isolation tool exited with code $LASTEXITCODE"
}
