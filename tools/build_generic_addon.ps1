param(
    [Parameter(Mandatory)][string]$HeaderDirectory,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string]$BuildDirectory,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9][a-z0-9_-]{0,63}$')][string]$PackageId,
    [string]$VisualStudioPath,
    [string]$CMake,
    [ValidateSet('Release', 'Debug')][string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskHeaders = [IO.Path]::GetFullPath($HeaderDirectory)
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
$taskBuild = [IO.Path]::GetFullPath($BuildDirectory)
if (-not (Test-Path -LiteralPath (Join-Path $taskHeaders 'generic_resource_map.hpp') -PathType Leaf)) {
    throw 'The generated package header generic_resource_map.hpp is missing.'
}
foreach ($taskProtected in @('dist\cm14-isolated', 'dist\b01-isolated', 'build\cm14-addon', 'build\b01-addon')) {
    $taskProtectedPath = [IO.Path]::GetFullPath((Join-Path $taskRoot $taskProtected)).TrimEnd('\')
    foreach ($taskDestination in @($taskOutput, $taskBuild)) {
        if ($taskDestination.Equals($taskProtectedPath, [StringComparison]::OrdinalIgnoreCase) -or
            $taskDestination.StartsWith($taskProtectedPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Generic compilation cannot use a fixed experiment directory: $taskDestination"
        }
    }
}

if (-not $VisualStudioPath) {
    $taskVsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $taskVsWhere) {
        $taskVsPaths = @(& $taskVsWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath)
        if ($LASTEXITCODE -eq 0 -and $taskVsPaths.Count) { $VisualStudioPath = $taskVsPaths[0] }
    }
    if (-not $VisualStudioPath -and (Test-Path -LiteralPath 'G:\App\Visual Studio\Common7\Tools\Microsoft.VisualStudio.DevShell.dll')) {
        $VisualStudioPath = 'G:\App\Visual Studio'
    }
}
if (-not $VisualStudioPath) { throw 'Visual Studio C++ x64 build tools were not found.' }
$taskDevShell = Join-Path $VisualStudioPath 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll'
if (-not (Test-Path -LiteralPath $taskDevShell)) { throw "Visual Studio developer shell missing: $taskDevShell" }
Import-Module $taskDevShell
Enter-VsDevShell -VsInstallPath $VisualStudioPath -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
$env:VSLANG = '1033'

if (-not $CMake) {
    $taskCMakeCommand = Get-Command cmake -ErrorAction SilentlyContinue
    if ($taskCMakeCommand) { $CMake = $taskCMakeCommand.Source }
    else { $CMake = Join-Path $VisualStudioPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe' }
}
$taskResolvedCMake = Get-Command $CMake -ErrorAction SilentlyContinue
if (-not $taskResolvedCMake) { throw "CMake was not found: $CMake" }
$CMake = $taskResolvedCMake.Source
$taskCTest = Join-Path (Split-Path -Parent $CMake) 'ctest.exe'
if (-not (Test-Path -LiteralPath $taskCTest)) { throw "CTest was not found next to CMake: $taskCTest" }
$taskNinja = Get-Command ninja -ErrorAction SilentlyContinue
if ($taskNinja) { $taskNinjaPath = $taskNinja.Source }
else { $taskNinjaPath = Join-Path $VisualStudioPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe' }
if (-not (Test-Path -LiteralPath $taskNinjaPath)) { throw 'Ninja was not found in PATH or Visual Studio.' }

& $CMake -S $taskRoot -B $taskBuild -G Ninja "-DCMAKE_BUILD_TYPE=$Configuration" '-DCMAKE_CXX_COMPILER=cl.exe' `
    "-DCMAKE_MAKE_PROGRAM=$taskNinjaPath" '-DBUILD_GENERIC_ISOLATION=ON' `
    "-DISOLATION_HEADER_DIRECTORY=$taskHeaders" "-DISOLATION_OUTPUT_DIRECTORY=$taskOutput" "-DISOLATION_PACKAGE_ID=$PackageId"
if ($LASTEXITCODE -ne 0) { throw 'Generic CMake configuration failed.' }
# Localized MSVC include output can leave Ninja's header dependency list empty.
& $CMake --build $taskBuild --config $Configuration --clean-first --target GenericResourceIsolation probe_generic_resources test_generic_addon
if ($LASTEXITCODE -ne 0) { throw 'Generic add-on compilation failed.' }
& $taskCTest --test-dir $taskBuild -C $Configuration -R '^generic_addon_transaction$' --output-on-failure
if ($LASTEXITCODE -ne 0) { throw 'Generic add-on transaction test failed.' }
$taskAddon = Join-Path $taskOutput "ArmorIsolation_$PackageId.addon64"
if (-not (Test-Path -LiteralPath $taskAddon -PathType Leaf)) { throw "Build output missing: $taskAddon" }
Get-FileHash -LiteralPath $taskAddon -Algorithm SHA256
