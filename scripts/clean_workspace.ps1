[CmdletBinding()]
param([switch]$Apply, [switch]$BuildCache)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$separator = [IO.Path]::DirectorySeparatorChar
$workspacePrefix = $projectRoot + $separator
$tracked = @(& git -C $projectRoot -c core.quotepath=false ls-files)
if ($LASTEXITCODE -ne 0) { throw 'Cannot check tracked files; cleanup cancelled.' }

$candidates = @(Get-ChildItem -LiteralPath $projectRoot -Force | Where-Object {
    $_.Name -match '^\.(?:pytest-tmp|test-tmp)(?:-|$)' -or
    $_.Name -in @('.pytest_cache', '.ruff_cache', '__pycache__', 'htmlcov') -or
    (-not $_.PSIsContainer -and $_.Name -like '.coverage*')
})
foreach ($folder in @('stylemate', 'evaluation', 'scripts', 'tests')) {
    $sourceRoot = Join-Path $projectRoot $folder
    $candidates += @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force -Directory -Filter '__pycache__')
}
if ($BuildCache -and (Test-Path -LiteralPath (Join-Path $projectRoot 'dist/native-build'))) {
    $candidates += Get-Item -LiteralPath (Join-Path $projectRoot 'dist/native-build')
}
$targets = @($candidates | Sort-Object FullName -Unique)

# Validate every absolute path before the first deletion. Keep all operations
# in PowerShell and never follow junctions or remove versioned files.
foreach ($target in $targets) {
    $absolute = [IO.Path]::GetFullPath($target.FullName)
    if (-not $absolute.StartsWith($workspacePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside this workspace: $absolute"
    }
    if (($target.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing junction or symbolic link: $absolute"
    }
    $relative = $absolute.Substring($workspacePrefix.Length).Replace('\', '/')
    if (@($tracked | Where-Object { $_ -eq $relative -or $_.StartsWith($relative + '/') }).Count -gt 0) {
        throw "Refusing tracked content: $relative"
    }
    if ($target.PSIsContainer -and @(Get-ChildItem -LiteralPath $absolute -Recurse -Force |
            Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }).Count -gt 0) {
        throw "Refusing tree containing a junction or symbolic link: $relative"
    }
}

foreach ($target in $targets) {
    $relative = $target.FullName.Substring($workspacePrefix.Length)
    if ($Apply) {
        Remove-Item -LiteralPath $target.FullName -Recurse -Force
        Write-Output "Removed: $relative"
    } else {
        Write-Output "Would remove: $relative"
    }
}
Write-Output "Targets: $($targets.Count). Apply: $([bool]$Apply)."
if (-not $Apply) { Write-Output 'Preview only. Use -Apply to delete these caches; -BuildCache also includes dist/native-build.' }
