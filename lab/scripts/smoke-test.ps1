. "$PSScriptRoot/partitionlab-common.ps1"

$root = Get-PartitionLabProjectRoot
$python = Get-PartitionLabPython

function Invoke-SmokePython {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Script,

        [string[]] $Arguments = @(),

        [switch] $ExpectFailure
    )

    $scriptPath = Join-Path $PSScriptRoot $Script
    if ($python -eq "py") {
        & py -3 $scriptPath @Arguments *> $null
    }
    else {
        & $python $scriptPath @Arguments *> $null
    }
    $code = $LASTEXITCODE
    if ($ExpectFailure) {
        if ($code -eq 0) {
            throw "Expected failure but command succeeded: $Script $Arguments"
        }
    }
    elseif ($code -ne 0) {
        throw "Smoke command failed: $Script $Arguments"
    }
}

Invoke-SmokePython "inspect_layout.py" @((Join-Path $root "fixtures/normal-c-e-layout.json"), "--json")
Invoke-SmokePython "plan_operation.py" @("--layout", (Join-Path $root "fixtures/normal-c-e-layout.json"), "--increase-c", "40G", "--json")
Invoke-SmokePython "verify_layout.py" @("--before", (Join-Path $root "fixtures/normal-c-e-layout.json"), "--increase-c", "40G", "--json")
Invoke-SmokePython "plan_operation.py" @("--layout", (Join-Path $root "fixtures/e-has-insufficient-free-space.json"), "--increase-c", "40G", "--json") -ExpectFailure
Invoke-SmokePython "verify_layout.py" @("--before", (Join-Path $root "fixtures/dirty-filesystem-placeholder.json"), "--increase-c", "40G", "--json") -ExpectFailure

Write-Output "smoke tests passed"
