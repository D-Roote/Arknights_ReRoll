"""MaaFramework custom action classes and registration helpers."""

from __future__ import annotations

import ctypes
from pathlib import Path

from maa.custom_action import CustomAction
from maa.define import MaaBool, MaaControllerHandle, MaaCtrlId, MaaStringBufferHandle
from maa.library import Library

from agent.device_ops import (
    AdbShell,
    delete_shared_prefs,
    export_shared_prefs,
    reset_advertising_id,
    run_action,
)
from agent.screenshots import capture_operator_screen
from agent.restore_ops import import_shared_prefs


class ResetAdvertisingId(CustomAction):
    def run(self, context, argv):
        return run_action(
            lambda: reset_advertising_id(AdbShell(context.tasker.controller)),
            "ResetAdvertisingId",
        )


class DeleteArknightsSharedPrefs(CustomAction):
    def run(self, context, argv):
        return run_action(
            lambda: delete_shared_prefs(AdbShell(context.tasker.controller)),
            "DeleteArknightsSharedPrefs",
        )


class CaptureArknightsOperators(CustomAction):
    def __init__(self, saved_dir: Path):
        super().__init__()
        self.saved_dir = saved_dir

    def run(self, context, argv):
        return run_action(
            lambda: capture_operator_screen(context, self.saved_dir, argv.custom_action_param),
            "CaptureArknightsOperators",
        )


class ImportArknightsSharedPrefs(CustomAction):
    def __init__(self, saved_dir: Path):
        super().__init__()
        self.saved_dir = saved_dir

    def run(self, context, argv):
        return run_action(
            lambda: import_shared_prefs(
                AdbShell(context.tasker.controller), self.saved_dir, argv.custom_action_param
            ),
            "ImportArknightsSharedPrefs",
        )


class ExportArknightsSharedPrefs(CustomAction):
    def __init__(self, saved_dir: Path):
        super().__init__()
        self.saved_dir = saved_dir

    def run(self, context, argv):
        return run_action(
            lambda: export_shared_prefs(
                AdbShell(context.tasker.controller), self.saved_dir, argv.custom_action_param
            ),
            "ExportArknightsSharedPrefs",
        )


def _configure_shell_api() -> None:
    """Supply shell ctypes declarations missing from MaaFW 5.12.3 bindings."""
    library = Library.framework()
    signatures = (
        (
            "MaaControllerPostShell",
            MaaCtrlId,
            [MaaControllerHandle, ctypes.c_char_p, ctypes.c_int64],
        ),
        (
            "MaaControllerGetShellOutput",
            MaaBool,
            [MaaControllerHandle, MaaStringBufferHandle],
        ),
    )
    for name, return_type, argument_types in signatures:
        function = getattr(library, name)
        if function.argtypes is None:
            function.restype = return_type
            function.argtypes = argument_types


def create_actions(saved_dir: Path) -> tuple[tuple[str, CustomAction], ...]:
    _configure_shell_api()
    return (
        ("ResetAdvertisingId", ResetAdvertisingId()),
        ("DeleteArknightsSharedPrefs", DeleteArknightsSharedPrefs()),
        ("CaptureArknightsOperators", CaptureArknightsOperators(saved_dir)),
        ("ExportArknightsSharedPrefs", ExportArknightsSharedPrefs(saved_dir)),
        ("ImportArknightsSharedPrefs", ImportArknightsSharedPrefs(saved_dir)),
    )


def register_resource_actions(resource, saved_dir: Path) -> None:
    for name, action in create_actions(saved_dir):
        if not resource.register_custom_action(name, action):
            raise RuntimeError(f"MaaFramework CustomAction 등록에 실패했습니다: {name}")
