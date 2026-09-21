[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Start", "Stop")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$captureDir = Join-Path (Split-Path $PSScriptRoot -Parent) "artifacts"
$etlPath = Join-Path $captureDir "login-network.etl"
$pcapPath = Join-Path $captureDir "login-network.pcapng"
$diagnosticPath = Join-Path $captureDir "login-network-capture.log"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell session."
}

if (-not (Test-Path -LiteralPath $captureDir)) {
    New-Item -ItemType Directory -Path $captureDir | Out-Null
}

try {
    if ($Action -eq "Start") {
        # Capture only truncated TLS packets addressed to aTrust's synthetic-IP range.
        # Payload is limited to 128 bytes so application data is not retained.
        $messages = @()
        $ErrorActionPreference = "Continue"
        $messages += (& pktmon stop 2>&1 | Out-String)
        $ErrorActionPreference = "Stop"
        $messages += (& pktmon filter remove 2>&1 | Out-String)
        $messages += (& pktmon filter add AntiSWUSTLogin -i 198.18.0.0/16 -t TCP -p 443 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "pktmon filter add failed" }
        $messages += (& pktmon start --capture --pkt-size 128 --file-name $etlPath 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "pktmon start failed" }
        $messages | Set-Content -LiteralPath $diagnosticPath -Encoding utf8
        Write-Output "Capture started: $etlPath"
        exit 0
    }

    $messages = @()
    $messages += (& pktmon stop 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "pktmon stop failed" }
    $messages += (& pktmon etl2pcap $etlPath --out $pcapPath 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "pktmon conversion failed" }
    $messages += (& pktmon filter remove 2>&1 | Out-String)
    $messages | Set-Content -LiteralPath $diagnosticPath -Encoding utf8
    Write-Output "Capture stopped: $pcapPath"
} catch {
    ($_ | Out-String) | Set-Content -LiteralPath $diagnosticPath -Encoding utf8
    throw
}
