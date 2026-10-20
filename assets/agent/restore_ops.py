"""Restore a local shared_prefs backup without changing its source folder."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import shlex
import stat
from pathlib import Path, PurePosixPath

from agent.device_ops import (
    ARKNIGHTS_PACKAGE,
    ARKNIGHTS_SHARED_PREFS,
    AdbShell,
    DeviceOperationError,
    _require_package,
    _SAFE_REMOTE_FILENAME,
)


_BACKUP_NAME = re.compile(r"shared_prefs_[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
# Leave room for sh/su quoting and remote paths in short ADB shell commands.
_CHUNK_SIZE = 2 * 1024


def _is_link(path: Path) -> bool:
    # Windows junctions are reparse points even on Python 3.10.
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _read_backup(saved_dir: Path, custom_action_param: str) -> tuple[Path, dict[str, bytes]]:
    try:
        param = json.loads(custom_action_param or "{}")
    except json.JSONDecodeError as error:
        raise DeviceOperationError("불러오기 custom_action_param은 JSON이어야 합니다.") from error
    name = param.get("source_dir") if isinstance(param, dict) else None
    if not isinstance(name, str) or not _BACKUP_NAME.fullmatch(name):
        raise DeviceOperationError("assets/saved 아래의 shared_prefs_ 백업 폴더 이름을 입력하세요.")
    saved_dir = saved_dir.resolve()
    source = saved_dir / name
    if not source.is_dir() or _is_link(source) or source.resolve().parent != saved_dir:
        raise DeviceOperationError(f"불러올 백업 폴더가 없거나 안전한 경로가 아닙니다: {name}")
    files = {}
    for path in sorted(source.iterdir()):
        if (
            not path.is_file()
            or _is_link(path)
            or path.resolve().parent != source
            or not _SAFE_REMOTE_FILENAME.fullmatch(path.name)
            or path.name in (".", "..")
        ):
            raise DeviceOperationError(f"복원할 수 없는 파일 또는 하위 폴더입니다: {path.name!r}")
        # Snapshot all bytes before touching the device; never rename/write the PC source.
        files[path.name] = path.read_bytes()
    if not files:
        raise DeviceOperationError("백업 폴더가 비어 있어 복원하지 않습니다.")
    return source, files


def _swap_script(stage: str, previous: str, owner: str, relabel: bool) -> str:
    target = shlex.quote(ARKNIGHTS_SHARED_PREFS)
    stage, previous = shlex.quote(stage), shlex.quote(previous)
    lines = [
        "set -eu",
        "anr_previous_started=0; anr_install_started=0; anr_committed=0",
        "anr_rollback() {",
        "  anr_code=$?",
        "  trap - EXIT HUP INT TERM",
        '  if [ "$anr_committed" -eq 0 ]; then',
        f'    if [ "$anr_install_started" -eq 1 ] && [ ! -e {stage} ] && [ ! -L {stage} ]; then',
        f"      test ! -L {target} && test -d {target} || exit 2",
        f"      rm -rf -- {target} || exit 2",
        "    fi",
        f'    if [ "$anr_previous_started" -eq 1 ] && [ -e {previous} ]; then',
        f"      test ! -L {previous} && test -d {previous} || exit 2",
        f"      test ! -e {target} && test ! -L {target} || exit 2",
        f"      mv -- {previous} {target} || exit 2",
        "    fi",
        "  fi",
        '  exit "$anr_code"',
        "}",
        "trap anr_rollback EXIT",
        "trap 'exit 1' HUP INT TERM",
        # Reject both live and dangling symlinks, and avoid nesting mv into a directory.
        f"test ! -L {target}",
        f"test ! -e {previous} && test ! -L {previous}",
        f"test -d {stage} && test ! -L {stage}",
        f"if [ -e {target} ]; then test -d {target}; anr_previous_started=1; mv -- {target} {previous}; fi",
        f"test ! -e {target} && test ! -L {target}",
        "anr_install_started=1",
        f"mv -- {stage} {target}",
    ]
    if relabel:
        lines.append(f"restorecon -RFD {target}")
    lines.append(f'test "$(stat -c %u:%g:%a {target})" = {shlex.quote(owner + ":700")}')
    # Only discard the previous device data after the replacement is usable.
    lines.extend([
        "anr_committed=1",
        f'if [ "$anr_previous_started" -eq 1 ]; then rm -rf -- {previous}; fi',
        "trap - EXIT HUP INT TERM",
    ])
    return "\n".join(lines)


def import_shared_prefs(shell: AdbShell, saved_dir: Path, custom_action_param: str = "") -> None:
    source, files = _read_backup(saved_dir, custom_action_param)
    _require_package(shell)
    app_dir = str(PurePosixPath(ARKNIGHTS_SHARED_PREFS).parent)
    app_path, target = shlex.quote(app_dir), shlex.quote(ARKNIGHTS_SHARED_PREFS)
    # Root/su and tools are checked before any device data is replaced.
    owner = shell.run_root(
        f"test -d {app_path} && test ! -L {app_path} && stat -c %u:%g {app_path}"
    ).strip()
    match = re.fullmatch(r"([0-9]+):([0-9]+)", owner)
    if match is None or int(match[1]) < 10000:
        raise DeviceOperationError("게임 데이터 디렉터리의 앱 UID/GID를 확인하지 못했습니다.")
    shell.run_root("command -v base64 >/dev/null && command -v sha256sum >/dev/null")
    selinux = shell.run_root(
        "if [ -e /sys/fs/selinux/enforce ]; then printf yes; else printf no; fi"
    ).strip()
    if selinux not in ("yes", "no"):
        raise DeviceOperationError("기기의 SELinux 활성 상태를 확인하지 못했습니다.")
    relabel = selinux == "yes"
    if relabel:
        shell.run_root("command -v restorecon >/dev/null")
    shell.run_root(
        f"test ! -L {target} && if [ -e {target} ]; then test -d {target}; fi"
    )

    token = secrets.token_hex(8)
    stage = f"{app_dir}/.anreroll_restore_{token}"
    previous = f"{app_dir}/.anreroll_previous_{token}"
    lock = f"{app_dir}/.anreroll_restore_lock"
    # The fixed package path plus generated children are the only remote rm/mv targets.
    try:
        shell.run_root(f"umask 077; mkdir -- {shlex.quote(lock)}")
    except DeviceOperationError:
        raise DeviceOperationError(f"복원 잠금을 얻지 못했습니다. 동시 실행 또는 이전 실패를 확인하세요: {lock}") from None
    stage_created = swap_started = retain_lock = operation_failed = False
    try:
        shell.run(f"am force-stop {shlex.quote(ARKNIGHTS_PACKAGE)}")
        shell.run_root(f"umask 077; mkdir -- {shlex.quote(stage)}")
        stage_created = True
        for name, data in files.items():
            remote = shlex.quote(f"{stage}/{name}")
            shell.run_root(f"umask 077; : > {remote}")
            for offset in range(0, len(data), _CHUNK_SIZE):
                encoded = base64.b64encode(data[offset:offset + _CHUNK_SIZE]).decode("ascii")
                try:
                    shell.run_root(f"printf %s {shlex.quote(encoded)} | base64 -d >> {remote}")
                except DeviceOperationError:
                    # Do not print encoded preference values into the Agent error message.
                    raise DeviceOperationError(f"복원 파일 전송에 실패했습니다: {name}") from None
            digest = shell.run_root(f"sha256sum {remote}").split()
            if not digest or digest[0] != hashlib.sha256(data).hexdigest():
                raise DeviceOperationError(f"복원 파일 전송 검증에 실패했습니다: {name}")
            shell.run_root(f"chmod 600 -- {remote}")
        shell.run_root(f"chown -R {shlex.quote(owner)} {shlex.quote(stage)}")
        # Verify each file BEFORE promotion. rename preserves UID/GID/mode;
        # embedding this loop in the swap command exceeded MuMu's shell limit.
        for name in files:
            remote = shlex.quote(f"{stage}/{name}")
            metadata = shell.run_root(f"stat -c %u:%g:%a {remote}").strip()
            if metadata != owner + ":600":
                raise DeviceOperationError(f"복원 파일의 소유권/권한 검증에 실패했습니다: {name}")
        script = _swap_script(stage, previous, owner, relabel)
        command = f"sh -c {shlex.quote(script)}"
        # Keep headroom for AdbShell's additional sh/su quoting. This size is
        # independent of the number and length of backup filenames.
        if len(command.encode("utf-8")) > 2800:
            raise DeviceOperationError("복원 교체 명령이 기기의 안전한 전송 크기를 초과했습니다.")
        swap_started = True
        # Isolate set -e/traps from AdbShell's outer exit-status marker wrapper.
        shell.run_root(command, 60_000)
    except Exception:
        operation_failed = True
        # A timeout/disconnect can leave a remote command running. Do not infer
        # rollback success from the mere absence of the previous-directory name.
        retain_lock = swap_started
        if retain_lock:
            print(
                f"[ANReroll Agent] 기기 복구 확인 필요: 기존={previous}, 임시={stage}, 잠금={lock}",
                flush=True,
            )
        raise
    finally:
        if not retain_lock:
            cleanup = "set -e\n"
            if stage_created:
                cleanup += (
                    f"if [ -e {shlex.quote(stage)} ] || [ -L {shlex.quote(stage)} ]; then "
                    f"test ! -L {shlex.quote(stage)}; test -d {shlex.quote(stage)}; "
                    f"rm -rf -- {shlex.quote(stage)}; fi\n"
                )
            cleanup += f"rmdir -- {shlex.quote(lock)}"
            try:
                shell.run_root(f"sh -c {shlex.quote(cleanup)}")
            except Exception:
                print(f"[ANReroll Agent] 임시 복원 경로 정리 확인 필요: 임시={stage}, 잠금={lock}", flush=True)
                if not operation_failed:
                    raise
    print(f"[ANReroll Agent] 계정 복원 완료: {source.name} -> {ARKNIGHTS_SHARED_PREFS}", flush=True)
