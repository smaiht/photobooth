$ErrorActionPreference = 'Stop'

$taskName = 'PhotoboothResetCanonR8'
$kioskUser = 'Photobooth'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Camera reset task setup must run as Administrator.'
}

$kioskSid = (New-Object Security.Principal.NTAccount($kioskUser)).Translate(
    [Security.Principal.SecurityIdentifier]
).Value

# Keep the privileged action inside Task Scheduler instead of a writable file.
# It can only select the USB parent (or PTP interface fallback) of Canon EOS R8.
$resetSource = @'
$ErrorActionPreference = 'Stop'
$devices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object {
    $_.InstanceId -like 'USB\VID_04A9&PID_330C\*'
})
if ($devices.Count -eq 0) {
    $devices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object {
        $_.InstanceId -like 'USB\VID_04A9&PID_330C&MI_00\*'
    })
}
if ($devices.Count -eq 0) {
    exit 1167
}
$instanceId = $devices[0].InstanceId
& "$env:SystemRoot\System32\pnputil.exe" /restart-device $instanceId
exit $LASTEXITCODE
'@

$encodedReset = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($resetSource)
)
$powershellPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$action = New-ScheduledTaskAction `
    -Execute $powershellPath `
    -Argument "-NoLogo -NoProfile -NonInteractive -EncodedCommand $encodedReset"
$taskPrincipal = New-ScheduledTaskPrincipal `
    -UserId 'SYSTEM' `
    -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$definition = New-ScheduledTask `
    -Action $action `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Description 'Restart only the Canon EOS R8 USB device for Photobooth recovery.'
Register-ScheduledTask -TaskName $taskName -InputObject $definition -Force | Out-Null

# SYSTEM and Administrators retain full control. The kiosk user receives only
# generic read/execute, enough to run this immutable task but not to edit it.
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$registeredTask = $scheduler.GetFolder('\').GetTask($taskName)
$taskSddl = "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;$kioskSid)"
$registeredTask.SetSecurityDescriptor($taskSddl, 0)
$installedSddl = $registeredTask.GetSecurityDescriptor(4)
if ($installedSddl -notlike "*$kioskSid*") {
    throw 'Camera reset task did not retain the kiosk execute permission.'
}

Write-Host "[OK] Canon R8 recovery task installed: $taskName"
