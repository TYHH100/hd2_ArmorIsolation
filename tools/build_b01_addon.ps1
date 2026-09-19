param(
    [string]$VisualStudioPath = 'G:\App\Visual Studio',
    [string]$CMake = 'cmake',
    [string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskDevShell = Join-Path $VisualStudioPath 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll'
if (-not (Test-Path -LiteralPath $taskDevShell)) {
    throw "Visual Studio developer shell missing: $taskDevShell"
}
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'include\b01_resource_map.hpp'))) {
    throw 'Run tools/build_b01_isolated.py before building the add-on.'
}
Import-Module $taskDevShell
Enter-VsDevShell -VsInstallPath $VisualStudioPath -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
$taskBuild = Join-Path $taskRoot 'build\b01-addon'
& $CMake -S $taskRoot -B $taskBuild -G Ninja "-DCMAKE_BUILD_TYPE=$Configuration" '-DCMAKE_CXX_COMPILER=cl.exe' '-DBUILD_B01_ISOLATION=ON'
if ($LASTEXITCODE -ne 0) { throw 'CMake configuration failed.' }
& $CMake --build $taskBuild --config $Configuration --target B01ResourceIsolation probe_b01_resources test_b01_addon
if ($LASTEXITCODE -ne 0) { throw 'B01 add-on compilation failed.' }
$taskAddon = Join-Path $taskRoot 'dist\b01-isolated\addon\B01Isolation.addon64'
if (-not (Test-Path -LiteralPath $taskAddon)) { throw "Build output missing: $taskAddon" }
Get-FileHash -LiteralPath $taskAddon -Algorithm SHA256
