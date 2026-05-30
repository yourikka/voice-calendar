from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import webbrowser
from pathlib import Path

from desktop_lite_config import WSL_EDGE_CANDIDATES


def open_system_browser(url: str, browser_cmd: str = "") -> dict:
    launch_attempts: list[str] = []

    if browser_cmd:
        command = _command_from_template(browser_cmd, url)
        if command:
            ok, detail = run_browser_command(command)
            launch_attempts.append(f"{' '.join(command)} -> {detail}")
            if ok:
                return {"ok": True, "target": command[0], "url": url}

    browser_env = os.getenv("BROWSER", "").strip()
    if browser_env:
        for item in browser_env.split(os.pathsep):
            command = _command_from_template(item.strip(), url)
            if not command:
                continue
            ok, detail = run_browser_command(command)
            launch_attempts.append(f"{' '.join(command)} -> {detail}")
            if ok:
                return {"ok": True, "target": command[0], "url": url}

    for binary in (
        "microsoft-edge",
        "microsoft-edge-stable",
        "microsoft-edge-beta",
        "microsoft-edge-dev",
    ):
        if shutil.which(binary) is None:
            continue
        command = [binary, url]
        ok, detail = run_browser_command(command)
        launch_attempts.append(f"{' '.join(command)} -> {detail}")
        if ok:
            return {"ok": True, "target": binary, "url": url}

    if "microsoft-standard-WSL" in os.uname().release:
        for edge_path in WSL_EDGE_CANDIDATES:
            if not Path(edge_path).exists():
                continue
            command = [edge_path, url]
            ok, detail = run_browser_command(command)
            launch_attempts.append(f"{' '.join(command)} -> {detail}")
            if ok:
                return {"ok": True, "target": edge_path, "url": url}

    for command in (["gio", "open", url], ["xdg-open", url], ["sensible-browser", url]):
        if shutil.which(command[0]) is None:
            continue
        ok, detail = run_browser_command(command)
        launch_attempts.append(f"{' '.join(command)} -> {detail}")
        if ok:
            return {"ok": True, "target": command[0], "url": url}

    try:
        opened = webbrowser.open(url)
        launch_attempts.append(f"webbrowser.open -> {opened}")
        if opened:
            return {"ok": True, "target": "webbrowser", "url": url}
    except Exception as exc:
        launch_attempts.append(f"webbrowser.open -> {exc}")

    attempts = "; ".join(launch_attempts) if launch_attempts else "none"
    hint = (
        "请先安装浏览器，或设置 VOICE_CALENDAR_BROWSER_CMD，例如 "
        "VOICE_CALENDAR_BROWSER_CMD='microsoft-edge %s'。"
    )
    return {
        "ok": False,
        "target": "system-browser",
        "url": url,
        "error": f"无法打开系统浏览器。{hint} 尝试结果: {attempts}",
    }


def _command_from_template(template: str, url: str) -> list[str]:
    tokens = shlex.split(template)
    if not tokens:
        return []
    command = [token.replace("%s", url) for token in tokens]
    if not any("%s" in token for token in tokens):
        command.append(url)
    return command


def run_browser_command(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,
            check=False,
        )
    except Exception as exc:
        return False, f"exception: {exc}"

    if completed.returncode == 0:
        return True, "ok"
    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    detail = stderr or stdout or "failed"
    return False, f"rc={completed.returncode} {detail}"
