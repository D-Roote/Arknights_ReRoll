"""Process-owned execution sessions and JSON-only GUI/worker boundaries."""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import multiprocessing as mp
import os
from pathlib import Path
from queue import Empty, Full
import threading
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from app.monitoring import MonitoringService, supported_presets
from app.sessionRuntime import SessionRuntime, needs_desktop_lock, resolve_preset, serialize_target, target_identity


ACTIVE_STATES = {"starting", "waiting", "running", "checking", "stopping"}
STATE_LABELS = {"idle": "연결 대상 선택", "ready": "연결 확인 완료 · 실행 시 재연결", "starting": "시작 준비",
                "waiting": "Win32 입력 대기", "running": "작업 실행 중", "checking": "연결 확인 중",
                "stopping": "중지 및 정리 중", "completed": "작업 완료", "stopped": "작업 중지", "failed": "실패"}


def discover_connections(snapshot, preferences=None, preset_name=None):
    presets = supported_presets(snapshot["interface"], snapshot["resource"])
    preferred = snapshot.get("controller", {}).get("name")
    presets.sort(key=lambda preset: preset["name"] != preferred)
    seen, found, errors = set(), [], []
    for preset in presets:
        if preset_name is not None and preset["name"] != preset_name:
            continue
        service = MonitoringService(snapshot["interface"], snapshot["resource"],
                                    Path(snapshot["user_dir"]) / "sessions" / "discovery")
        try:
            for target in service.discover(preset["name"], preferences, snapshot.get("program")):
                if target.kind == "Win32" and target.pid == os.getpid():
                    continue
                connection = {"preset": preset["name"], "target": serialize_target(target),
                              "preferences": deepcopy(preferences or {}), "emulator": {}}
                if target.kind == "Adb":
                    connection["preferences"]["address"] = target.key
                identity = target_identity(connection)
                if identity and identity not in seen:
                    seen.add(identity)
                    found.append(connection)
        except Exception as error:
            errors.append(f"{preset.get('label') or preset['name']}: {error}")
        finally:
            service.close()
    return found, errors


def session_process(snapshot, connection, mode, stop_event, events, desktop_lock):
    """Top-level spawn target: never import or create GUI widgets here."""
    from app.crashDiagnostics import enable_fault_log
    from app.afterActions import capture_window_target
    from maa.toolkit import Toolkit
    runtime = None
    locked = False
    done = threading.Event()
    stopper = None
    outcome = {"succeeded": False, "message": "세션을 시작하지 못했습니다.", "target": None}

    def send(kind, value):
        try:
            events.put((kind, value), timeout=2 if kind == "result" else 0)
        except (Full, OSError, ValueError):
            pass  # A stalled GUI cannot accumulate an unbounded native log queue.

    try:
        preset = resolve_preset(snapshot, connection)
        if needs_desktop_lock(preset, snapshot.get("minimize", False)):
            send("state", "waiting")
            while not desktop_lock.acquire(timeout=0.1):
                if stop_event.is_set():
                    outcome["message"] = "작업이 중지되었습니다."
                    return
            locked = True
        if stop_event.is_set():
            outcome["message"] = "작업이 중지되었습니다."
            return
        directory = Path(snapshot["user_dir"]) / "sessions" / snapshot["session_id"] / uuid4().hex
        enable_fault_log(directory)
        runtime = SessionRuntime(snapshot, connection, directory)
        runtime.log_sink.set_log_callback(lambda message: send("log", message))
        if not Toolkit.init_option(str(directory), snapshot.get("settings", {})):
            raise RuntimeError("세션 연결 도구 초기화에 실패했습니다.")
        runtime._toolkit_initialized = True

        def cancel():
            while not done.wait(0.05):
                if stop_event.is_set() and runtime.tasker is not None:
                    runtime.stop_task()
                    return
        stopper = threading.Thread(target=cancel, daemon=True)
        stopper.start()
        if mode == "check":
            send("state", "checking")
            created, message = runtime._create_controller()
            if not created:
                raise RuntimeError(message)
            outcome["succeeded"], outcome["message"] = runtime._execute_controller()
        else:
            send("state", "starting")
            initialized, message = runtime.initialize(
                snapshot.get("controller"), program_settings=snapshot.get("program"),
                execution_queue=snapshot["queue"], minimize_window=snapshot["minimize"],
                cancellation_requested=stop_event.is_set)
            if not initialized:
                outcome["message"] = message
                return
            if preset["type"] == "Win32" and snapshot.get("after_actions", {}).get("close_program"):
                from dataclasses import asdict
                outcome["target"] = asdict(capture_window_target(runtime._target_hwnd))
            send("state", "running")
            outcome["succeeded"], outcome["message"] = runtime.run_task(
                snapshot["queue"], minimize_window=snapshot["minimize"], cancellation_requested=stop_event.is_set)
    except Exception as error:
        outcome["message"] = str(error)
    finally:
        done.set()
        if stopper is not None:
            stopper.join(6)
        if runtime is not None:
            try:
                success, message = runtime.release_session()
                if not success:
                    outcome["succeeded"] = False
                    outcome["message"] += "\n" + message
            except Exception as error:
                outcome["succeeded"] = False
                outcome["message"] += "\n정리 실패: " + str(error)
        if stop_event.is_set():
            outcome["succeeded"] = False
            outcome["message"] += "\n작업이 중지되었습니다."
        outcome["message"] = "\n".join(dict.fromkeys(outcome["message"].splitlines()))
        send("result", outcome)
        # A process exits before the GUI declares the session idle. The mutex
        # is released only after both stop-thread and native lifecycle cleanup.
        if locked:
            desktop_lock.release()


@dataclass
class Session:
    id: str
    title: str
    connection: dict = field(default_factory=dict)
    state: str = "idle"
    process: object = None
    events: object = None
    stop_event: object = None
    mode: str = "run"
    result: dict | None = None
    remove_pending: bool = False
    logs: deque = field(default_factory=lambda: deque(maxlen=200))

    @property
    def active(self):
        return self.process is not None


class SessionManager(QObject):
    changed = Signal(str)
    log = Signal(str, str)
    activity_changed = Signal()
    wave_finished = Signal(object, object)

    def __init__(self, parent=None, context=None):
        super().__init__(parent)
        self.context = context or mp.get_context("spawn")
        self.desktop_lock = self.context.Lock()
        self.sessions = {}
        self.wave = None
        self.closing = False
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.poll)

    @property
    def active(self):
        return any(session.active for session in self.sessions.values())

    def add(self, connection=None, title=None):
        connection = deepcopy(connection or {})
        identity = target_identity(connection)
        if identity and any(target_identity(session.connection) == identity for session in self.sessions.values()):
            return None
        number = 1
        while f"인스턴스 {number}" in {s.title for s in self.sessions.values()}:
            number += 1
        session = Session(uuid4().hex, title or f"인스턴스 {number}", connection)
        self.sessions[session.id] = session
        self.changed.emit(session.id)
        return session.id

    def configure(self, session_id, connection):
        session = self.sessions[session_id]
        if session.active:
            raise ValueError("실행/연결 확인 중에는 연결 대상을 변경할 수 없습니다.")
        identity = target_identity(connection)
        if identity and any(other.id != session_id and target_identity(other.connection) == identity
                            for other in self.sessions.values()):
            raise ValueError("이미 다른 인스턴스에 등록된 연결 대상입니다.")
        session.connection = deepcopy(connection)
        session.state = "idle"
        session.result = None
        self.changed.emit(session_id)

    def validate_start(self, session_id, snapshot):
        session = self.sessions[session_id]
        preset = resolve_preset(snapshot, session.connection)
        # ADB convenience minimization must never manipulate another session's
        # Win32 window, even if that session is only waiting for the input lock.
        target = session.connection.get("emulator") if preset["type"] == "Adb" else session.connection["target"]
        if not target or (preset["type"] == "Adb" and not snapshot.get("minimize")):
            return
        identity = (target.get("pid"), target.get("hwnd"))
        for other in self.sessions.values():
            if other.id == session_id:
                continue
            candidate = other.connection.get("target") or {}
            emulator = other.connection.get("emulator") or {}
            candidates = [candidate] if candidate.get("kind") == "Win32" else [emulator]
            if any(identity == (item.get("pid"), item.get("hwnd")) for item in candidates):
                raise ValueError("편의 최소화 창이 다른 인스턴스의 창과 겹칩니다. 창 선택을 해제하세요.")

    def mark_wave_failure(self, session_id, message):
        if self.wave is not None and not any(result["id"] == session_id and not result["succeeded"]
                                             for result in self.wave["results"]):
            self.wave["results"].append({"id": session_id, "succeeded": False, "message": str(message)})

    def start(self, session_id, snapshot, mode="run"):
        session = self.sessions[session_id]
        if self.closing or session.active:
            return False
        self.validate_start(session_id, snapshot)
        request = deepcopy(snapshot)
        request["session_id"] = session_id
        if mode == "run" and not request.get("queue"):
            raise ValueError("시작 탭에서 실행할 작업을 선택하세요.")
        session.mode, session.result = mode, None
        session.logs.clear() if request.get("clear_log") else None
        session.stop_event = self.context.Event()
        session.events = self.context.Queue(maxsize=512)
        session.process = self.context.Process(
            target=session_process, args=(request, deepcopy(session.connection), mode, session.stop_event,
                                         session.events, self.desktop_lock), daemon=False)
        session.state = "checking" if mode == "check" else "starting"
        try:
            session.process.start()
        except Exception as error:
            session.process.close()
            session.process = None
            session.events.close()
            session.state = "failed"
            self.mark_wave_failure(session_id, error)
            self.changed.emit(session_id)
            raise
        if mode == "run":
            if self.wave is None:
                self.wave = {"ids": set(), "results": [], "actions": deepcopy(request.get("after_actions", {}))}
            self.wave["ids"].add(session_id)
        self.timer.start()
        self.changed.emit(session_id)
        self.activity_changed.emit()
        return True

    def stop(self, session_id):
        session = self.sessions.get(session_id)
        if session is not None and session.active:
            session.stop_event.set()
            session.state = "stopping"
            self.changed.emit(session_id)

    def stop_all(self):
        for session_id in list(self.sessions):
            self.stop(session_id)

    def remove(self, session_id):
        session = self.sessions[session_id]
        if session.active:
            session.remove_pending = True
            self.stop(session_id)
        else:
            del self.sessions[session_id]
            self.changed.emit(session_id)

    def poll(self):
        finished = False
        for session in list(self.sessions.values()):
            if not session.active:
                continue
            was_alive = session.process.is_alive()
            for _ in range(100 if was_alive else 600):
                try:
                    kind, value = session.events.get_nowait()
                except Empty:
                    break
                if kind == "log":
                    session.logs.append(str(value))
                    self.log.emit(session.id, str(value))
                elif kind == "state" and session.state != "stopping":
                    session.state = value
                    self.changed.emit(session.id)
                elif kind == "result":
                    session.result = value
            if was_alive:
                continue
            finished = True
            session.process.join(timeout=0)
            cancelled = session.stop_event.is_set()
            result = session.result or {"succeeded": False, "message": "실행 프로세스가 결과 없이 종료되었습니다."}
            exit_code = session.process.exitcode
            if exit_code not in (None, 0):
                result = {**result, "succeeded": False,
                          "message": result["message"] + f"\n실행 프로세스 비정상 종료: {exit_code:#x}. 세션 진단 로그를 확인하세요."}
            session.result = result
            session.state = ("stopped" if cancelled else "ready" if result["succeeded"] and session.mode == "check"
                             else "completed" if result["succeeded"] else "failed")
            session.process.close()
            session.process = None
            session.events.close()
            session.events = None
            if session.mode == "run" and self.wave is not None:
                self.wave["results"].append({"id": session.id, "connection": deepcopy(session.connection), **result,
                                              "succeeded": bool(result["succeeded"] and not cancelled)})
                self.wave["ids"].discard(session.id)
            self.log.emit(session.id, result["message"])
            if session.remove_pending:
                del self.sessions[session.id]
            self.changed.emit(session.id)
        if not self.active:
            self.timer.stop()
            if self.wave is not None:
                wave, self.wave = self.wave, None
                self.wave_finished.emit(wave["results"], wave["actions"])
        if finished:
            self.activity_changed.emit()

    def saved_sessions(self):
        return [{"title": session.title, "connection": deepcopy(session.connection)} for session in self.sessions.values()]

    def restore(self, records):
        if isinstance(records, list):
            for record in records:
                if isinstance(record, dict) and isinstance(record.get("connection"), dict):
                    connection = record["connection"]
                    if (connection.get("target") is not None and not isinstance(connection["target"], dict)
                            or not isinstance(connection.get("preferences", {}), dict)
                            or not isinstance(connection.get("emulator", {}), dict)):
                        continue
                    self.add(connection, str(record.get("title", "인스턴스"))[:128])

    def shutdown(self):
        self.closing = True
        self.stop_all()
