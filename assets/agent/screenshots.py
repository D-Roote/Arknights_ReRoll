"""Save cached operator screens, optionally linking them to a later backup."""

from __future__ import annotations

import json
import secrets
import shutil
import time
from pathlib import Path

from maa.pipeline import JActionType, JScreencap

from agent.device_ops import DeviceOperationError


EXPORT_NODE = "SReset_SharedPrefs_Export"


def _capture_options(saved_dir: Path, custom_action_param: str) -> tuple[Path, bool]:
    try:
        param = json.loads(custom_action_param or "{}")
    except (json.JSONDecodeError, TypeError) as error:
        raise DeviceOperationError("촬영 custom_action_param은 JSON 객체여야 합니다.") from error
    if not isinstance(param, dict):
        raise DeviceOperationError("촬영 custom_action_param은 JSON 객체여야 합니다.")
    link_backup = param.get("link_backup", True)
    if not isinstance(link_backup, bool):
        raise DeviceOperationError("촬영 link_backup은 true 또는 false여야 합니다.")

    saved_dir = saved_dir.resolve()
    assets_dir = saved_dir.parent
    requested = param.get("save_dir", str(saved_dir))
    if not isinstance(requested, str) or not requested.strip():
        raise DeviceOperationError("촬영 save_dir은 비어 있지 않은 폴더 경로여야 합니다.")
    output_dir = Path(requested.strip())
    if not output_dir.is_absolute():
        output_dir = assets_dir / output_dir
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(assets_dir):
        raise DeviceOperationError("촬영 save_dir은 assets 디렉터리 안에 있어야 합니다.")
    if link_backup and output_dir != saved_dir:
        raise DeviceOperationError("백업 연동 촬영은 saved에 저장해야 합니다. 기록 전용 촬영은 link_backup을 false로 지정하세요.")
    return output_dir, link_backup


def capture_operator_screen(context, saved_dir: Path, custom_action_param: str = "") -> Path:
    """Keep per-iteration state in this task's Context, not in Agent globals."""
    output_dir, link_backup = _capture_options(saved_dir, custom_action_param)
    export_param = None
    if link_backup:
        node = context.get_node_data(EXPORT_NODE)
        if node is None:
            raise DeviceOperationError(f"백업 노드를 찾지 못했습니다: {EXPORT_NODE}")
        action = node.get("action", {})
        action_param = action.get("param", {})
        if action.get("type") != "Custom" or action_param.get("custom_action") != "ExportArknightsSharedPrefs":
            raise DeviceOperationError(f"shared_prefs 백업 CustomAction이 아닙니다: {EXPORT_NODE}")
        export_param = action_param.get("custom_action_param", {})
        if not isinstance(export_param, dict):
            raise DeviceOperationError("백업 custom_action_param은 JSON 객체여야 합니다.")

    output_dir.mkdir(parents=True, exist_ok=True)
    # Seconds retain the existing naming convention; randomness separates instances.
    backup_id = f"{time.strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(8)}"
    screenshot = output_dir / f"shared_prefs_{backup_id}.png"
    native_filename = f"anreroll_capture_{backup_id}"
    native_screenshot: Path | None = None
    created = False
    try:
        # Pipeline recognition already refreshed the controller's full-screen cache.
        # Let MaaFW encode/save it; do not take another frame or import an image library.
        result = context.run_action_direct(
            JActionType.Screencap,
            JScreencap(filename=native_filename, format="png"),
        )
        if result is None or not result.success:
            raise DeviceOperationError("MaaFW의 오퍼레이터 캐시 화면 저장에 실패했습니다.")
        # 5.12.3 has no typed Screencap result; filepath is in raw_detail.
        filepath = result.raw_detail.get("filepath")
        if not isinstance(filepath, str) or not filepath.strip():
            raise DeviceOperationError("MaaFW가 저장한 화면의 파일 경로가 없습니다.")
        candidate = Path(filepath)
        if (
            not candidate.is_absolute()
            or candidate.name != f"{native_filename}.png"
            or candidate.is_symlink()
        ):
            raise DeviceOperationError("MaaFW 화면 저장 경로가 요청한 파일과 일치하지 않습니다.")
        native_screenshot = candidate
        if not native_screenshot.is_file() or native_screenshot.stat().st_size == 0:
            raise DeviceOperationError("MaaFW가 저장한 오퍼레이터 화면이 없거나 비어 있습니다.")

        # The native action writes under log_dir/screencap; retain only our saved copy.
        # Exclusive creation also protects existing screenshots from accidental reuse.
        with native_screenshot.open("rb") as source:
            with screenshot.open("xb") as output:
                created = True
                shutil.copyfileobj(source, output)
        if screenshot.stat().st_size == 0:
            raise DeviceOperationError("복사한 오퍼레이터 화면이 비어 있습니다.")
        if export_param is not None:
            export_param = {
                **export_param,
                "name": backup_id,
                "screenshot_path": str(screenshot),
                "require_screenshot": True,
            }
            if not context.override_pipeline({
                EXPORT_NODE: {
                    "action": {
                        "type": "Custom",
                        "param": {
                            "custom_action": "ExportArknightsSharedPrefs",
                            "custom_action_param": export_param,
                        },
                    },
                },
            }):
                raise DeviceOperationError("촬영 ID를 백업 노드에 전달하지 못했습니다.")
    except Exception:
        if created:
            screenshot.unlink(missing_ok=True)
        raise
    finally:
        if native_screenshot is not None:
            try:
                native_screenshot.unlink(missing_ok=True)
            except OSError as error:
                # A log-directory cleanup failure must not invalidate a completed backup handoff.
                print(f"[ANReroll Agent] 임시 화면 파일 정리 실패: {error}", flush=True)
    return screenshot
