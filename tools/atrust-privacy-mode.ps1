[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Start", "Stop", "Status")]
    [string]$Action,

    [switch]$PurgeLocalTelemetry
)

$ErrorActionPreference = "Stop"
$serviceName = "aTrustService"
$trayPath = "C:\Program Files (x86)\Sangfor\aTrust\aTrustTray\aTrustTray.exe"
$roaming = [Environment]::GetFolderPath("ApplicationData")
$aTrustData = Join-Path $roaming "Sangfor\aTrust"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Administrator {
    if (-not (Test-IsAdministrator)) {
        throw "Run this script from an elevated PowerShell session."
    }
}

function Show-Status {
    $service = Get-Service -Name $serviceName -ErrorAction Stop
    $processes = @(Get-Process -Name "aTrustAgent", "aTrustTray", "aTrustXtunnel" -ErrorAction SilentlyContinue)
    [PSCustomObject]@{
        ServiceStatus = $service.Status
        StartupType   = $service.StartType
        ProcessCount  = $processes.Count
        DataDirectory = $aTrustData
    } | Format-List
}

switch ($Action) {
    "Start" {
        Assert-Administrator
        if ($PSCmdlet.ShouldProcess($serviceName, "set Manual startup and start service")) {
            Set-Service -Name $serviceName -StartupType Manual
            Start-Service -Name $serviceName
        }
        if ((Test-Path -LiteralPath $trayPath) -and
            -not (Get-Process -Name "aTrustTray" -ErrorAction SilentlyContinue)) {
            Start-Process -FilePath $trayPath -ArgumentList "installedstart" -WindowStyle Hidden
        }
        Show-Status
    }

    "Stop" {
        Assert-Administrator
        if ($PSCmdlet.ShouldProcess("aTrust user processes", "stop tray and tunnel processes")) {
            Get-Process -Name "aTrustTray", "aTrustXtunnel" -ErrorAction SilentlyContinue |
                Stop-Process -Force
        }
        if ($PSCmdlet.ShouldProcess($serviceName, "stop service and keep Manual startup")) {
            Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
            Set-Service -Name $serviceName -StartupType Manual
        }

        if ($PurgeLocalTelemetry) {
            $purgeTargets = @(
                (Join-Path $aTrustData "logs"),
                (Join-Path $aTrustData "buryData"),
                (Join-Path $aTrustData "AppCache\Crashpad")
            )
            foreach ($target in $purgeTargets) {
                if ((Test-Path -LiteralPath $target) -and
                    $PSCmdlet.ShouldProcess($target, "purge local aTrust logs and telemetry cache")) {
                    Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue |
                        Remove-Item -Recurse -Force
                }
            }
        }
        Show-Status
    }

    "Status" {
        Show-Status
    }
}
