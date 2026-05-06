param(
    [Parameter(Mandatory = $true)]
    [string] $Image,
    [string] $IncreaseC = "40G",
    [switch] $DryRun,
    [switch] $IUnderstandThisIsDestructive
)

. "$PSScriptRoot/partitionlab-common.ps1"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Get-PartitionLabProjectRoot
$testImages = Resolve-PartitionLabPath (Join-Path $root "test-images")
$resolvedImage = Resolve-PartitionLabPath $Image
$prefix = $testImages.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
$logFile = New-PartitionLabLogFile "destructive_guard_windows"

if ($Image -match '^(\\\\[.?]\\)?PhysicalDrive[0-9]+$') {
    throw "Refusing Windows physical disk path: $Image"
}
if (-not $resolvedImage.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Image must be under $testImages"
}
if (-not (Test-Path -LiteralPath $resolvedImage)) {
    throw "Image not found: $resolvedImage"
}
if (-not $DryRun -and -not $IUnderstandThisIsDestructive) {
    throw "Write mode requires -IUnderstandThisIsDestructive"
}

Write-PartitionLabLog $logFile "tenra Partition Lab Windows destructive guard"
Write-PartitionLabLog $logFile "target=$resolvedImage"
Write-PartitionLabLog $logFile "increase_c=$IncreaseC"
Write-PartitionLabLog $logFile "dry_run=$DryRun"
Write-PartitionLabLog $logFile "+ inspect-image.ps1 -Image $resolvedImage -Json"
$inspectionOutput = & "$PSScriptRoot/inspect-image.ps1" -Image $resolvedImage -Json
foreach ($line in $inspectionOutput) {
    Write-Output $line
    Add-Content -LiteralPath $logFile -Value $line
}

if ($DryRun) {
    Write-PartitionLabLog $logFile "Dry run complete. Real mutation is not implemented in this phase."
    exit 0
}

throw "Real destructive partition mutation is intentionally not implemented yet."
