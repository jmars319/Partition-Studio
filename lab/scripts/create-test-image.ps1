param(
    [string] $Scenario = "normal-c-e-layout",
    [string] $Output,
    [ValidateSet("GPT", "MBR")]
    [string] $PartitionTable = "GPT",
    [string] $DiskSize = "12GiB",
    [string] $CSize = "4GiB",
    [string] $ESize = "7GiB",
    [string] $CFill = "3500MiB",
    [string] $EData = "2GiB",
    [switch] $NoFormat,
    [switch] $NoPopulate,
    [switch] $Force,
    [switch] $DryRun
)

. "$PSScriptRoot/partitionlab-common.ps1"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Get-PartitionLabProjectRoot
$testImages = Join-Path $root "test-images"
New-Item -ItemType Directory -Force -Path $testImages | Out-Null

if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $testImages "$Scenario.vhdx"
}

$resolvedOutput = Assert-PartitionLabPathUnderTestImages $Output
$logFile = New-PartitionLabLogFile "create_windows_$Scenario"

Write-PartitionLabLog $logFile "tenra Partition Lab Windows image creation"
Write-PartitionLabLog $logFile "scenario=$Scenario"
Write-PartitionLabLog $logFile "output=$resolvedOutput"
Write-PartitionLabLog $logFile "disk_size=$DiskSize c_size=$CSize e_size=$ESize partition_table=$PartitionTable"

if (-not (Test-PartitionLabIsWindows) -and -not $DryRun) {
    throw "create-test-image.ps1 is the Windows VHDX path. Use create-raw-image.ps1 or create_image.py on non-Windows hosts."
}

if (-not $DryRun -and -not (Test-PartitionLabAdministrator)) {
    throw "Administrator PowerShell is required to create, attach, format, and detach VHDX images with diskpart."
}

if ((Test-Path -LiteralPath $resolvedOutput) -and -not $Force) {
    throw "Output already exists. Use -Force to replace it: $resolvedOutput"
}

$diskMiB = ConvertTo-PartitionLabMiB $DiskSize
$cMiB = ConvertTo-PartitionLabMiB $CSize
$eMiB = ConvertTo-PartitionLabMiB $ESize
$cFillBytes = ConvertTo-PartitionLabBytes $CFill
$eDataBytes = ConvertTo-PartitionLabBytes $EData
$letters = @()
if (-not $NoFormat -and -not $NoPopulate) {
    if ((Test-PartitionLabIsWindows) -or -not $DryRun) {
        $letters = Get-PartitionLabFreeDriveLetters -Count 2
    }
    else {
        $letters = @("P", "Q")
    }
}

if ($Force -and (Test-Path -LiteralPath $resolvedOutput)) {
    Write-PartitionLabLog $logFile "+ Remove-Item -LiteralPath $resolvedOutput -Force"
    if (-not $DryRun) {
        Remove-Item -LiteralPath $resolvedOutput -Force
    }
}

$commands = @(
    "create vdisk file=`"$resolvedOutput`" maximum=$diskMiB type=expandable",
    "select vdisk file=`"$resolvedOutput`"",
    "attach vdisk",
    "convert $($PartitionTable.ToLowerInvariant())",
    "create partition primary size=$cMiB"
)

if (-not $NoFormat) {
    $commands += "format fs=ntfs quick label=`"C`""
    if (-not $NoPopulate) {
        $commands += "assign letter=$($letters[0])"
    }
}

$commands += "create partition primary size=$eMiB"

if (-not $NoFormat) {
    $commands += "format fs=ntfs quick label=`"E`""
    if (-not $NoPopulate) {
        $commands += "assign letter=$($letters[1])"
    }
}

$commands += "exit"

Invoke-PartitionLabDiskPart -Commands $commands -LogFile $logFile -DryRun:$DryRun

try {
    if (-not $NoFormat -and -not $NoPopulate) {
        $cRoot = "$($letters[0]):\"
        $eRoot = "$($letters[1]):\"
        $cData = Join-Path $cRoot "Users\LabUser"
        $eDataRoot = Join-Path $eRoot "data\projects"
        $eChecksums = Join-Path $eRoot "data\checksums"

        foreach ($directory in @($cData, $eDataRoot, $eChecksums)) {
            Write-PartitionLabLog $logFile "+ New-Item -ItemType Directory -Force -Path $directory"
            if (-not $DryRun) {
                New-Item -ItemType Directory -Force -Path $directory | Out-Null
            }
        }

        $cFile = Join-Path $cData "fill-c-01.dat"
        $eFile = Join-Path $eDataRoot "archive-001.bin"
        Write-PartitionLabLog $logFile "+ fsutil file createnew `"$cFile`" $cFillBytes"
        Write-PartitionLabLog $logFile "+ fsutil file createnew `"$eFile`" $eDataBytes"
        if (-not $DryRun) {
            foreach ($line in (& fsutil file createnew $cFile $cFillBytes 2>&1)) {
                Write-Output $line
                Add-Content -LiteralPath $logFile -Value $line
            }
            foreach ($line in (& fsutil file createnew $eFile $eDataBytes 2>&1)) {
                Write-Output $line
                Add-Content -LiteralPath $logFile -Value $line
            }
            $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $eFile
            $manifest = Join-Path $eChecksums "manifest.sha256"
            "$($hash.Hash.ToLowerInvariant())  data/projects/archive-001.bin" | Set-Content -LiteralPath $manifest -Encoding ASCII
        }
    }
}
finally {
    $cleanup = @("select vdisk file=`"$resolvedOutput`"")
    if ($letters.Count -ge 2) {
        $cleanup += "select volume $($letters[0])"
        $cleanup += "remove letter=$($letters[0])"
        $cleanup += "select volume $($letters[1])"
        $cleanup += "remove letter=$($letters[1])"
    }
    $cleanup += "detach vdisk"
    $cleanup += "exit"
    try {
        Invoke-PartitionLabDiskPart -Commands $cleanup -LogFile $logFile -DryRun:$DryRun
    }
    catch {
        Write-PartitionLabLog $logFile "Cleanup failed: $($_.Exception.Message)"
        throw
    }
}

Write-PartitionLabLog $logFile "Created disposable VHDX image: $resolvedOutput"
