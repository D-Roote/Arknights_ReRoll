"""ADB operations used by the ANReroll MaaFramework custom actions."""

from __future__ import annotations

import base64
import json
import re
import secrets
import shlex
import shutil
import time
import traceback
from pathlib import Path, PurePosixPath
from typing import Callable
from xml.etree import ElementTree


ARKNIGHTS_PACKAGE = "com.YoStarKR.Arknights"
ARKNIGHTS_SHARED_PREFS = f"/data/data/{ARKNIGHTS_PACKAGE}/shared_prefs"
# Google Play services 26.39 uses "adid"; older versions used "ads".
ADS_SETTINGS_COMPONENTS = (
    "com.google.android.gms/.adid.settings.AdsSettingsActivity",
    "com.google.android.gms/.ads.settings.AdsSettingsActivity",
)
ADS_SETTINGS_ACTIONS = (
    "com.google.android.gms.settings.ADS_PRIVACY",
    "androidx.ads.identifier.provider.OPEN_SETTINGS",
)

RESET_LABELS = (
    "Reset advertising ID",
    "Get new advertising ID",
    "광고 ID 재설정",
    "새 광고 ID 받기",
)
DELETE_LABELS = ("Delete advertising ID", "광고 ID 삭제")
CONFIRM_LABELS = (
    "Confirm",
    "OK",
    "확인",
    "재설정",
    "Reset advertising ID",
    "Get new advertising ID",
    "Delete advertising ID",
    "광고 ID 재설정",
    "새 광고 ID 받기",
    "광고 ID 삭제",
)

_BOUNDS_PATTERN = re.compile(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$")
# Firebase preference filenames can contain Base64 '+' and '=' characters.
_SAFE_REMOTE_FILENAME = re.compile(r"^[A-Za-z0-9._+=-]+$")
_SAFE_EXPORT_SUFFIX = re.compile(r"[^A-Za-z0-9._-]+")


class DeviceOperationError(RuntimeError):
    """Raised when the connected ADB device cannot complete an operation."""


class AdbShell:
    """Checked wrapper around the MaaFW 5.12.3 Controller.post_shell API."""

    _EXIT_MARKER = "__ANREROLL_EXIT__"

    def __init__(self, controller):
        self.controller = controller
        self._root_prefix: str | None = None

    def run(self, command: str, timeout_ms: int = 20_000) -> str:
        marked = (
            f"{command}; _anreroll_code=$?; "
            f"printf '\\n{self._EXIT_MARKER}%s' \"$_anreroll_code\""
        )
        job = self.controller.post_shell(f"sh -c {shlex.quote(marked)}", timeout_ms).wait()
        if not job.succeeded:
            raise DeviceOperationError(f"ADB shell 실행 실패: {command}")
        output = job.get()
        marker = output.rfind(self._EXIT_MARKER)
        if marker < 0:
            raise DeviceOperationError("ADB shell 종료 상태를 확인할 수 없습니다.")
        body = output[:marker].rstrip("\r\n")
        try:
            return_code = int(output[marker + len(self._EXIT_MARKER):].strip())
        except ValueError as error:
            raise DeviceOperationError("ADB shell 종료 상태가 올바르지 않습니다.") from error
        if return_code != 0:
            detail = body.strip() or f"exit {return_code}"
            raise DeviceOperationError(f"ADB shell 명령 실패: {detail}")
        return body

    def _detect_root_prefix(self) -> str:
        if self._root_prefix is not None:
            return self._root_prefix
        try:
            if self.run("id -u").strip() == "0":
                self._root_prefix = ""
                return self._root_prefix
        except DeviceOperationError:
            pass
        for prefix in ("su -c", "su 0 sh -c"):
            try:
                if self.run(f"{prefix} {shlex.quote('id -u')}").strip() == "0":
                    self._root_prefix = prefix
                    return prefix
            except DeviceOperationError:
                continue
        raise DeviceOperationError("shared_prefs 접근에 필요한 ADB root/su 권한이 없습니다.")

    def run_root(self, command: str, timeout_ms: int = 20_000) -> str:
        prefix = self._detect_root_prefix()
        rooted_command = command if not prefix else f"{prefix} {shlex.quote(command)}"
        return self.run(rooted_command, timeout_ms)


def _parse_hierarchy(output: str) -> ElementTree.Element:
    start = output.find("<hierarchy")
    end = output.rfind("</hierarchy>")
    if start < 0 or end < 0:
        raise DeviceOperationError("Android 화면 구조를 읽지 못했습니다.")
    try:
        return ElementTree.fromstring(output[start:end + len("</hierarchy>")])
    except ElementTree.ParseError as error:
        raise DeviceOperationError("Android 화면 구조 XML이 올바르지 않습니다.") from error


def _labeled_node(
    root: ElementTree.Element,
    labels: tuple[str, ...],
    excluded_center: tuple[int, int] | None = None,
) -> tuple[str, tuple[int, int]] | None:
    wanted = {label.casefold() for label in labels}
    for node in root.iter("node"):
        values = (node.attrib.get("text", ""), node.attrib.get("content-desc", ""))
        matched_label = next(
            (value.strip() for value in values if value.strip().casefold() in wanted),
            None,
        )
        if matched_label is None:
            continue
        match = _BOUNDS_PATTERN.fullmatch(node.attrib.get("bounds", ""))
        if not match:
            continue
        left, top, right, bottom = map(int, match.groups())
        if right > left and bottom > top:
            center = (left + right) // 2, (top + bottom) // 2
            if center != excluded_center:
                return matched_label, center
    return None


def _dump_hierarchy(shell: AdbShell) -> ElementTree.Element:
    output = shell.run(
        "uiautomator dump /sdcard/anreroll_window.xml >/dev/null "
        "&& cat /sdcard/anreroll_window.xml; rm -f /sdcard/anreroll_window.xml",
        15_000,
    )
    return _parse_hierarchy(output)


def _wait_and_tap(
    shell: AdbShell,
    labels: tuple[str, ...],
    timeout_seconds: float = 12.0,
    poll_interval: float = 0.5,
    excluded_center: tuple[int, int] | None = None,
    fallback_labels: tuple[str, ...] = (),
) -> tuple[str, tuple[int, int]]:
    deadline = time.monotonic() + timeout_seconds
    last_error: DeviceOperationError | None = None
    while time.monotonic() < deadline:
        try:
            root = _dump_hierarchy(shell)
            matched = _labeled_node(root, labels, excluded_center)
            if matched is None and fallback_labels:
                matched = _labeled_node(root, fallback_labels, excluded_center)
            if matched is not None:
                label, center = matched
                shell.run(f"input tap {center[0]} {center[1]}")
                return label, center
        except DeviceOperationError as error:
            last_error = error
        time.sleep(poll_interval)
    detail = f" ({last_error})" if last_error else ""
    raise DeviceOperationError(
        f"화면에서 필요한 항목을 찾지 못했습니다: {', '.join(labels + fallback_labels)}{detail}"
    )


def _open_ads_settings(shell: AdbShell) -> None:
    attempts = [f"-n {component}" for component in ADS_SETTINGS_COMPONENTS]
    attempts.extend(f"-a {action} -p com.google.android.gms" for action in ADS_SETTINGS_ACTIONS)
    failures = []
    for arguments in attempts:
        try:
            output = shell.run(f"am start -W {arguments}", 15_000)
            # Android's am can print "unable to resolve Intent" but still exit 0.
            # Validate its -W result for every fallback, not just the first attempt.
            if re.search(r"(?im)^\s*(?:Error\b|Exception\b|SecurityException\b)", output):
                raise DeviceOperationError(output.strip())
            if not re.search(r"(?im)^\s*Status:\s*ok\s*$", output):
                raise DeviceOperationError(output.strip() or "Activity 실행 결과가 비어 있습니다.")
        except DeviceOperationError as error:
            failures.append(f"{arguments}: {error}")
            continue
        print(f"[ANReroll Agent] 광고 설정 화면 열기: {arguments}", flush=True)
        return
    raise DeviceOperationError("Google 광고 설정 화면을 열지 못했습니다.\n" + "\n".join(failures))


def reset_advertising_id(shell: AdbShell) -> None:
    """Open Google Ads settings and request a fresh advertising ID through its UI."""
    _open_ads_settings(shell)
    # am -W can finish before the settings controls have been populated.
    first_label, first_center = _wait_and_tap(shell, RESET_LABELS, fallback_labels=DELETE_LABELS)
    _wait_and_tap(shell, CONFIRM_LABELS, excluded_center=first_center)
    if first_label.casefold() not in {label.casefold() for label in DELETE_LABELS}:
        return

    # Android 12+ may expose deletion and recreation instead of a reset item.
    _label, create_center = _wait_and_tap(shell, RESET_LABELS)
    _wait_and_tap(shell, CONFIRM_LABELS, excluded_center=create_center)


def _require_package(shell: AdbShell) -> None:
    path = shell.run(f"pm path {shlex.quote(ARKNIGHTS_PACKAGE)}").strip()
    if not path.startswith("package:"):
        raise DeviceOperationError(f"설치된 패키지를 찾지 못했습니다: {ARKNIGHTS_PACKAGE}")


def delete_shared_prefs(shell: AdbShell) -> None:
    _require_package(shell)
    shell.run(f"am force-stop {shlex.quote(ARKNIGHTS_PACKAGE)}")
    shell.run_root(f"rm -rf -- {shlex.quote(ARKNIGHTS_SHARED_PREFS)}")
    exists = shell.run_root(
        f"if [ -e {shlex.quote(ARKNIGHTS_SHARED_PREFS)} ]; then printf yes; else printf no; fi"
    )
    if exists.strip() != "no":
        raise DeviceOperationError("shared_prefs 삭제를 확인하지 못했습니다.")


def _export_suffix(custom_action_param: str) -> str:
    requested = ""
    if custom_action_param:
        try:
            param = json.loads(custom_action_param)
        except json.JSONDecodeError as error:
            raise DeviceOperationError("custom_action_param은 JSON이어야 합니다.") from error
        if isinstance(param, dict) and isinstance(param.get("name"), str):
            requested = param["name"].strip()
    if requested:
        suffix = _SAFE_EXPORT_SUFFIX.sub("_", requested).strip("._-")
        if not suffix:
            raise DeviceOperationError("내보내기 이름에 사용할 수 있는 문자가 없습니다.")
        return suffix[:96]
    return time.strftime("%Y%m%d%H%M%S")


def _require_export_screenshot(saved_dir: Path, suffix: str, custom_action_param: str) -> None:
    param = json.loads(custom_action_param) if custom_action_param else {}
    if not isinstance(param, dict):
        raise DeviceOperationError("백업 custom_action_param은 JSON 객체여야 합니다.")
    screenshot_path = param.get("screenshot_path")
    if screenshot_path is None:
        if param.get("require_screenshot", False):
            raise DeviceOperationError("촬영 정보가 없습니다. 같은 task에서 촬영 Agent를 먼저 실행하세요.")
        return
    if not isinstance(screenshot_path, str) or not screenshot_path.strip():
        raise DeviceOperationError("screenshot_path는 촬영 파일의 경로여야 합니다.")
    if not isinstance(param.get("name"), str) or not param["name"].strip():
        raise DeviceOperationError("촬영 이미지와 연결할 백업 name이 없습니다.")
    expected = saved_dir / f"shared_prefs_{suffix}.png"
    if Path(screenshot_path).resolve() != expected:
        raise DeviceOperationError("촬영 파일 경로와 백업 이름이 일치하지 않습니다.")
    if not expected.is_file() or expected.stat().st_size == 0:
        raise DeviceOperationError(f"촬영 이미지를 찾지 못했거나 파일이 비어 있습니다: {expected.name}")


def export_shared_prefs(shell: AdbShell, saved_dir: Path, custom_action_param: str = "") -> Path:
    saved_dir = saved_dir.resolve()
    suffix = _export_suffix(custom_action_param)
    # Fail before stopping the app if the screenshot/name handoff was lost.
    _require_export_screenshot(saved_dir, suffix, custom_action_param)
    destination = saved_dir / f"shared_prefs_{suffix}"
    if destination.exists():
        raise DeviceOperationError(f"내보내기 경로가 이미 존재합니다: {destination.name}")
    _require_package(shell)
    # SharedPreferences can be rewritten asynchronously; stop the app for a coherent snapshot.
    shell.run(f"am force-stop {shlex.quote(ARKNIGHTS_PACKAGE)}")
    exists = shell.run_root(
        f"if [ -d {shlex.quote(ARKNIGHTS_SHARED_PREFS)} ]; then printf yes; else printf no; fi"
    )
    if exists.strip() != "yes":
        raise DeviceOperationError("shared_prefs 디렉터리가 없습니다.")

    names_output = shell.run_root(f"ls -1A {shlex.quote(ARKNIGHTS_SHARED_PREFS)}")
    names = [line.rstrip("\r") for line in names_output.splitlines() if line.rstrip("\r")]
    for name in names:
        if (
            name in (".", "..")
            or not _SAFE_REMOTE_FILENAME.fullmatch(name)
            or PurePosixPath(name).name != name
        ):
            raise DeviceOperationError(f"안전하게 저장할 수 없는 shared_prefs 파일명입니다: {name!r}")

    saved_dir.mkdir(parents=True, exist_ok=True)
    temporary = saved_dir / f".tmp_shared_prefs_{secrets.token_hex(8)}"
    temporary.mkdir()
    try:
        for name in names:
            remote_path = f"{ARKNIGHTS_SHARED_PREFS}/{name}"
            encoded = shell.run_root(
                f"base64 {shlex.quote(remote_path)} | tr -d '\\r\\n'",
                60_000,
            )
            try:
                data = base64.b64decode(encoded, validate=True)
            except ValueError as error:
                raise DeviceOperationError(f"파일 전송 데이터가 손상되었습니다: {name}") from error
            (temporary / name).write_bytes(data)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def run_action(operation: Callable[[], object], action_name: str = "operation") -> bool:
    """Keep callback exceptions inside MaaFramework and emit a useful log."""
    try:
        print(f"[ANReroll Agent] 작업 시작: {action_name}", flush=True)
        result = operation()
        if result is False:
            print(f"[ANReroll Agent] 작업 실패: {action_name}", flush=True)
            return False
        if isinstance(result, Path):
            print(f"[ANReroll Agent] 내보내기 완료: {result}", flush=True)
        print(f"[ANReroll Agent] 작업 완료: {action_name}", flush=True)
        return True
    except (DeviceOperationError, OSError) as error:
        print(f"[ANReroll Agent] 작업 실패: {action_name}: {error}", flush=True)
        return False
    except Exception as error:
        # Exceptions escaping a ctypes callback can leave an undefined C return value.
        print(
            f"[ANReroll Agent] 작업 실패: {action_name}: {type(error).__name__}: {error}",
            flush=True,
        )
        traceback.print_exc()
        return False
