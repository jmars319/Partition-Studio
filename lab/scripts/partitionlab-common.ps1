Set-StrictMode -Version Latest

function Get-PartitionLabProjectRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Get-PartitionLabPython {
    $candidates = @("py", "python", "python3")
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return $candidate
        }
    }
    throw "Python was not found. Install Python 3 and make sure 'py' or 'python' is on PATH."
}

function Invoke-PartitionLabPython {
    param(
        [Parameter(Mandatory = $true)]
        [string] $ScriptName,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )

    $python = Get-PartitionLabPython
    $scriptPath = Join-Path $PSScriptRoot $ScriptName
    if ($python -eq "py") {
        & py -3 $scriptPath @Arguments
    }
    else {
        & $python $scriptPath @Arguments
    }
    exit $LASTEXITCODE
}

function ConvertTo-PartitionLabBytes {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Value
    )

    if ($Value -notmatch '^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)\s*$') {
        throw "Invalid size: $Value"
    }

    $number = [double] $Matches[1]
    $unit = $Matches[2].ToUpperInvariant()
    $multipliers = @{
        "" = 1L
        "B" = 1L
        "K" = 1KB
        "KB" = 1KB
        "KI" = 1KB
        "KIB" = 1KB
        "M" = 1MB
        "MB" = 1MB
        "MI" = 1MB
        "MIB" = 1MB
        "G" = 1GB
        "GB" = 1GB
        "GI" = 1GB
        "GIB" = 1GB
        "T" = 1TB
        "TB" = 1TB
        "TI" = 1TB
        "TIB" = 1TB
    }

    if (-not $multipliers.ContainsKey($unit)) {
        throw "Unsupported size unit: $Value"
    }

    $bytes = [int64] [Math]::Round($number * [double] $multipliers[$unit])
    if ($bytes -le 0) {
        throw "Size must be positive: $Value"
    }
    return $bytes
}

function ConvertTo-PartitionLabMiB {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Value
    )

    $bytes = ConvertTo-PartitionLabBytes $Value
    if (($bytes % 1MB) -ne 0) {
        throw "Size must be a whole MiB: $Value"
    }
    return [int64] ($bytes / 1MB)
}

function Resolve-PartitionLabPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-PartitionLabPathUnderTestImages {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    $root = Get-PartitionLabProjectRoot
    $testImages = Resolve-PartitionLabPath (Join-Path $root "test-images")
    $resolved = Resolve-PartitionLabPath $Path
    $prefix = $testImages.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path must be under $testImages"
    }
    return $resolved
}

function Test-PartitionLabAdministrator {
    if (-not (Test-PartitionLabIsWindows)) {
        return $false
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-PartitionLabIsWindows {
    $variable = Get-Variable -Name IsWindows -ErrorAction SilentlyContinue
    if ($null -ne $variable) {
        return [bool] $variable.Value
    }
    return $env:OS -eq "Windows_NT"
}

function Get-PartitionLabFreeDriveLetters {
    param(
        [int] $Count = 2
    )

    $letters = @()
    foreach ($letter in @("P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z")) {
        if (-not (Test-Path "${letter}:\")) {
            $letters += $letter
        }
        if ($letters.Count -ge $Count) {
            return $letters
        }
    }
    throw "Could not find $Count free drive letters."
}

function New-PartitionLabLogFile {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Prefix
    )

    $root = Get-PartitionLabProjectRoot
    $logs = Join-Path $root "logs"
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    return Join-Path $logs "$Prefix`_$timestamp.log"
}

function Write-PartitionLabLog {
    param(
        [Parameter(Mandatory = $true)]
        [string] $LogFile,

        [Parameter(Mandatory = $true)]
        [string] $Message
    )

    Write-Output $Message
    Add-Content -LiteralPath $LogFile -Value $Message
}

function Invoke-PartitionLabDiskPart {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Commands,

        [Parameter(Mandatory = $true)]
        [string] $LogFile,

        [switch] $DryRun
    )

    Write-PartitionLabLog $LogFile "+ diskpart"
    foreach ($command in $Commands) {
        Write-PartitionLabLog $LogFile "  $command"
    }

    if ($DryRun) {
        return
    }

    $scriptFile = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $scriptFile -Value ($Commands -join [Environment]::NewLine) -Encoding ASCII
        $output = & diskpart /s $scriptFile 2>&1
        foreach ($line in $output) {
            Write-Output $line
            Add-Content -LiteralPath $LogFile -Value $line
        }
        if ($LASTEXITCODE -ne 0) {
            throw "diskpart failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Remove-Item -LiteralPath $scriptFile -Force -ErrorAction SilentlyContinue
    }
}
