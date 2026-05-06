param(
    [string] $HostName = "127.0.0.1",
    [int] $Port = 8765,
    [switch] $Open
)

. "$PSScriptRoot/partitionlab-common.ps1"

$arguments = @("--host", $HostName, "--port", [string] $Port)
if ($Open) {
    $arguments += "--open"
}

Invoke-PartitionLabPython "lab_ui.py" @arguments
