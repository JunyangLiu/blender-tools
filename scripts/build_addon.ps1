$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $projectRoot "blender_addon\semantic_mesh_marker_next"
$dist = Join-Path $projectRoot "dist"
$archive = Join-Path $dist "semantic_mesh_marker_next.zip"

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Blender add-on source not found: $source"
}
New-Item -ItemType Directory -Path $dist -Force | Out-Null
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipArchiveMode] | Out-Null
$zip = [System.IO.Compression.ZipFile]::Open(
    $archive,
    [System.IO.Compression.ZipArchiveMode]::Create
)
try {
    Get-ChildItem -LiteralPath $source -Recurse -File |
        Where-Object {
            $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
            $_.Extension -notin @('.pyc', '.pyo')
        } |
        ForEach-Object {
            $relative = $_.FullName.Substring($source.Length).TrimStart('\', '/')
            $entry = "semantic_mesh_marker_next/" + ($relative -replace '\\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip,
                $_.FullName,
                $entry,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
}
finally {
    $zip.Dispose()
}
Write-Output $archive
