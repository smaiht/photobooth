$exePath = $args[0]
$sid = (New-Object System.Security.Principal.NTAccount('Photobooth')).Translate([System.Security.Principal.SecurityIdentifier]).Value
$hivePath = "C:\Users\Photobooth\NTUSER.DAT"
$loaded = $false

if (!(Test-Path "Registry::HKU\$sid")) {
    if (Test-Path $hivePath) {
        reg load "HKU\$sid" $hivePath 2>$null
        $loaded = $true
    } else {
        Write-Host "[WARN] User profile not created yet. Log in as Photobooth once, then re-run setup."
        exit 1
    }
}

reg add "HKU\$sid\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d $exePath /f
if ($loaded) { reg unload "HKU\$sid" 2>$null }
Write-Host "[OK] Shell set"
