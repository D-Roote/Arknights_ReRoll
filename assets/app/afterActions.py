"""Completion preferences and narrowly scoped Windows requests (no Maa SDK calls)."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys


SYSTEM_ACTIONS = {
    "lock": "화면 잠금", "sleep": "절전", "hibernate": "최대 절전", "shutdown": "시스템 종료",
}


def normalize_after_actions(value):
    value = value if isinstance(value, dict) else {}
    system = value.get("system_action")
    return {
        "close_program": value.get("close_program") is True,
        "close_app": value.get("close_app") is True or value.get("close_emulator") is True,
        "close_emulator": value.get("close_emulator") is True,
        "close_maa": value.get("close_maa") is True,
        "system_action": system if isinstance(system, str) and system in SYSTEM_ACTIONS else "",
    }


class AfterActionPreferences:
    def __init__(self, saved=None):
        self.saved = normalize_after_actions(saved)
        self.current = dict(self.saved)
        self.once = False

    def set_once(self, checked):
        self.once = bool(checked)
        if not self.once:
            self.saved = dict(self.current)

    def update(self, key, value):
        self.current = normalize_after_actions({**self.current, key: value})
        if not self.once:
            self.saved = dict(self.current)

    def clear(self):
        self.once = False
        self.current = normalize_after_actions(None)
        self.saved = dict(self.current)

    def consume(self):
        if self.once:
            self.current = dict(self.saved)
            self.once = False

    def for_controller(self, controller_type="Win32"):
        actions = dict(self.current)
        if controller_type == "Adb":
            actions["close_program"] = False
        else:
            actions["close_app"] = False
            actions["close_emulator"] = False
        return actions

    def description(self, controller_type="Win32"):
        actions = self.for_controller(controller_type)
        parts = []
        if actions["close_program"]:
            parts.append("대상 프로그램 종료")
        if actions["close_app"]:
            parts.append("앱 종료")
        if actions["close_emulator"]:
            parts.append("에뮬레이터 종료")
        if actions["close_maa"]:
            parts.append("MAA 종료")
        if actions["system_action"]:
            parts.append(SYSTEM_ACTIONS[actions["system_action"]])
        return " · ".join(parts) or "아무것도 하지 않음"


@dataclass(frozen=True)
class WindowTarget:
    hwnd: int
    pid: int
    path: str


def capture_window_target(hwnd):
    from app.monitoring import window_process_info

    hwnd = getattr(hwnd, "value", hwnd)
    if not isinstance(hwnd, int) or not hwnd:
        raise RuntimeError("실행 창을 확인할 수 없습니다.")
    pid, path = window_process_info(hwnd)
    if not pid or pid == os.getpid() or not path:
        raise RuntimeError("대상 프로그램의 PID/실행 경로를 확인할 수 없습니다.")
    return WindowTarget(hwnd, pid, path)


class Luid(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]


class LuidAndAttributes(ctypes.Structure):
    _fields_ = [("luid", Luid), ("attributes", wintypes.DWORD)]


class TokenPrivileges(ctypes.Structure):
    _fields_ = [("count", wintypes.DWORD), ("privileges", LuidAndAttributes * 1)]


class WindowsAfterActionBackend:
    """Load APIs lazily; tests replace this backend and never perform real actions."""
    def __init__(self):
        self.user32 = None

    def _load(self):
        if self.user32 is not None:
            return
        if sys.platform != "win32":
            raise RuntimeError("완료 후 시스템 동작은 Windows에서만 지원합니다.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
        for function, args, result in (
            (self.user32.IsWindow, [wintypes.HWND], wintypes.BOOL),
            (self.user32.PostMessageW, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            (self.user32.LockWorkStation, [], wintypes.BOOL),
            (self.user32.ExitWindowsEx, [wintypes.UINT, wintypes.DWORD], wintypes.BOOL),
            (self.kernel32.GetCurrentProcess, [], wintypes.HANDLE),
            (self.kernel32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel32.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel32.WaitForSingleObject, [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            (self.advapi32.OpenProcessToken, [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL),
            (self.advapi32.LookupPrivilegeValueW, [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(Luid)], wintypes.BOOL),
            (self.advapi32.AdjustTokenPrivileges, [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TokenPrivileges), wintypes.DWORD, ctypes.POINTER(TokenPrivileges), ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.powrprof.SetSuspendState, [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte], ctypes.c_ubyte),
        ):
            function.argtypes = args
            function.restype = result

    @staticmethod
    def _check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error() or 31)  # ERROR_GEN_FAILURE if API supplies no detail

    def close_program(self, target):
        self._load()
        if not isinstance(target, WindowTarget):
            raise RuntimeError("실행 대상 정보가 없어 종료 요청을 생략합니다.")
        if not self.user32.IsWindow(target.hwnd):
            raise RuntimeError("실행 대상 창이 이미 종료되었습니다.")
        actual = capture_window_target(target.hwnd)
        if actual.pid != target.pid or actual.path.casefold() != target.path.casefold():
            raise RuntimeError("실행 대상이 변경되어 종료 요청을 생략합니다.")
        self._check(self.user32.PostMessageW(target.hwnd, 0x0010, 0, 0))  # WM_CLOSE, no force kill

    @contextmanager
    def _shutdown_privilege(self):
        token = wintypes.HANDLE()
        self._check(self.advapi32.OpenProcessToken(self.kernel32.GetCurrentProcess(), 0x20 | 0x08, ctypes.byref(token)))
        previous = TokenPrivileges()
        enabled = False
        try:
            desired = TokenPrivileges()
            desired.count = 1
            self._check(self.advapi32.LookupPrivilegeValueW(None, "SeShutdownPrivilege", ctypes.byref(desired.privileges[0].luid)))
            desired.privileges[0].attributes = 0x02  # SE_PRIVILEGE_ENABLED
            length = wintypes.DWORD()
            ctypes.set_last_error(0)
            self._check(self.advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(desired), ctypes.sizeof(previous), ctypes.byref(previous), ctypes.byref(length)))
            error = ctypes.get_last_error()
            if error:
                raise ctypes.WinError(error)  # Includes ERROR_NOT_ALL_ASSIGNED.
            enabled = True
            yield
        finally:
            try:
                if enabled:
                    self._check(self.advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(previous), 0, None, None))
            finally:
                self.kernel32.CloseHandle(token)

    def system_action(self, action):
        if action not in SYSTEM_ACTIONS:
            raise ValueError("지원하지 않는 시스템 동작입니다.")
        self._load()
        if action == "lock":
            self._check(self.user32.LockWorkStation())
        else:
            with self._shutdown_privilege():
                if action == "shutdown":
                    self._check(self.user32.ExitWindowsEx(0x08, 0x80040000))  # planned application, no force
                else:
                    self._check(self.powrprof.SetSuspendState(action == "hibernate", False, False))

    def defer_system_action(self, action, log_path):
        """An independent helper waits for this exact process to exit before power/lock."""
        if action not in SYSTEM_ACTIONS:
            raise ValueError("지원하지 않는 시스템 동작입니다.")
        self._load()
        if getattr(sys, "frozen", False):
            raise RuntimeError("현재 전원 동작 도우미는 Python 실행 환경이 필요합니다.")
        if action != "lock":
            with self._shutdown_privilege():
                pass  # Validate permission now, while failures can still be logged in the UI.
        # A real inherited process handle prevents a recycled PID from being targeted.
        process = self.kernel32.OpenProcess(0x00100000, True, os.getpid())  # SYNCHRONIZE
        self._check(process)
        try:
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {"handle_list": [process]}
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--after-exit", str(process), action, str(log_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=startup, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        finally:
            self.kernel32.CloseHandle(process)


def _run_after_exit(handle, action, log_path):
    backend = WindowsAfterActionBackend()
    try:
        backend._load()
        try:
            if backend.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) != 0:
                raise ctypes.WinError(ctypes.get_last_error() or 31)
        finally:
            backend.kernel32.CloseHandle(handle)
        backend.system_action(action)
        message = f"{SYSTEM_ACTIONS[action]} 요청 처리 완료"
    except Exception as error:
        message = f"{SYSTEM_ACTIONS[action]} 요청 실패: {error}"
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        from datetime import datetime
        stream.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--after-exit" or sys.argv[3] not in SYSTEM_ACTIONS:
        raise SystemExit(2)
    _run_after_exit(int(sys.argv[2]), sys.argv[3], sys.argv[4])
