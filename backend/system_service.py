"""Small Windows helpers used by the local service menu."""

import json
import logging
import subprocess
import sys

log = logging.getLogger(__name__)

SYSTEM_ACTIONS = {"keyboard", "lock", "logoff", "taskmgr"}


def _powershell_string(value: str) -> str:
    """Quote one literal PowerShell string."""
    return "'" + value.replace("'", "''") + "'"


def _run_powershell(script: str) -> str:
    """Run PowerShell without a console and raise its real error."""
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
                "$ErrorActionPreference = 'Stop'\n" + script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("PowerShell не ответил за 8 секунд") from exc
    except OSError as exc:
        raise RuntimeError(f"Не удалось запустить PowerShell: {exc}") from exc

    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        log.warning("PowerShell failed (%s): %s", proc.returncode, detail)
        first_line = next(
            (line.strip() for line in detail.splitlines() if line.strip()),
            f"PowerShell завершился с кодом {proc.returncode}",
        )
        raise RuntimeError(first_line)
    return proc.stdout.strip()


def _toggle_touch_keyboard() -> None:
    """Invoke the same touch-keyboard toggle used by the taskbar button."""
    _run_powershell(r"""
    Add-Type -TypeDefinition @'
    using System;
    using System.Runtime.InteropServices;

    [ComImport, Guid("4CE576FA-83DC-4F88-951C-9D0782B4E376")]
    internal class UIHostNoLaunch { }

    [ComImport, Guid("37C994E7-432B-4834-A2F7-DCE1F13B834B")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface ITipInvocation
    {
        void Toggle(IntPtr hwnd);
    }

    public static class TouchKeyboard
    {
        [DllImport("user32.dll")]
        private static extern IntPtr GetDesktopWindow();

        public static void Toggle()
        {
            ITipInvocation keyboard = (ITipInvocation)new UIHostNoLaunch();
            try { keyboard.Toggle(GetDesktopWindow()); }
            finally { Marshal.ReleaseComObject(keyboard); }
        }
    }
'@
    [TouchKeyboard]::Toggle()
    """)


def launch_system_action(action: str) -> dict:
    """Launch a small allowlist of Windows system actions."""
    if action not in SYSTEM_ACTIONS:
        return {"ok": False, "error": f"Неизвестное действие: {action}"}
    log.info("System action requested: %s", action)
    if sys.platform != "win32":
        return {"ok": True, "action": action, "mock": True}

    try:
        if action == "keyboard":
            _toggle_touch_keyboard()
            return {"ok": True, "action": action}

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        commands = {
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "logoff": ["shutdown.exe", "/l"],
            "taskmgr": ["taskmgr.exe"],
        }
        subprocess.Popen(commands[action], startupinfo=startupinfo)
        return {"ok": True, "action": action}
    except (OSError, RuntimeError) as exc:
        log.exception("Failed to launch action %s", action)
        return {"ok": False, "error": str(exc)}


def list_network_adapters() -> dict:
    """Return every adapter normally shown by Get-NetAdapter."""
    if sys.platform != "win32":
        return {
            "ok": True,
            "adapters": [
                {"name": "4G", "description": "Mock 4G", "enabled": True},
                {"name": "Wi-Fi", "description": "Mock Wi-Fi", "enabled": True},
            ],
            "mock": True,
        }

    script = """
    $adapters = @(Get-NetAdapter | Sort-Object Name | ForEach-Object {
        [PSCustomObject]@{
            name = $_.Name
            description = $_.InterfaceDescription
            enabled = $_.AdminStatus -eq 'Up'
        }
    })
    [PSCustomObject]@{ adapters = $adapters } | ConvertTo-Json -Depth 3 -Compress
    """
    try:
        result = json.loads(_run_powershell(script))
        result["ok"] = True
        return result
    except (RuntimeError, json.JSONDecodeError, TypeError) as exc:
        log.warning("Could not read network adapter status: %s", exc)
        return {"ok": False, "error": str(exc)}


def set_adapter(name: str, enabled: bool) -> dict:
    """Idempotently enable or disable one exactly named adapter."""
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "Имя адаптера не указано"}
    if type(enabled) is not bool:
        return {"ok": False, "error": "enabled должен быть true или false"}

    log.info("Set adapter %s enabled=%s", name, enabled)
    if sys.platform != "win32":
        return {
            "ok": True,
            "name": name,
            "enabled": enabled,
            "mock": True,
        }

    desired = "$true" if enabled else "$false"
    command = "Enable-NetAdapter" if enabled else "Disable-NetAdapter"
    script = f"""
    $name = {_powershell_string(name)}
    $desired = {desired}
    $target = Get-NetAdapter | Where-Object {{ $_.Name -eq $name }} | Select-Object -First 1
    if ($null -eq $target) {{ throw "Адаптер не найден: $name" }}
    $current = $target.AdminStatus -eq 'Up'
    if ($current -ne $desired) {{
        {command} -Name $target.Name -Confirm:$false
    }}
    $target = Get-NetAdapter | Where-Object {{ $_.Name -eq $name }} | Select-Object -First 1
    $actual = $target.AdminStatus -eq 'Up'
    if ($actual -ne $desired) {{ throw "Windows не изменила состояние адаптера: $name" }}
    [PSCustomObject]@{{ name = $target.Name; enabled = $actual }} | ConvertTo-Json -Compress
    """
    try:
        result = json.loads(_run_powershell(script))
        result["ok"] = True
        return result
    except (RuntimeError, json.JSONDecodeError, TypeError) as exc:
        log.warning("Could not set adapter %s: %s", name, exc)
        return {"ok": False, "name": name, "error": str(exc)}
