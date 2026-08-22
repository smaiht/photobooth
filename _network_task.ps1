$ErrorActionPreference = 'Stop'
$requestKey = $null
$result = [ordered]@{
    id = ''
    ok = $false
    enabled = $false
    error = ''
}

try {
    $userSid = (New-Object System.Security.Principal.NTAccount('Photobooth')).Translate(
        [System.Security.Principal.SecurityIdentifier]
    ).Value
    $requestKey = "Registry::HKEY_USERS\$userSid\Software\Photobooth"
    $request = Get-ItemPropertyValue -LiteralPath $requestKey `
        -Name NetworkRequest | ConvertFrom-Json
    $result.id = [string]$request.id
    $name = [string]$request.name

    if ([string]::IsNullOrWhiteSpace($result.id)) { throw 'Request ID is empty' }
    if ([string]::IsNullOrWhiteSpace($name)) { throw 'Adapter name is empty' }
    if ($request.enabled -isnot [bool]) { throw 'Adapter state must be boolean' }

    $desired = $request.enabled
    $target = Get-NetAdapter | Where-Object Name -EQ $name | Select-Object -First 1
    if ($null -eq $target) { throw "Adapter not found: $name" }

    if (($target.AdminStatus -eq 'Up') -ne $desired) {
        if ($desired) {
            Enable-NetAdapter -Name $target.Name -Confirm:$false
        } else {
            Disable-NetAdapter -Name $target.Name -Confirm:$false
        }
    }

    $target = Get-NetAdapter | Where-Object Name -EQ $name | Select-Object -First 1
    $actual = $target.AdminStatus -eq 'Up'
    if ($actual -ne $desired) { throw "Windows did not change adapter state: $name" }
    $result.enabled = $actual
    $result.ok = $true
} catch {
    $result.error = $_.Exception.Message
}

if ($null -ne $requestKey -and (Test-Path -LiteralPath $requestKey)) {
    $json = $result | ConvertTo-Json -Compress
    New-ItemProperty -LiteralPath $requestKey -Name NetworkResult `
        -Value $json -PropertyType String -Force | Out-Null
}

if (-not $result.ok) { exit 1 }
