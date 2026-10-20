"""Idle-only controller diagnostics; no input actions, Tasker or resources."""

from copy import deepcopy
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
from maa.controller import AdbController, Win32Controller
from maa.define import MaaWin32InputMethodEnum, MaaWin32ScreencapMethodEnum
from maa.toolkit import Toolkit

from app.pg_init import resolve_manual_program_path


def supported_presets(interface, resource_config):
    allowed = resource_config.get("controller") if isinstance(resource_config, dict) else None
    if allowed is not None and not isinstance(allowed, list):
        return []
    controllers = interface.get("controller", []) if isinstance(interface, dict) else []
    if not isinstance(controllers, list):
        return []
    result = []
    for preset in controllers:
        if not isinstance(preset, dict) or not isinstance(preset.get("name"), str):
            continue
        if not preset["name"] or preset.get("type") not in ("Win32", "Adb"):
            continue
        if allowed is not None and preset["name"] not in allowed:
            continue
        if preset["type"] == "Win32" and not isinstance(preset.get("win32"), dict):
            continue
        result.append(deepcopy(preset))
    return result


def normalize_connection_preferences(value):
    value = value if isinstance(value, dict) else {}
    return {key: value.get(key, "").strip() if isinstance(value.get(key), str) else ""
            for key in ("adb_path", "address")}


def normalize_screen_preferences(value):
    value = value if isinstance(value, dict) else {}
    return {
        "mode": "continuous" if value.get("mode") == "continuous" else "single",
        "fps": value.get("fps") if type(value.get("fps")) is int and value["fps"] in (1, 2, 5, 10, 15, 30, 45, 60) else 2,
    }


def window_process_info(hwnd):
    """Query only, never start/stop a process or elevate permissions."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process = kernel32.OpenProcess(0x1000, False, pid.value)
    path = ""
    if process:
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
                path = buffer.value
        finally:
            kernel32.CloseHandle(process)
    return pid.value, path


@dataclass(frozen=True)
class ConnectionTarget:
    key: str
    label: str
    kind: str
    hwnd: int = 0
    device: object = None
    process_path: str = ""
    pid: int = 0


class MonitoringDisconnected(RuntimeError):
    """The selected capture connection has actually been lost."""


class PreviewNotReady(RuntimeError):
    """A runtime handoff is still initializing; it is safe to retry."""




class MonitoringService:
    def __init__(self, interface, resource_config, user_dir):
        self.presets = supported_presets(interface, resource_config)
        self.user_dir = Path(user_dir)
        self.controller = None
        self.connected_target = None
        self.targets = []
        self._discovered_preset = None
        self._discovered_adb_path = ""
        self._initialized = False
        self._user32 = None
        self._original_window_placement = None
        self._placement_hwnd = None

    def _window_api(self):
        if self._user32 is None:
            from app.runtime import create_user32
            self._user32 = create_user32()
        return self._user32

    @property
    def needs_cleanup(self):
        return self.controller is not None or self._original_window_placement is not None

    def ensure_preview_available(self, target_key):
        """Read-only check: idle preview must not unminimize a user's window."""
        target = next((t for t in self.targets if t.key == target_key), None)
        if target is None:
            raise MonitoringDisconnected("화면 대상이 변경되거나 종료되었습니다. 다시 연결하세요.")
        if target.kind != "Win32":
            return
        pid, path = window_process_info(target.hwnd)
        if not pid or pid != target.pid or (target.process_path and path != target.process_path):
            raise MonitoringDisconnected("대상 프로그램이 변경되거나 종료되었습니다. 다시 연결하세요.")
        if self._window_api().IsIconic(target.hwnd):
            raise PreviewNotReady("대상 창이 최소화되어 있습니다. 창 복구 후 화면 표시를 재개합니다.")

    def preset(self, name):
        for preset in self.presets:
            if preset["name"] == name:
                return preset
        raise ValueError("현재 리소스에 선언된 컨트롤러를 선택하세요.")

    def _init_toolkit(self):
        if not self._initialized:
            if not Toolkit.init_option(str(self.user_dir)):
                raise RuntimeError("연결 도구 초기화에 실패했습니다.")
            self._initialized = True

    def discover(self, name, preferences=None, program_settings=None):
        preset = self.preset(name)
        self.close()
        self.targets = []
        self._discovered_preset = None
        if preset["type"] == "Win32":
            config = preset["win32"]
            title = config.get("window_regex", "")
            class_name = config.get("class_regex", "")
            if not isinstance(title, str) or not isinstance(class_name, str) or not (title or class_name):
                raise ValueError("Win32 창 제목 또는 클래스 정규식이 필요합니다.")
            title_pattern = re.compile(title, re.IGNORECASE)
            class_pattern = re.compile(class_name, re.IGNORECASE)
            self._init_toolkit()
            for window in Toolkit.find_desktop_windows() or []:
                if not title_pattern.search(window.window_name or ""):
                    continue
                if not class_pattern.search(window.class_name or ""):
                    continue
                hwnd = getattr(window.hwnd, "value", window.hwnd)
                if not hwnd:
                    continue
                pid, path = window_process_info(hwnd)
                program = program_settings if isinstance(program_settings, dict) else {}
                manual_path = program.get("manual_path", "")
                if path and manual_path:
                    resolved = resolve_manual_program_path(manual_path)
                    if resolved is None or Path(path).resolve() != resolved:
                        continue
                detail = Path(path).name if path else "실행 파일 확인 권한 제한"
                self.targets.append(ConnectionTarget(
                    str(hwnd), f"{window.window_name} · {detail} · PID {pid}", "Win32",
                    hwnd=hwnd, process_path=path, pid=pid,
                ))
        else:
            preferences = normalize_connection_preferences(preferences)
            adb_path = preferences["adb_path"]
            if adb_path and not Path(adb_path).is_file():
                raise ValueError("ADB 실행 파일 경로를 확인하세요.")
            self._init_toolkit()
            self._discovered_adb_path = adb_path
            for device in Toolkit.find_adb_devices(adb_path or None) or []:
                self.targets.append(ConnectionTarget(
                    device.address, f"{device.name} · {device.address}", "Adb", device=device,
                ))
        self._discovered_preset = name
        return list(self.targets)

    def connect(self, name, target_key, preferences=None):
        preset = self.preset(name)
        preferences = normalize_connection_preferences(preferences)
        target = next((target for target in self.targets if target.key == target_key), None)
        if self._discovered_preset != name:
            target = None
        if preset["type"] == "Win32":
            if target is None or target.kind != "Win32":
                raise ValueError("먼저 실행 중인 프로그램을 탐색하고 선택하세요.")
            pid, path = window_process_info(target.hwnd)
            if not pid or pid != target.pid or (target.process_path and path != target.process_path):
                raise ValueError("대상 프로그램이 변경되거나 종료되었습니다. 다시 탐색하세요.")
            config = preset["win32"]
            methods = {
                "screencap_method": MaaWin32ScreencapMethodEnum[config.get("screencap", "Background")],
                # A supported, guard-free method; diagnostics never post input.
                # Null (0) logs Unknown input method in MaaFramework 5.12.3.
                "mouse_method": MaaWin32InputMethodEnum.PostMessage,
                "keyboard_method": MaaWin32InputMethodEnum.PostMessage,
            }
            factory = lambda: Win32Controller(hWnd=target.hwnd, **methods)
        else:
            if preferences["adb_path"] != self._discovered_adb_path:
                target = None
            if (preferences["address"] and self._discovered_preset == name
                    and preferences["adb_path"] == self._discovered_adb_path):
                target = next((t for t in self.targets if t.key == preferences["address"]), None)
            if target is not None and target.device is not None:
                device = target.device
                factory = lambda: AdbController(
                    adb_path=device.adb_path, address=device.address,
                    screencap_methods=device.screencap_methods,
                    input_methods=device.input_methods, config=device.config,
                )
            elif preferences["adb_path"] and preferences["address"]:
                if not Path(preferences["adb_path"]).is_file():
                    raise ValueError("ADB 실행 파일 경로를 확인하세요.")
                target = ConnectionTarget(preferences["address"], preferences["address"], "Adb")
                factory = lambda: AdbController(
                    adb_path=preferences["adb_path"], address=preferences["address"],
                )
            else:
                raise ValueError("ADB 기기를 선택하거나 실행 파일과 주소를 입력하세요.")
        self.close()
        self._init_toolkit()
        if target.kind == "Win32":
            from app.runtime import WindowPlacement
            placement = WindowPlacement()
            placement.length = ctypes.sizeof(WindowPlacement)
            if not self._window_api().GetWindowPlacement(target.hwnd, ctypes.byref(placement)):
                raise RuntimeError("사전 연결 창의 원래 상태를 저장하지 못했습니다.")
            self._original_window_placement = placement
            self._placement_hwnd = target.hwnd
        try:
            self.controller = factory()
            job = self.controller.post_connection().wait()
            if not job.succeeded or not self.controller.connected:
                raise RuntimeError("연결 실패: 프로그램 실행 상태 또는 ADB 주소/승인을 확인하세요.")
            self.connected_target = target
            return target
        except Exception:
            self.close()
            raise

    @staticmethod
    def validate_frame(image, *, copy=True):
        if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
            raise ValueError("캡처 이미지 형식이 올바르지 않습니다.")
        if image.ndim != 3 or image.shape[2] != 3 or not image.size:
            raise ValueError("캡처 이미지가 비어 있거나 BGR 형식이 아닙니다.")
        contiguous = np.ascontiguousarray(image)
        return contiguous.copy() if copy else contiguous


    def capture(self):
        if self.controller is None or not self.controller.connected:
            raise MonitoringDisconnected("캡처 연결이 해제되었습니다. 다시 연결 확인을 완료하세요.")
        if self.connected_target is not None and self.connected_target.kind == "Win32":
            self.ensure_preview_available(self.connected_target.key)
        job = self.controller.post_screencap().wait()
        if not job.succeeded:
            if not self.controller.connected:
                raise MonitoringDisconnected("캡처 중 연결이 해제되었습니다.")
            raise RuntimeError("스크린샷 캡처에 실패했습니다.")
        return self.validate_frame(job.get())

    def close(self):
        restore_placement = self._original_window_placement
        if self.controller is not None and restore_placement is not None:
            from app.runtime import GWL_EXSTYLE, LWA_ALPHA, WS_EX_LAYERED, WS_EX_TRANSPARENT
            api = self._window_api()
            # Diagnostics change only pseudo-minimize, not geometry. Do not undo
            # a user's later manual resize/restore/minimize or activate a normal window.
            style = int(api.GetWindowLongPtrW(self._placement_hwnd, GWL_EXSTYLE))
            color_key, alpha, flags = wintypes.DWORD(), ctypes.c_ubyte(255), wintypes.DWORD()
            mask = WS_EX_LAYERED | WS_EX_TRANSPARENT
            pseudo = (style & mask == mask and api.GetLayeredWindowAttributes(
                self._placement_hwnd, ctypes.byref(color_key), ctypes.byref(alpha), ctypes.byref(flags)
            ) and flags.value & LWA_ALPHA and alpha.value == 0)
            if not pseudo:
                restore_placement = None
        if self.controller is not None and self.controller.connected:
            if not self.controller.post_inactive().wait().succeeded:
                raise RuntimeError("사전 연결 해제에 실패했습니다. 다시 해제한 후 실행하세요.")
        self.controller = None
        self.connected_target = None
        self._original_window_placement = restore_placement
        if self._original_window_placement is not None:
            api = self._window_api()
            from app.runtime import SW_SHOWNOACTIVATE, SW_SHOWMINNOACTIVE, WindowPlacement
            restore = WindowPlacement.from_buffer_copy(self._original_window_placement)
            if restore.show_cmd == 1:
                restore.show_cmd = SW_SHOWNOACTIVATE
            elif restore.show_cmd == 2:
                restore.show_cmd = SW_SHOWMINNOACTIVE
            if api.IsWindow(self._placement_hwnd) and not api.SetWindowPlacement(
                self._placement_hwnd, ctypes.byref(restore)
            ):
                raise RuntimeError("사전 연결 창의 원래 상태를 복원하지 못했습니다. 다시 해제하세요.")
            self._original_window_placement = None
            self._placement_hwnd = None
