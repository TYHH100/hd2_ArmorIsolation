param(
    [ValidateSet('Status', 'Check', 'Install', 'Uninstall')]
    [string]$Action = 'Status',
    [string]$GamePath = 'G:\AppData\SteamLibrary\steamapps\common\Helldivers 2',
    [string]$PackagePath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\b01-isolated')
)

$ErrorActionPreference = 'Stop'
$taskGame = [IO.Path]::GetFullPath($GamePath).TrimEnd('\')
$taskPackage = [IO.Path]::GetFullPath($PackagePath).TrimEnd('\')
$taskReceiptPath = Join-Path $taskGame 'bin\B01Isolation.install.json'
$taskPrefix = '9ba626afa44a3aa3.patch_'
$taskOwner = 'hd2-mods-test-b01-isolation-v1'

function Resolve-ChildPath([string]$Root, [string]$Relative) {
    if ([IO.Path]::IsPathRooted($Relative)) { throw 'Absolute paths are not allowed in the manifest.' }
    $taskResolved = [IO.Path]::GetFullPath((Join-Path $Root $Relative))
    if (-not $taskResolved.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes the expected directory: $Relative"
    }
    return $taskResolved
}

function Assert-Hash([string]$Path, [string]$Expected) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing file: $Path" }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Expected) {
        throw "File changed or checksum mismatch: $Path"
    }
}

function Assert-NoGame {
    if (Get-Process -Name helldivers2 -ErrorAction SilentlyContinue) {
        throw 'Exit Helldivers 2 normally before installing or removing this test.'
    }
}

function Get-BasePatchFiles {
    @(Get-ChildItem -LiteralPath (Join-Path $taskGame 'data') -File |
        Where-Object Name -Match '^9ba626afa44a3aa3\.patch_\d+$')
}

if ($Action -eq 'Status') {
    [PSCustomObject]@{
        GameRunning = [bool](Get-Process -Name helldivers2 -ErrorAction SilentlyContinue)
        Installed = Test-Path -LiteralPath $taskReceiptPath
        Addon = Test-Path -LiteralPath (Join-Path $taskGame 'bin\B01Isolation.addon64')
        Log = Join-Path $taskGame 'bin\B01Isolation.log'
    } | Format-List
    if (Test-Path -LiteralPath $taskReceiptPath) { Get-Content -LiteralPath $taskReceiptPath }
    return
}

if ($Action -in @('Install', 'Uninstall')) { Assert-NoGame }
if ($Action -eq 'Uninstall') {
    if (-not (Test-Path -LiteralPath $taskReceiptPath)) { throw 'No install receipt; no files were removed.' }
    $taskReceipt = Get-Content -LiteralPath $taskReceiptPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($taskReceipt.owner -ne $taskOwner -or $taskReceipt.game_root -ne $taskGame) {
        throw 'Install receipt ownership or game path mismatch.'
    }
    foreach ($taskFile in $taskReceipt.files) {
        $taskPath = Resolve-ChildPath $taskGame $taskFile.relative_path
        Assert-Hash $taskPath $taskFile.sha256
        if ((Get-Item -LiteralPath $taskPath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Installed file was replaced by a link: $taskPath"
        }
    }
    foreach ($taskPatch in (Get-BasePatchFiles)) {
        if ([int]($taskPatch.Name -replace '^.*\.patch_', '') -gt [int]$taskReceipt.patch_index) {
            throw 'Later base patches exist. Redeploy those with the mod manager before removing this test; numbering must remain contiguous.'
        }
    }
    foreach ($taskFile in $taskReceipt.files) {
        Assert-NoGame
        Remove-Item -LiteralPath (Resolve-ChildPath $taskGame $taskFile.relative_path)
    }
    Remove-Item -LiteralPath $taskReceiptPath
    Write-Output 'B01 test removed. Original mod files were not changed. The diagnostic log was retained.'
    return
}

if (Test-Path -LiteralPath $taskReceiptPath) { throw 'This test is already installed. Remove it first.' }
$taskManifestPath = Join-Path $taskPackage 'manifest.json'
$taskManifest = Get-Content -LiteralPath $taskManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
Assert-Hash (Join-Path $taskGame 'data\game\game.dll') $taskManifest.expected_game_dll_sha256
$taskAddon = Join-Path $taskPackage 'addon\B01Isolation.addon64'
$taskIni = Join-Path $taskPackage 'addon\B01Isolation.ini'
foreach ($taskPath in @($taskAddon, $taskIni)) {
    if (-not (Test-Path -LiteralPath $taskPath -PathType Leaf)) { throw "Missing package file: $taskPath" }
}
$taskOutputNames = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($taskFile in $taskManifest.output) {
    if ($taskFile.name -notmatch '^9ba626afa44a3aa3\.patch_0(\.stream|\.gpu_resources)?$' -or
        -not $taskOutputNames.Add($taskFile.name)) {
        throw 'Unexpected or duplicate package filename.'
    }
    $taskSource = Resolve-ChildPath $taskPackage $taskFile.path
    Assert-Hash $taskSource $taskFile.sha256
    if ((Get-Item -LiteralPath $taskSource).Length -ne [long]$taskFile.size) {
        throw "Package file size mismatch: $taskSource"
    }
}
if ($taskOutputNames.Count -ne 3) { throw 'The package must contain all three patch files.' }

# Old IDs would keep affecting other suits; private IDs must also be unique among active patches.
$taskOldIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($taskResource in $taskManifest.source_resources) {
    [void]$taskOldIds.Add($taskResource.type + ':' + $taskResource.source)
}
$taskPrivateIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($taskResource in $taskManifest.mapping) {
    [void]$taskPrivateIds.Add($taskResource.type + ':' + $taskResource.target)
}
if (-not $taskOldIds.Count -or -not $taskPrivateIds.Count) { throw 'The manifest has no source or private resource IDs.' }
$taskConflicts = [Collections.Generic.List[string]]::new()
$taskActivePatches = @(Get-ChildItem -LiteralPath (Join-Path $taskGame 'data') -File |
    Where-Object Name -Match '\.patch_\d+$')
foreach ($taskPatch in $taskActivePatches) {
    $taskStream = [IO.File]::OpenRead($taskPatch.FullName)
    try {
        $taskHeader = [byte[]]::new(72)
        $taskStream.ReadExactly($taskHeader, 0, $taskHeader.Length)
        $taskTypes = [BitConverter]::ToUInt32($taskHeader, 4)
        $taskCount = [BitConverter]::ToUInt32($taskHeader, 8)
        if ([BitConverter]::ToUInt32($taskHeader, 0) -ne 0xF0000011u -or $taskTypes -gt 1000 -or
            $taskCount -gt 1000000 -or 72L + 32L * $taskTypes + 80L * $taskCount -gt $taskStream.Length) {
            throw "Cannot inspect active patch: $($taskPatch.Name)"
        }
        $taskStream.Position = 72L + 32L * $taskTypes
        $taskEntry = [byte[]]::new(80)
        for ($taskIndex = 0; $taskIndex -lt $taskCount; ++$taskIndex) {
            $taskStream.ReadExactly($taskEntry, 0, $taskEntry.Length)
            $taskKey = '{0:x16}:{1:x16}' -f [BitConverter]::ToUInt64($taskEntry, 8), [BitConverter]::ToUInt64($taskEntry, 0)
            if ($taskOldIds.Contains($taskKey)) {
                $taskConflicts.Add('old ID: ' + $taskPatch.Name + ' ' + $taskKey)
            }
            if ($taskPrivateIds.Contains($taskKey)) {
                $taskConflicts.Add('private ID: ' + $taskPatch.Name + ' ' + $taskKey)
            }
        }
    } finally { $taskStream.Dispose() }
}
if ($taskConflicts.Count) {
    throw ('Disable the original B01 mod or conflicting resource overrides using their manager before this test: ' +
        (($taskConflicts | Select-Object -Unique -First 12) -join ', '))
}

$taskIndices = @((Get-BasePatchFiles) | ForEach-Object { [int]($_.Name -replace '^.*\.patch_', '') } | Sort-Object)
for ($taskIndex = 0; $taskIndex -lt $taskIndices.Count; ++$taskIndex) {
    if ($taskIndices[$taskIndex] -ne $taskIndex) { throw 'Existing base patch numbering is not contiguous from zero.' }
}
$taskNumber = $taskIndices.Count
$taskCopies = [Collections.Generic.List[object]]::new()
foreach ($taskFile in $taskManifest.output) {
    $taskSuffix = $taskFile.name.Substring('9ba626afa44a3aa3.patch_0'.Length)
    $taskCopies.Add([PSCustomObject]@{
        source = Resolve-ChildPath $taskPackage $taskFile.path
        relative_path = 'data\' + $taskPrefix + $taskNumber + $taskSuffix
        sha256 = $taskFile.sha256
    })
}
foreach ($taskName in @('B01Isolation.addon64', 'B01Isolation.ini')) {
    $taskSource = Join-Path $taskPackage ('addon\' + $taskName)
    $taskCopies.Add([PSCustomObject]@{
        source = $taskSource
        relative_path = 'bin\' + $taskName
        sha256 = (Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash
    })
}
foreach ($taskFile in $taskCopies) {
    if (Test-Path -LiteralPath (Resolve-ChildPath $taskGame $taskFile.relative_path)) {
        throw "Destination already exists: $($taskFile.relative_path)"
    }
}
if ($Action -eq 'Check') {
    [PSCustomObject]@{
        Check = 'Passed'
        GameRunning = [bool](Get-Process -Name helldivers2 -ErrorAction SilentlyContinue)
        Patch = $taskPrefix + $taskNumber
        ActivePatches = $taskActivePatches.Count
        SourceResources = $taskOldIds.Count
        PrivateResources = $taskPrivateIds.Count
        ExistingCM14Addon = Test-Path -LiteralPath (Join-Path $taskGame 'bin\CM14Isolation.addon64')
    } | Format-List
    Write-Output 'Read-only preflight completed. No game files were changed.'
    return
}

$taskCreated = [Collections.Generic.List[string]]::new()
try {
    foreach ($taskFile in $taskCopies) {
        Assert-NoGame
        $taskDestination = Resolve-ChildPath $taskGame $taskFile.relative_path
        $taskOut = [IO.File]::Open($taskDestination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $taskCreated.Add($taskDestination)
        try {
            $taskIn = [IO.File]::OpenRead($taskFile.source)
            try { $taskIn.CopyTo($taskOut) } finally { $taskIn.Dispose() }
        } finally { $taskOut.Dispose() }
        Assert-Hash $taskDestination $taskFile.sha256
    }
    $taskReceipt = [ordered]@{
        owner = $taskOwner
        game_root = $taskGame
        installed_utc = [DateTime]::UtcNow.ToString('o')
        patch_index = $taskNumber
        files = @($taskCopies | Select-Object relative_path, sha256)
    }
    $taskReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $taskReceiptPath -Encoding utf8
} catch {
    # Only newly created, prechecked destinations are candidates for rollback.
    if (-not (Get-Process -Name helldivers2 -ErrorAction SilentlyContinue)) {
        foreach ($taskPath in $taskCreated) {
            if (Test-Path -LiteralPath $taskPath) { Remove-Item -LiteralPath $taskPath }
        }
    }
    throw
}
Write-Output "Installed B01 test as $taskPrefix$taskNumber and B01Isolation.addon64. Restart the game to test."
