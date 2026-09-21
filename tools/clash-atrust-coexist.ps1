param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('Enable', 'Disable', 'Status')]
    [string]$Action,

    [string]$ClashProxy = '127.0.0.1:7890'
)

$ErrorActionPreference = 'Stop'

$internetSettings = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$backupPath = Join-Path $PSScriptRoot '..\artifacts\clash-atrust-proxy-backup.json'
$requiredBypass = @(
    '<local>',
    'localhost',
    '127.*',
    '[::1]',
    'swust.edu.cn',
    '*.swust.edu.cn'
)

function Get-RegistryValueState {
    param([string]$Name)

    $key = Get-Item -LiteralPath $internetSettings
    $valueNames = $key.GetValueNames()
    if ($valueNames -contains $Name) {
        return [ordered]@{
            Exists = $true
            Value  = $key.GetValue($Name, $null, 'DoNotExpandEnvironmentNames')
            Kind   = $key.GetValueKind($Name).ToString()
        }
    }

    return [ordered]@{
        Exists = $false
        Value  = $null
        Kind   = $null
    }
}

function Get-ProxyState {
    $proxy = Get-ItemProperty -LiteralPath $internetSettings
    return [ordered]@{
        ProxyEnable  = [int]$proxy.ProxyEnable
        ProxyServer  = [string]$proxy.ProxyServer
        ProxyOverride = [string]$proxy.ProxyOverride
        AutoConfigURL = [string]$proxy.AutoConfigURL
    }
}

function Notify-ProxyChanged {
    if (-not ('WinInet.NativeMethods' -as [type])) {
        Add-Type @'
namespace WinInet {
    using System.Runtime.InteropServices;
    public static class NativeMethods {
        [DllImport("wininet.dll", SetLastError = true)]
        public static extern bool InternetSetOption(System.IntPtr hInternet, int option, System.IntPtr buffer, int length);
    }
}
'@
    }

    [void][WinInet.NativeMethods]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0)
    [void][WinInet.NativeMethods]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0)
}

function Test-ClashProxy {
    $parts = $ClashProxy.Split(':')
    if ($parts.Count -ne 2) {
        throw "ClashProxy must use the host:port format. Current value: $ClashProxy"
    }

    $port = 0
    if (-not [int]::TryParse($parts[1], [ref]$port)) {
        throw "Invalid ClashProxy port: $ClashProxy"
    }

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.ConnectAsync($parts[0], $port)
        if (-not $connect.Wait(1500) -or -not $client.Connected) {
            throw "Clash is not listening on $ClashProxy. Start Clash first."
        }
    }
    finally {
        $client.Dispose()
    }
}

function Get-TunRouteStatus {
    $routes = route.exe print 198.18.0.0 2>$null
    return (($routes | Out-String) -match '198\.18\.0\.')
}

function Show-Status {
    $state = Get-ProxyState
    [pscustomobject]@{
        ClashProxyEnabled = ($state.ProxyEnable -eq 1 -and $state.ProxyServer -eq $ClashProxy)
        ProxyEnable       = $state.ProxyEnable
        ProxyServer       = $state.ProxyServer
        ProxyOverride     = $state.ProxyOverride
        ClashTunDetected  = Get-TunRouteStatus
        BackupExists      = Test-Path -LiteralPath $backupPath
    } | Format-List
}

switch ($Action) {
    'Enable' {
        Test-ClashProxy

        $backupDir = Split-Path -Parent $backupPath
        if (-not (Test-Path -LiteralPath $backupDir)) {
            New-Item -ItemType Directory -Path $backupDir | Out-Null
        }

        if (-not (Test-Path -LiteralPath $backupPath)) {
            $backup = [ordered]@{
                Version       = 1
                CreatedAt     = (Get-Date).ToString('o')
                ProxyEnable   = Get-RegistryValueState 'ProxyEnable'
                ProxyServer   = Get-RegistryValueState 'ProxyServer'
                ProxyOverride = Get-RegistryValueState 'ProxyOverride'
                AutoConfigURL = Get-RegistryValueState 'AutoConfigURL'
            }
            $backup | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $backupPath -Encoding UTF8
        }

        $current = Get-ProxyState
        $bypass = @()
        if ($current.ProxyOverride) {
            $bypass += $current.ProxyOverride.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries)
        }
        $bypass += $requiredBypass
        $bypass = $bypass | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique

        Set-ItemProperty -LiteralPath $internetSettings -Name ProxyServer -Type String -Value $ClashProxy
        Set-ItemProperty -LiteralPath $internetSettings -Name ProxyOverride -Type String -Value ($bypass -join ';')
        Set-ItemProperty -LiteralPath $internetSettings -Name ProxyEnable -Type DWord -Value 1
        Notify-ProxyChanged

        Write-Host 'Clash system proxy is enabled. SWUST and localhost bypass Clash.' -ForegroundColor Green
        if (Get-TunRouteStatus) {
            Write-Warning 'Clash TUN is still detected. Turn off TUN Mode on the Clash for Windows General page; the system proxy is already handling ordinary traffic.'
        }
        Show-Status
    }

    'Disable' {
        if (-not (Test-Path -LiteralPath $backupPath)) {
            throw "Proxy settings backup not found: $backupPath"
        }

        $backup = Get-Content -LiteralPath $backupPath -Raw | ConvertFrom-Json
        foreach ($name in @('ProxyEnable', 'ProxyServer', 'ProxyOverride', 'AutoConfigURL')) {
            $saved = $backup.$name
            if ($saved.Exists) {
                $kind = switch ($saved.Kind) {
                    'DWord' { 'DWord' }
                    'QWord' { 'QWord' }
                    'ExpandString' { 'ExpandString' }
                    'MultiString' { 'MultiString' }
                    'Binary' { 'Binary' }
                    default { 'String' }
                }
                Set-ItemProperty -LiteralPath $internetSettings -Name $name -Type $kind -Value $saved.Value
            }
            else {
                Remove-ItemProperty -LiteralPath $internetSettings -Name $name -ErrorAction SilentlyContinue
            }
        }
        Notify-ProxyChanged

        Write-Host 'The previous Windows proxy settings have been restored.' -ForegroundColor Green
        Show-Status
    }

    'Status' {
        Show-Status
    }
}
