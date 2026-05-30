from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock

import httpx
import webview

from browser_launcher import open_system_browser
from desktop_lite_config import (
    BACKEND_BASE_URL,
    COMPACT_MIN_HEIGHT,
    COMPACT_MIN_WIDTH,
    COMPACT_SIZE,
    DEFAULT_BROWSER_CMD,
    EXPANDED_MIN_HEIGHT,
    EXPANDED_SIZE,
    NOTIFY_LOG_FILE,
    OVERLAY_HTML,
    PROJECT_ROOT,
    SNAP_MARGIN,
    STATE_FILE,
    TOOL_OPTIONS,
)

try:
    import gi

    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk
except Exception:  # pragma: no cover
    Gdk = None


@dataclass
class OverlayState:
    edge: str = "right"
    x: int | None = None
    y: int | None = None
    width: int = COMPACT_SIZE["width"]
    height: int = COMPACT_SIZE["height"]


class OverlayBridge:
    def __init__(self, backend_base_url: str) -> None:
        self._backend_base_url = backend_base_url.rstrip("/")
        self._browser_cmd = DEFAULT_BROWSER_CMD
        self._window: webview.Window | None = None
        self._state = self._load_state()
        self._drag_offset: tuple[int, int] | None = None
        self._record_process: subprocess.Popen | None = None
        self._record_file: Path | None = None
        self._record_started_at: float | None = None
        self._record_stderr_file: Path | None = None
        self._record_provider: str | None = None
        self._lock = Lock()
        self._notification_thread: threading.Thread | None = None
        self._notification_stop = threading.Event()
        self._pending_overlay_notification: dict | None = None
        self._log_notification("bridge init")

    def attach_window(self, window: webview.Window) -> None:
        self._window = window
        self._log_notification("attach window")
        self._start_notification_loop()

    def get_config(self) -> dict:
        return {
            "backendBaseUrl": self._backend_base_url,
            "mcpBaseUrl": "http://127.0.0.1:8001",
            "calendarUrl": f"{self._backend_base_url}/",
            "browserCmdConfigured": bool(self._browser_cmd),
            "toolOptions": TOOL_OPTIONS,
            "dragMode": "native",
            "nativeAudioCapture": self._pick_recorder_command()[0] is not None,
        }

    def get_pending_notification(self) -> dict | None:
        with self._lock:
            payload = self._pending_overlay_notification
            self._pending_overlay_notification = None
            return payload

    def _pick_recorder_command(self) -> tuple[list[str] | None, str | None]:
        parec = shutil.which("parec")
        if parec:
            return ([parec, "-d", "RDPSource", "--file-format=wav", "--rate=16000", "--channels=1"], "parec")

        pw_record = shutil.which("pw-record")
        if pw_record:
            return ([pw_record, "--rate", "16000", "--channels", "1"], "pw-record")

        return (None, None)

    def _start_notification_loop(self) -> None:
        if self._notification_thread and self._notification_thread.is_alive():
            return
        self._notification_stop.clear()
        self._notification_thread = threading.Thread(
            target=self._notification_loop,
            name="voice-calendar-notify",
            daemon=True,
        )
        self._notification_thread.start()
        self._log_notification("thread started")

    def stop(self) -> None:
        self._notification_stop.set()

    def _notification_loop(self) -> None:
        while not self._notification_stop.is_set():
            try:
                self._log_notification("tick")
                response = httpx.get(
                    f"{self._backend_base_url}/api/notifications/due",
                    params={"channel": "desktop-lite", "lookback_seconds": 600, "limit": 20},
                    timeout=5.0,
                )
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("items", []):
                    self._log_notification(f"due {json.dumps(item, ensure_ascii=False)}")
                    self._notify_reminder(item)
                    self._acknowledge_notification(item["delivery_id"])
            except Exception as exc:
                self._log_notification(f"poll error {exc}")
            self._notification_stop.wait(1.0)

    def _acknowledge_notification(self, delivery_id: str) -> None:
        try:
            httpx.post(
                f"{self._backend_base_url}/api/notifications/ack",
                json={"delivery_id": delivery_id, "channel": "desktop-lite"},
                timeout=5.0,
            )
            self._log_notification(f"ack {delivery_id}")
        except Exception:
            self._log_notification(f"ack failed {delivery_id}")
            return

    def _notify_reminder(self, item: dict) -> None:
        title = str(item.get("title") or "提醒")
        start_at = str(item.get("start_at") or "")
        body = title
        if start_at:
            try:
                when = datetime.fromisoformat(start_at).strftime("%m-%d %H:%M:%S")
                body = f"{when} {title}"
            except Exception:
                body = title
        description = str(item.get("description") or "").strip()
        if description:
            body = f"{body}\n{description}"

        with self._lock:
            self._pending_overlay_notification = {
                "title": "Voice Calendar 提醒",
                "body": body,
            }
        self._log_notification(f"overlay-queued {body}")

    def _log_notification(self, message: str) -> None:
        timestamp = datetime.now().isoformat()
        try:
            with NOTIFY_LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp} {message}\n")
        except Exception:
            return


    def call_mcp_tool(self, tool_name: str, arguments_payload: dict) -> dict:
        response = httpx.post(
            f"{self._backend_base_url}/api/mcp/tools/{tool_name}",
            json={"arguments": arguments_payload},
            timeout=30.0,
        )
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("detail") if isinstance(payload, dict) else None
            except Exception:
                detail = None
            raise RuntimeError(detail or f"MCP tool {tool_name} 调用失败（HTTP {response.status_code}）。")
        return response.json()["result"]

    def open_calendar(self) -> dict:
        return open_system_browser(f"{self._backend_base_url}/", self._browser_cmd)

    def start_voice_capture(self) -> dict:
        if self._record_process and self._record_process.poll() is None:
            return {"ok": True, "recording": True}

        command, provider = self._pick_recorder_command()
        if not command or not provider:
            return {"ok": False, "error": "系统未安装可用录音工具，无法启用原生录音。"}

        fd, tmp_path = tempfile.mkstemp(prefix="voice-overlay-", suffix=".wav")
        os.close(fd)
        err_fd, err_path = tempfile.mkstemp(prefix="voice-overlay-", suffix=".stderr.log")
        os.close(err_fd)
        file_path = Path(tmp_path)
        err_file_path = Path(err_path)
        err_handle = err_file_path.open("wb")
        process = subprocess.Popen(
            [*command, str(file_path)],
            stdout=subprocess.DEVNULL,
            stderr=err_handle,
        )
        err_handle.close()
        self._record_process = process
        self._record_file = file_path
        self._record_stderr_file = err_file_path
        self._record_started_at = time.monotonic()
        self._record_provider = provider
        return {"ok": True, "recording": True, "provider": provider}

    def stop_voice_capture(self) -> dict:
        process = self._record_process
        file_path = self._record_file
        err_file_path = self._record_stderr_file
        started = self._record_started_at
        provider = self._record_provider
        self._record_process = None
        self._record_file = None
        self._record_stderr_file = None
        self._record_started_at = None
        self._record_provider = None

        if process is None or file_path is None:
            return {"ok": False, "error": "当前没有进行中的录音。"}

        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()

        stderr_text = ""
        if err_file_path and err_file_path.exists():
            try:
                stderr_text = err_file_path.read_text(encoding="utf-8", errors="ignore").strip()
            finally:
                err_file_path.unlink(missing_ok=True)

        if not file_path.exists():
            detail = f" 详细信息：{stderr_text}" if stderr_text else ""
            return {"ok": False, "error": f"录音文件未生成。{detail}"}

        raw = file_path.read_bytes()
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass

        if len(raw) <= 1024:
            detail = f" 详细信息：{stderr_text}" if stderr_text else ""
            return {"ok": False, "error": f"未采集到有效音频数据。请检查系统输入设备。{detail}"}

        duration_ms = int((time.monotonic() - started) * 1000) if started else 0
        return {
            "ok": True,
            "audio_base64": base64.b64encode(raw).decode("ascii"),
            "content_type": "audio/wav",
            "filename": "voice-input.wav",
            "duration_ms": duration_ms,
            "provider": provider or "native-recorder",
        }

    def set_mode(
        self,
        mode: str,
        content_height: int | None = None,
        content_width: int | None = None,
    ) -> dict:
        if self._window is None:
            return {"ok": False}
        if mode == "expanded":
            target_height = EXPANDED_SIZE["height"]
            if content_height is not None:
                target_height = max(EXPANDED_MIN_HEIGHT, min(int(content_height), EXPANDED_SIZE["height"]))
            target = {"width": EXPANDED_SIZE["width"], "height": target_height}
        else:
            target_width = COMPACT_SIZE["width"]
            target_height = COMPACT_SIZE["height"]
            if content_width is not None:
                target_width = max(COMPACT_MIN_WIDTH, min(int(content_width), COMPACT_SIZE["width"]))
            if content_height is not None:
                target_height = max(COMPACT_MIN_HEIGHT, min(int(content_height), COMPACT_SIZE["height"]))
            target = {"width": target_width, "height": target_height}
        bounds = self._clamp_bounds(
            self._state.x or 0,
            self._state.y or 0,
            target["width"],
            target["height"],
        )
        with self._lock:
            self._state = OverlayState(
                edge=self._state.edge,
                x=bounds["x"],
                y=bounds["y"],
                width=target["width"],
                height=target["height"],
            )
            self._save_state()
        self._window.resize(bounds["width"], bounds["height"])
        self._window.move(bounds["x"], bounds["y"])
        return {"ok": True}

    def start_drag(self, screen_x: int, screen_y: int) -> dict:
        if self._state.x is None or self._state.y is None:
            return {"ok": False}
        self._drag_offset = (screen_x - self._state.x, screen_y - self._state.y)
        return {"ok": True}

    def move_drag(self, screen_x: int, screen_y: int) -> dict:
        if self._window is None or self._drag_offset is None:
            return {"ok": False}
        next_x = int(screen_x - self._drag_offset[0])
        next_y = int(screen_y - self._drag_offset[1])
        bounds = self._clamp_bounds(next_x, next_y, self._state.width, self._state.height)
        with self._lock:
            self._state.x = bounds["x"]
            self._state.y = bounds["y"]
        self._window.move(bounds["x"], bounds["y"])
        return {"ok": True}

    def end_drag(self) -> dict:
        if self._window is None:
            return {"ok": False}
        bounds = self._clamp_bounds(
            self._state.x or 0,
            self._state.y or 0,
            self._state.width,
            self._state.height,
        )
        with self._lock:
            self._state.edge = "left" if bounds["x"] < (self._screen_geometry()["width"] / 2) else "right"
            self._state.x = bounds["x"]
            self._state.y = bounds["y"]
            self._drag_offset = None
            self._save_state()
        self._window.move(bounds["x"], bounds["y"])
        return {"ok": True}

    def _load_state(self) -> OverlayState:
        if not STATE_FILE.exists():
            return self._default_state()
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return OverlayState(
                edge="left" if data.get("edge") == "left" else "right",
                x=data.get("x"),
                y=data.get("y"),
                width=COMPACT_SIZE["width"],
                height=COMPACT_SIZE["height"],
            )
        except Exception:
            return self._default_state()

    def _save_state(self) -> None:
        STATE_FILE.write_text(
            json.dumps(
                {
                    "edge": self._state.edge,
                    "x": self._state.x,
                    "y": self._state.y,
                    "width": self._state.width,
                    "height": self._state.height,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _default_state(self) -> OverlayState:
        screen = self._screen_geometry()
        return OverlayState(
            edge="right",
            x=screen["x"] + screen["width"] - COMPACT_SIZE["width"] - SNAP_MARGIN,
            y=screen["y"] + screen["height"] - COMPACT_SIZE["height"] - SNAP_MARGIN,
        )

    def _screen_geometry(self) -> dict:
        if Gdk is None:
            return {"x": 0, "y": 0, "width": 1440, "height": 900}
        display = Gdk.Display.get_default()
        if display is None:
            return {"x": 0, "y": 0, "width": 1440, "height": 900}
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geometry = monitor.get_geometry()
        return {"x": geometry.x, "y": geometry.y, "width": geometry.width, "height": geometry.height}

    def _clamp_bounds(self, x: int, y: int, width: int, height: int) -> dict:
        screen = self._screen_geometry()
        min_x = screen["x"] + SNAP_MARGIN
        max_x = screen["x"] + screen["width"] - width - SNAP_MARGIN
        min_y = screen["y"] + SNAP_MARGIN
        max_y = screen["y"] + screen["height"] - height - SNAP_MARGIN
        return {
            "x": max(min_x, min(x, max_x)),
            "y": max(min_y, min(y, max_y)),
            "width": width,
            "height": height,
        }

    def _snap_bounds(self, x: int | None, y: int | None, width: int, height: int, edge: str | None) -> dict:
        screen = self._screen_geometry()
        current_x = x if x is not None else (screen["x"] + screen["width"] - width - SNAP_MARGIN)
        current_y = y if y is not None else (screen["y"] + screen["height"] - height - SNAP_MARGIN)
        clamped = self._clamp_bounds(current_x, current_y, width, height)
        midpoint = screen["x"] + (screen["width"] / 2)
        snapped_edge = edge or ("left" if clamped["x"] + (width / 2) < midpoint else "right")
        snapped_x = screen["x"] + SNAP_MARGIN if snapped_edge == "left" else screen["x"] + screen["width"] - width - SNAP_MARGIN
        return {**clamped, "x": snapped_x, "edge": snapped_edge}


def launch_overlay(backend_base_url: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        http_port = int(sock.getsockname()[1])

    bridge = OverlayBridge(backend_base_url)
    window = webview.create_window(
        "Voice Calendar Bubble Lite",
        url=OVERLAY_HTML.as_uri(),
        js_api=bridge,
        width=COMPACT_SIZE["width"],
        height=COMPACT_SIZE["height"],
        min_size=(COMPACT_SIZE["width"], COMPACT_SIZE["height"]),
        x=bridge._state.x,
        y=bridge._state.y,
        frameless=True,
        easy_drag=False,
        resizable=True,
        on_top=True,
        transparent=True,
        text_select=True,
        focus=True,
        background_color="#000000",
        http_port=http_port,
    )
    bridge.attach_window(window)
    try:
        webview.start(
            gui="gtk",
            debug=False,
            http_server=True,
            http_port=http_port,
            private_mode=False,
        )
    finally:
        bridge.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lightweight desktop overlay for Voice Calendar.")
    parser.add_argument("--backend-base-url", default=BACKEND_BASE_URL)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--notify-test", action="store_true")
    return parser.parse_args()


def _relaunch_with_x11_if_wayland() -> None:
    # Wayland often blocks frameless floating window move; prefer XWayland for stable dragging.
    if os.environ.get("VC_FORCE_X11") == "1":
        return
    if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("GDK_BACKEND", "").lower() != "x11":
        env = os.environ.copy()
        env["GDK_BACKEND"] = "x11"
        env["VC_FORCE_X11"] = "1"
        subprocess.Popen([sys.executable, *sys.argv], env=env, cwd=str(PROJECT_ROOT))
        raise SystemExit(0)


def main() -> None:
    _relaunch_with_x11_if_wayland()
    args = parse_args()
    if args.notify_test:
        bridge = OverlayBridge(args.backend_base_url)
        bridge._notify_reminder(
            {
                "title": "桌面通知测试",
                "description": "如果你没看见这一条，说明系统通知层有问题。",
                "start_at": datetime.now().astimezone().isoformat(),
            }
        )
        print("notify-test sent")
        return
    if args.check:
        bridge = OverlayBridge(args.backend_base_url)
        print(json.dumps(bridge.get_config(), ensure_ascii=False))
        return
    launch_overlay(args.backend_base_url)


if __name__ == "__main__":
    main()
