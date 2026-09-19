param(
    [string]$OutputDirectory,
    [string]$VisualStudioPath,
    [string]$CMake,
    [ValidateSet('Release', 'Debug')][string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$taskRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $taskRoot 'dist\armor-isolation-runtime' }
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
foreach ($taskProtected in @('dist\cm14-isolated', 'dist\b01-isolated')) {
    $taskProtectedPath = [IO.Path]::GetFullPath((Join-Path $taskRoot $taskProtected)).TrimEnd('\')
    if ($taskOutput.Equals($taskProtectedPath, [StringComparison]::OrdinalIgnoreCase) -or
        $taskOutput.StartsWith($taskProtectedPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Universal compilation cannot use a fixed experiment directory: $taskOutput"
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
if (-not (Test-Path -LiteralPath $taskCTest)) { throw 'CTest was not found next to CMake.' }
$taskNinja = Get-Command ninja -ErrorAction SilentlyContinue
if ($taskNinja) { $taskNinjaPath = $taskNinja.Source }
else { $taskNinjaPath = Join-Path $VisualStudioPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe' }
if (-not (Test-Path -LiteralPath $taskNinjaPath)) { throw 'Ninja was not found in PATH or Visual Studio.' }

$taskBuildRoot = [IO.Path]::GetFullPath((Join-Path $taskRoot 'build'))
$taskBuild = Join-Path $taskBuildRoot ('universal-runtime-' + [Guid]::NewGuid().ToString('N'))
try {
    & $CMake -S $taskRoot -B $taskBuild -G Ninja "-DCMAKE_BUILD_TYPE=$Configuration" '-DCMAKE_CXX_COMPILER=cl.exe' `
        "-DCMAKE_MAKE_PROGRAM=$taskNinjaPath" '-DBUILD_UNIVERSAL_ISOLATION=ON' "-DISOLATION_OUTPUT_DIRECTORY=$taskOutput"
    if ($LASTEXITCODE -ne 0) { throw 'Universal CMake configuration failed.' }
    & $CMake --build $taskBuild --config $Configuration --clean-first
    if ($LASTEXITCODE -ne 0) { throw 'Universal add-on compilation failed.' }
    & $taskCTest --test-dir $taskBuild -C $Configuration --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw 'Universal add-on tests failed.' }
    $taskAddon = Join-Path $taskOutput 'ArmorIsolation.addon64'
    if (-not (Test-Path -LiteralPath $taskAddon -PathType Leaf)) { throw "Build output missing: $taskAddon" }
    $taskIni = Join-Path $taskOutput 'ArmorIsolation.ini'
    if (-not (Test-Path -LiteralPath $taskIni)) {
        [IO.File]::WriteAllText($taskIni, "[ArmorIsolation]`r`nEnabled=1`r`nDiagnosticOnly=0`r`n", [Text.UTF8Encoding]::new($false))
    }
    $taskLicenses = Join-Path $taskOutput 'licenses'
    New-Item -ItemType Directory -Path $taskLicenses -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $taskRoot 'third_party\nlohmann-json-3.12.0\LICENSE.MIT') -Destination (Join-Path $taskLicenses 'nlohmann-json.LICENSE.MIT') -Force
    Copy-Item -LiteralPath (Join-Path $taskRoot 'third_party\reshade-v6.5.1\LICENSE.md') -Destination (Join-Path $taskLicenses 'ReShade.LICENSE.md') -Force
    $taskFiles = foreach ($taskName in @('ArmorIsolation.addon64', 'ArmorIsolation.ini', 'validate_runtime_profile.exe')) {
        $taskFile = Get-Item -LiteralPath (Join-Path $taskOutput $taskName)
        @{ name = $taskName; size = $taskFile.Length; sha256 = (Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    $taskRelease = @{
        schema = 'hd2-armor-runtime-release/1'; runtime_schema = 'hd2-armor-runtime/1'
        expected_game_dll_sha256 = 'cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c'
        reshade_version = '6.5.1'; sdk_api = 17; files = @($taskFiles)
    }
    [IO.File]::WriteAllText((Join-Path $taskOutput 'runtime-release.json'), ($taskRelease | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    Get-FileHash -LiteralPath $taskAddon -Algorithm SHA256
} finally {
    $taskResolvedBuild = [IO.Path]::GetFullPath($taskBuild)
    if ($taskResolvedBuild.StartsWith($taskBuildRoot.TrimEnd('\') + '\universal-runtime-', [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $taskResolvedBuild)) {
        Remove-Item -LiteralPath $taskResolvedBuild -Recurse -Force
    }
}
