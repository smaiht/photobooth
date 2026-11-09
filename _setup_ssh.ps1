# SSH for remote support: OpenSSH Server, key-only login for administrators.
# The keys come from https://github.com/smaiht.keys; run again to refresh them.
# Every step is idempotent, so the whole setup can be run any number of times.
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 may still offer TLS 1.0, which GitHub refuses.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$capability = 'OpenSSH.Server~~~~0.0.1.0'
if ((Get-WindowsCapability -Online -Name $capability).State -ne 'Installed') {
    Add-WindowsCapability -Online -Name $capability | Out-Null
}
Set-Service sshd -StartupType Automatic
Start-Service sshd  # the first start writes sshd_config

# Keys only: the kiosk user has an empty password, and passwords can be guessed.
$config = 'C:\ProgramData\ssh\sshd_config'
$text = Get-Content -Raw $config
if ($text -match '(?m)^#?\s*PasswordAuthentication\s+\w+') {
    $text = $text -replace '(?m)^#?\s*PasswordAuthentication\s+\w+', 'PasswordAuthentication no'
} else {
    $text = "PasswordAuthentication no`r`n" + $text  # top of the file: before any Match block
}
Set-Content -Encoding ascii -Path $config -Value $text

# SIDs instead of names: on a Russian Windows the groups are not called Administrators/SYSTEM.
$keys = 'C:\ProgramData\ssh\administrators_authorized_keys'
Invoke-RestMethod 'https://github.com/smaiht.keys' | Set-Content -Encoding ascii -Path $keys
icacls $keys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null

if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
        -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow | Out-Null
}
Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Enabled True -Profile Any

Restart-Service sshd
