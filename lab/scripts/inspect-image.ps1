param(
    [Parameter(Mandatory = $true)]
    [string] $Image,
    [switch] $Json,
    [switch] $AllowOutsideTestImages
)

. "$PSScriptRoot/partitionlab-common.ps1"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Get-PartitionLabProjectRoot
$testImages = Resolve-PartitionLabPath (Join-Path $root "test-images")
if ($Image -match '^(\\\\[.?]\\)?PhysicalDrive[0-9]+$') {
    throw "Refusing Windows physical disk path: $Image"
}
$resolvedImage = Resolve-PartitionLabPath $Image
$prefix = $testImages.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $AllowOutsideTestImages -and -not $resolvedImage.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Image must be under $testImages unless -AllowOutsideTestImages is provided."
}
if (-not (Test-Path -LiteralPath $resolvedImage)) {
    throw "Image not found: $resolvedImage"
}

$extension = [System.IO.Path]::GetExtension($resolvedImage).ToLowerInvariant()
if ((Test-PartitionLabIsWindows) -and ($extension -eq ".vhd" -or $extension -eq ".vhdx")) {
    $mounted = $null
    try {
        $mounted = Mount-DiskImage -ImagePath $resolvedImage -ReadOnly -NoDriveLetter -PassThru
        $disk = Get-DiskImage -ImagePath $resolvedImage | Get-Disk
        $partitions = @()
        foreach ($partition in (Get-Partition -DiskNumber $disk.Number | Sort-Object PartitionNumber)) {
            $volume = $partition | Get-Volume -ErrorAction SilentlyContinue
            $gptType = $partition.PSObject.Properties["GptType"]
            $partitions += [pscustomobject] @{
                number = $partition.PartitionNumber
                type = $partition.Type
                gpt_type = if ($null -ne $gptType) { $gptType.Value } else { $null }
                offset_bytes = $partition.Offset
                size_bytes = $partition.Size
                filesystem = if ($volume) { $volume.FileSystem } else { $null }
                label = if ($volume) { $volume.FileSystemLabel } else { $null }
                mount_status = if ($volume) { "volume-detected" } else { "not-mounted" }
                size_remaining_bytes = if ($volume) { $volume.SizeRemaining } else { $null }
            }
        }
        $result = [pscustomobject] @{
            schema = "partition-lab.windows-image-inspection.v1"
            target = $resolvedImage
            mode = "windows-vhdx"
            disk = [pscustomobject] @{
                number = $disk.Number
                partition_style = $disk.PartitionStyle
                size_bytes = $disk.Size
                operational_status = $disk.OperationalStatus
                is_offline = $disk.IsOffline
                is_read_only = $disk.IsReadOnly
                partitions = $partitions
            }
        }
    }
    finally {
        Dismount-DiskImage -ImagePath $resolvedImage -ErrorAction SilentlyContinue
    }

    if ($Json) {
        $result | ConvertTo-Json -Depth 20
    }
    else {
        Write-Output "Target: $resolvedImage"
        Write-Output "Mode: Windows VHD/VHDX"
        Write-Output "Partition style: $($result.disk.partition_style)"
        foreach ($partition in $result.disk.partitions) {
            Write-Output ("  {0}: offset={1} size={2} fs={3} label={4}" -f $partition.number, $partition.offset_bytes, $partition.size_bytes, $partition.filesystem, $partition.label)
        }
    }
    exit 0
}

$argsForPython = @("--image", $resolvedImage)
if ($Json) {
    $argsForPython += "--json"
}
if ($AllowOutsideTestImages) {
    $argsForPython += "--allow-outside-test-images"
}
Invoke-PartitionLabPython "inspect_image.py" @argsForPython
