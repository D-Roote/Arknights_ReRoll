from copy import deepcopy
import json
from pathlib import Path

from PySide6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.runtime import WIN32_METHOD_DEFAULTS, WIN32_METHOD_PRIORITY
from app.controls import PopupOnlyWheelComboBox
from app.monitoring import normalize_connection_preferences, normalize_screen_preferences
from app.pg_init import (
    DEFAULT_PROGRAM_CONFIG,
    find_auto_program_executable,
    find_program_executable,
    normalize_program_config,
    parse_manual_program_command,
    resolve_manual_program_path,
)

WIN32_MANUAL_PATH_DESCRIPTION = '자동 인식이 불가능하면 실행 파일을 지정하세요. "실행 파일 경로.exe" 인수 형식을 사용할 수 있습니다.'
ADB_MANUAL_PATH_DESCRIPTION = (
    '실행 디바이스의 바로가기 생성 후, 우클릭-속성-바로 가기 탭 의 "대상"을 복사하여 사용합니다.'
)


DEFAULT_MAA_CONFIG = {
    "general": {
        "minimize_enabled": False,
        "program_launch_task_enabled": True,
        "allow_option_edits_while_running": False,
        "clear_log_on_start": True,
    },
    "controller": {},
    "connection": {"adb_path": "", "address": ""},
    "monitor": {"mode": "single", "fps": 2},
    "program": DEFAULT_PROGRAM_CONFIG,
    "appearance": {
        "theme": "light",
    },
}


class SettingsStore:

    def __init__(self, config_path, legacy_user_config_path=None):
        self.config_path = Path(config_path)
        self.legacy_user_config_path = (
            Path(legacy_user_config_path) if legacy_user_config_path else None
        )

    @staticmethod
    def _read_json(path):
        if path is None or not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
            file.flush()
        temp_path.replace(path)

    def load(self, default_controller=None):
        raw_config = self._read_json(self.config_path)
        config = deepcopy(DEFAULT_MAA_CONFIG)

        if raw_config is not None:
            raw_general = raw_config.get("general")
            if isinstance(raw_general, dict):
                for key in (
                    "minimize_enabled",
                    "program_launch_task_enabled",
                    "allow_option_edits_while_running",
                    "clear_log_on_start",
                ):
                    if isinstance(raw_general.get(key), bool):
                        config["general"][key] = raw_general[key]
                # 직전 개발 버전에서 저장한 부정형 설정을 긍정형으로 이관한다.
                if (
                    not isinstance(raw_general.get("program_launch_task_enabled"), bool)
                    and isinstance(raw_general.get("remove_program_launch_task"), bool)
                ):
                    config["general"]["program_launch_task_enabled"] = not raw_general[
                        "remove_program_launch_task"
                    ]

            raw_controller = raw_config.get("controller")
            if isinstance(raw_controller, dict):
                config["controller"] = deepcopy(raw_controller)

            config["program"] = normalize_program_config(raw_config.get("program"))
            config["connection"] = normalize_connection_preferences(raw_config.get("connection"))
            config["monitor"] = normalize_screen_preferences(raw_config.get("monitor"))

            raw_appearance = raw_config.get("appearance")
            if isinstance(raw_appearance, dict):
                theme = raw_appearance.get("theme")
                if theme in {"system", "light", "dark"}:
                    config["appearance"]["theme"] = theme

        if not config["controller"] and isinstance(default_controller, dict):
            config["controller"] = self.serialize_controller(default_controller)

        legacy_config = self._read_json(self.legacy_user_config_path)
        migrated_legacy = None
        if legacy_config is not None and "minimize_enabled" in legacy_config:
            raw_general = raw_config.get("general") if raw_config else None
            has_new_value = isinstance(raw_general, dict) and isinstance(
                raw_general.get("minimize_enabled"), bool
            )
            legacy_value = legacy_config.get("minimize_enabled")
            if not has_new_value and isinstance(legacy_value, bool):
                config["general"]["minimize_enabled"] = legacy_value

            migrated_legacy = deepcopy(legacy_config)
            migrated_legacy.pop("minimize_enabled", None)

        self.save(config)
        if migrated_legacy is not None:
            self._write_json(self.legacy_user_config_path, migrated_legacy)
        return config

    def save(self, config):
        self._write_json(self.config_path, config)

    @staticmethod
    def serialize_controller(controller):
        if not isinstance(controller, dict):
            return {}
        return {
            key: deepcopy(controller[key])
            for key in ("name", "type", "win32", "adb")
            if key in controller
        }


class AssociatedControlLabel(QLabel):
    """A label that extends a checkable control's mouse hit area."""

    activated = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SettingsPanel(QWidget):
    minimize_changed = Signal(bool)
    program_launch_task_enabled_changed = Signal(bool)
    runtime_option_editing_changed = Signal(bool)
    theme_changed = Signal(str)
    controller_changed = Signal(object)
    program_changed = Signal(object)

    def __init__(
        self,
        config_path,
        legacy_user_config_path,
        controllers,
        supported_controller_names=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self._syncing_navigation = False
        self._sections = []
        self.controllers = self._filter_controllers(
            controllers, supported_controller_names
        )
        self.store = SettingsStore(config_path, legacy_user_config_path)
        default_controller = self.controllers[0] if self.controllers else None
        self.config = self.store.load(default_controller)

        self._build_ui()
        self._apply_config()
        self._connect_controls()
        QTimer.singleShot(0, lambda: self._sync_navigation_to_scroll(0))

    @staticmethod
    def _filter_controllers(controllers, supported_controller_names):
        if not isinstance(controllers, list):
            return []
        supported = (
            set(supported_controller_names)
            if isinstance(supported_controller_names, list)
            else None
        )
        result = []
        for controller in controllers:
            if not isinstance(controller, dict) or controller.get("type") not in ("Win32", "Adb"):
                continue
            name = controller.get("name")
            if not isinstance(name, str) or not name:
                continue
            if controller["type"] == "Win32" and not isinstance(controller.get("win32"), dict):
                continue
            if supported is not None and name not in supported:
                continue
            result.append(controller)
        return result

    def _build_ui(self):
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 6, 16)
        root_layout.setSpacing(16)

        self.navigation = QListWidget()
        self.navigation.setObjectName("settingsNavigation")
        self.navigation.setMinimumWidth(170)
        self.navigation.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        for label in ("일반", "프로그램", "컨트롤러", "외관"):
            item = QListWidgetItem(label)
            self.navigation.addItem(item)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("settingsDetailScroll")
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.detail_contents = QWidget()
        self.detail_contents.setObjectName("settingsDetailContents")
        self.detail_layout = QVBoxLayout(self.detail_contents)
        self.detail_layout.setContentsMargins(0, 0, 6, 0)
        self.detail_layout.setSpacing(14)

        general, general_layout = self._create_section(
            "일반", "작업 실행과 편집 동작을 설정합니다."
        )
        self.minimize_checkbox = QCheckBox()
        self.minimize_checkbox.setObjectName("settingsCheckbox")
        self._add_setting_row(
            general_layout,
            "실행 시 최소화",
            "작업을 시작할 때 대상 프로그램 창을 최소화합니다.",
            self.minimize_checkbox,
            control_right_margin=12,
        )
        self.program_launch_checkbox = QCheckBox()
        self.program_launch_checkbox.setObjectName("settingsCheckbox")
        self._add_setting_row(
            general_layout,
            "자동 실행 작업",
            "작업 시작 전 대상 프로그램을 자동 실행하는 작업을 목록 최상단에 표시합니다.",
            self.program_launch_checkbox,
            control_right_margin=12,
        )
        self.runtime_edit_checkbox = QCheckBox()
        self.runtime_edit_checkbox.setObjectName("settingsCheckbox")
        self._add_setting_row(
            general_layout,
            "작업 중 옵션 편집",
            (
                "실행 중에도 작업 활성화, 순서, 세부 옵션 등 모든 실행 옵션을 "
                "편집합니다. 변경 사항은 다음 실행부터 적용됩니다."
            ),
            self.runtime_edit_checkbox,
            control_right_margin=12,
        )
        self.clear_log_checkbox = QCheckBox()
        self.clear_log_checkbox.setObjectName("settingsCheckbox")
        self._add_setting_row(
            general_layout,
            "작업 시작 시 로그 초기화",
            "새로운 작업을 시작할 때 이전 실행의 로그를 비웁니다.",
            self.clear_log_checkbox,
            control_right_margin=12,
        )

        program, program_layout = self._create_section(
            "프로그램", "자동 실행에 사용할 대상 프로그램을 확인하거나 직접 지정합니다."
        )
        self.program_auto_status = QLabel()
        self.program_auto_status.setObjectName("programPathStatus")
        self.program_auto_status.setWordWrap(True)
        program_layout.addWidget(self.program_auto_status)
        program_layout.addSpacing(8)

        self.program_path_input = QLineEdit()
        self.program_path_input.setObjectName("programPathInput")
        self.program_path_input.setPlaceholderText(
            "실행 파일 또는 실행 파일이 있는 폴더 경로"
        )
        self.program_path_input.setMinimumWidth(260)
        self.program_browse_button = QPushButton("찾아보기")
        self.program_browse_button.setObjectName("programBrowseButton")
        self.program_apply_button = QPushButton("확인")
        self.program_apply_button.setObjectName("programApplyButton")

        program_path_controls = QWidget()
        program_path_controls.setObjectName("programPathControls")
        program_path_layout = QHBoxLayout(program_path_controls)
        program_path_layout.setContentsMargins(0, 0, 0, 0)
        program_path_layout.setSpacing(6)
        program_path_layout.addWidget(self.program_path_input, 1)
        program_path_layout.addWidget(self.program_browse_button)
        program_path_layout.addWidget(self.program_apply_button)
        self.program_path_row = self._add_setting_row(
            program_layout,
            "수동 경로",
            WIN32_MANUAL_PATH_DESCRIPTION,
            program_path_controls,
        )
        self.program_path_row.description_label.installEventFilter(self)
        self.program_path_row.description_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.program_active_status = QLabel()
        self.program_active_status.setObjectName("programPathStatus")
        self.program_active_status.setWordWrap(True)
        self.program_active_status_container = QWidget()
        self.program_active_status_container.setObjectName(
            "programActiveStatusContainer"
        )
        active_status_layout = QVBoxLayout(self.program_active_status_container)
        active_status_layout.setContentsMargins(0, 8, 0, 0)
        active_status_layout.setSpacing(0)
        active_status_layout.addWidget(self.program_active_status)
        self.program_active_status_effect = QGraphicsOpacityEffect(
            self.program_active_status_container
        )
        self.program_active_status_effect.setOpacity(1.0)
        self.program_active_status_container.setGraphicsEffect(
            self.program_active_status_effect
        )
        program_layout.addWidget(self.program_active_status_container)
        self.program_path_row.layout().setContentsMargins(0, 12, 0, 0)
        self._program_status_animation = None
        self._manual_path_error_active = False

        controller, controller_layout = self._create_section(
            "컨트롤러", "실행에 사용할 컨트롤러를 선택합니다."
        )
        self.controller_combo = PopupOnlyWheelComboBox()
        self.controller_combo.setObjectName("settingsComboBox")
        self.controller_combo.setMinimumWidth(240)
        if self.controllers:
            for controller_config in self.controllers:
                label = controller_config.get("label") or controller_config["name"]
                self.controller_combo.addItem(label, controller_config)
        else:
            self.controller_combo.addItem("사용 가능한 컨트롤러 없음", None)
            self.controller_combo.setEnabled(False)
        self._add_setting_row(
            controller_layout,
            "사용할 컨트롤러",
            "선택한 캡처 및 입력 방식은 다음 실행부터 적용됩니다.",
            self.controller_combo,
        )
        controller_layout.addSpacing(8)
        self.controller_details = QLabel()
        self.controller_details.setObjectName("controllerDetails")
        self.controller_details.setWordWrap(True)
        controller_layout.addWidget(self.controller_details)
        self._connection_layout = controller_layout

        appearance, appearance_layout = self._create_section(
            "외관", "애플리케이션의 표시 방식을 설정합니다."
        )
        self.theme_combo = PopupOnlyWheelComboBox()
        self.theme_combo.setObjectName("settingsComboBox")
        self.theme_combo.setMinimumWidth(180)
        for label, value in (
            ("시스템 설정", "system"),
            ("라이트", "light"),
            ("다크", "dark"),
        ):
            self.theme_combo.addItem(label, value)
        self._add_setting_row(
            appearance_layout,
            "색상 모드",
            "애플리케이션 전체와 Windows 제목 표시줄의 색상을 변경합니다.",
            self.theme_combo,
        )

        # The card owns its bottom inset; avoid doubling it on a final row.
        for section in self._sections:
            section_layout = section.layout()
            last_widget = section_layout.itemAt(section_layout.count() - 1).widget()
            if last_widget is not None and last_widget.objectName() == "settingsRow":
                margins = last_widget.layout().contentsMargins()
                last_widget.layout().setContentsMargins(
                    margins.left(), margins.top(), margins.right(), 0
                )

        self.detail_layout.addStretch(1)
        self.detail_scroll.setWidget(self.detail_contents)

        root_layout.addWidget(self.navigation, 2)
        root_layout.addWidget(self.detail_scroll, 8)

    def _create_section(self, title, description):
        section = QFrame()
        section.setObjectName("settingsSection")
        section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(0)

        title_label = QLabel(title)
        title_label.setObjectName("settingsSectionTitle")
        layout.addWidget(title_label)
        layout.addSpacing(3)

        description_label = QLabel(description)
        description_label.setObjectName("settingsSectionDescription")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        layout.addSpacing(6)

        self.detail_layout.addWidget(section)
        self._sections.append(section)
        return section, layout

    @staticmethod
    def _add_setting_row(
        parent_layout,
        title,
        description,
        control,
        control_right_margin=0,
    ):
        row = QFrame()
        row.setObjectName("settingsRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        row_layout = QGridLayout(row)
        row_layout.setContentsMargins(0, 12, control_right_margin, 12)
        row_layout.setHorizontalSpacing(16)
        row_layout.setVerticalSpacing(2)
        row_layout.setColumnStretch(0, 1)

        label_type = AssociatedControlLabel if isinstance(control, QCheckBox) else QLabel
        title_label = label_type(title)
        title_label.setObjectName("settingsRowTitle")
        description_label = label_type(description)
        description_label.setObjectName("settingsRowDescription")
        description_label.setWordWrap(True)

        if isinstance(control, QCheckBox):
            title_label.activated.connect(control.click)
            description_label.activated.connect(control.click)

        control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row_layout.addWidget(title_label, 0, 0)
        row_layout.addWidget(description_label, 1, 0)
        row_layout.addWidget(
            control,
            0,
            1,
            2,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        parent_layout.addWidget(row)
        row.title_label = title_label
        row.description_label = description_label
        return row

    def _apply_config(self):
        general = self.config["general"]
        self.minimize_checkbox.setChecked(general["minimize_enabled"])
        self.program_launch_checkbox.setChecked(
            general["program_launch_task_enabled"]
        )
        self.runtime_edit_checkbox.setChecked(
            general["allow_option_edits_while_running"]
        )
        self.clear_log_checkbox.setChecked(general["clear_log_on_start"])

        controller_index = self._find_controller_index(self.config["controller"])
        if controller_index >= 0:
            self.controller_combo.setCurrentIndex(controller_index)
        self._confirmed_manual_path = self.config["program"]["manual_path"]
        self.program_path_input.setText(self._confirmed_manual_path)
        self._refresh_program_status()

        theme = self.config["appearance"]["theme"]
        theme_index = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 1)

        self._update_controller_details()

    def _find_controller_index(self, saved_controller):
        if not isinstance(saved_controller, dict):
            return 0 if self.controllers else -1

        saved_name = saved_controller.get("name")
        if isinstance(saved_name, str):
            for index, controller in enumerate(self.controllers):
                if controller.get("name") == saved_name:
                    return index

        saved_win32 = saved_controller.get("win32")
        if not isinstance(saved_win32, dict):
            return 0 if self.controllers else -1
        requested = {
            method: saved_win32[method]
            for method in WIN32_METHOD_PRIORITY
            if isinstance(saved_win32.get(method), str) and saved_win32[method]
        }
        for index, controller in enumerate(self.controllers):
            if controller.get("type") != "Win32":
                continue
            win32_config = controller["win32"]
            if requested and all(
                win32_config.get(method, WIN32_METHOD_DEFAULTS[method]) == value
                for method, value in requested.items()
            ):
                return index
        return 0 if self.controllers else -1

    def _connect_controls(self):
        self.navigation.currentRowChanged.connect(self._scroll_to_section)
        self.detail_scroll.verticalScrollBar().valueChanged.connect(
            self._sync_navigation_to_scroll
        )
        self.minimize_checkbox.toggled.connect(self._on_minimize_changed)
        self.program_launch_checkbox.toggled.connect(
            self._on_program_launch_enabled_changed
        )
        self.runtime_edit_checkbox.toggled.connect(self._on_runtime_edit_changed)
        self.clear_log_checkbox.toggled.connect(self._on_clear_log_changed)
        self.program_browse_button.clicked.connect(self._browse_program_path)
        self.program_apply_button.clicked.connect(self._apply_program_path)
        self.controller_combo.currentIndexChanged.connect(
            self._on_controller_changed
        )
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.navigation.setCurrentRow(0)

    def _scroll_to_section(self, row):
        if self._syncing_navigation or not 0 <= row < len(self._sections):
            return
        section = self._sections[row]
        # Keep an explicit selection even when scrolling to it is clamped.
        self._syncing_navigation = True
        try:
            self.detail_scroll.verticalScrollBar().setValue(section.y())
        finally:
            self._syncing_navigation = False

    def _sync_navigation_to_scroll(self, value):
        if self._syncing_navigation or not self._sections:
            return
        # A partially visible card is still the topmost visible section.
        active_row = len(self._sections) - 1
        for index, section in enumerate(self._sections):
            if section.y() + section.height() > value:
                active_row = index
                break

        if self.navigation.currentRow() == active_row:
            return
        self._syncing_navigation = True
        self.navigation.setCurrentRow(active_row)
        self._syncing_navigation = False

    def _collect_config(self):
        return {
            "general": {
                "minimize_enabled": self.minimize_checkbox.isChecked(),
                "program_launch_task_enabled": (
                    self.program_launch_checkbox.isChecked()
                ),
                "allow_option_edits_while_running": (
                    self.runtime_edit_checkbox.isChecked()
                ),
                "clear_log_on_start": self.clear_log_checkbox.isChecked(),
            },
            "controller": SettingsStore.serialize_controller(
                self.controller_combo.currentData()
            ),
            "connection": normalize_connection_preferences(self.config.get("connection")),
            "monitor": normalize_screen_preferences(self.config.get("monitor")),
            "program": {
                **normalize_program_config(self.config.get("program")),
                "manual_path": self._confirmed_manual_path,
            },
            "appearance": {
                "theme": self.theme_combo.currentData() or "light",
            },
        }

    def add_connection_panel(self, panel):
        group = QFrame()
        group.setObjectName("settingsConnectionGroup")
        group.setProperty("connectionGroup", True)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(8)
        label = QLabel("연결 설정 · 사전 확인")
        label.setObjectName("settingsRowTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setMinimumHeight(24)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        panel.layout().setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(panel)
        group.title_label = label
        self._connection_group = group
        self._connection_layout.addSpacing(8)
        self._connection_layout.addWidget(group)

    def save_monitor_preferences(self, connection=None, screen=None):
        if connection is not None:
            self.config["connection"] = normalize_connection_preferences(connection)
        if screen is not None:
            self.config["monitor"] = normalize_screen_preferences(screen)
        self._save()

    def _save(self):
        self.config = self._collect_config()
        self.store.save(self.config)

    def _on_minimize_changed(self, enabled):
        self._save()
        self.minimize_changed.emit(enabled)

    def _on_program_launch_enabled_changed(self, enabled):
        self._save()
        self.program_launch_task_enabled_changed.emit(enabled)

    def _on_runtime_edit_changed(self, enabled):
        self._save()
        self.runtime_option_editing_changed.emit(enabled)

    def _on_clear_log_changed(self, _enabled):
        self._save()

    def _browse_program_path(self):
        adb = self.controller_settings().get("type") == "Adb"
        selected, _ = QFileDialog.getOpenFileName(
            self, "앱플레이어 실행 파일 선택" if adb else "프로그램 실행 파일 선택", "", "실행 파일 (*.exe)"
        )
        if selected:
            self.program_path_input.setText(f'"{selected}"')

    def _apply_program_path(self):
        if self._confirmed_manual_path or self._manual_path_error_active:
            self._confirmed_manual_path = ""
            self._manual_path_error_active = False
            self.program_path_input.clear()
            self._save()
            self._refresh_program_status(animate=True)
            self.program_changed.emit(self.program_settings())
            return

        manual_path = self.program_path_input.text().strip()
        error = None
        if self.controller_settings().get("type") == "Adb":
            try:
                parse_manual_program_command(manual_path)
            except (OSError, ValueError) as exception:
                error = str(exception)
        elif manual_path and resolve_manual_program_path(manual_path) is None:
            error = "실행 파일을 확인할 수 없습니다. EXE 경로와 인수를 확인하세요."
        if error:
            self._manual_path_error_active = True
            self.program_apply_button.setText("초기화")
            self._set_status_label(
                self.program_active_status,
                error,
                False,
            )
            self._set_program_active_status_visible(True, animate=True)
            self.program_changed.emit(self.program_settings())
            return

        self._confirmed_manual_path = manual_path
        self._manual_path_error_active = False
        self._save()
        self._refresh_program_status(animate=True)
        self.program_changed.emit(self.program_settings())

    @staticmethod
    def _refresh_status_style(label):
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _set_status_label(self, label, text, is_valid):
        if label.text() == text and label.property("pathValid") == is_valid:
            return
        label.setText(text)
        label.setProperty("pathValid", is_valid)
        self._refresh_status_style(label)

    def _set_program_active_status_visible(self, visible, animate=False):
        container = self.program_active_status_container
        opacity_effect = self.program_active_status_effect
        if self._program_status_animation is not None:
            self._program_status_animation.stop()
            self._program_status_animation.deleteLater()
            self._program_status_animation = None

        if not animate or not self.isVisible():
            container.setVisible(visible)
            opacity_effect.setOpacity(1.0)
            container.updateGeometry()
            return

        if visible:
            if not container.isVisible():
                opacity_effect.setOpacity(0.0)
                container.show()
            start_opacity = opacity_effect.opacity()
            target_opacity = 1.0
        else:
            if not container.isVisible():
                opacity_effect.setOpacity(1.0)
                return
            start_opacity = opacity_effect.opacity()
            target_opacity = 0.0

        # 레이아웃 높이는 매 프레임 바꾸지 않고 새 영역만 페이드하여
        # 기존 설정 카드들이 반복해서 다시 그려지는 현상을 방지한다.
        animation = QPropertyAnimation(opacity_effect, b"opacity", self)
        animation.setDuration(140)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.setStartValue(start_opacity)
        animation.setEndValue(target_opacity)

        def finish_transition():
            if not visible:
                container.hide()
            opacity_effect.setOpacity(1.0)
            container.updateGeometry()
            if self._program_status_animation is animation:
                self._program_status_animation = None
            animation.deleteLater()

        animation.finished.connect(finish_transition)
        self._program_status_animation = animation
        animation.start()

    def _refresh_program_status(self, animate=False):
        config = {
            **normalize_program_config(self.config.get("program")),
            "manual_path": self._confirmed_manual_path,
            "controller": self.controller_settings(),
        }
        has_manual_path = bool(self._confirmed_manual_path)
        show_active_status = has_manual_path or self._manual_path_error_active
        self.program_apply_button.setText(
            "초기화" if show_active_status else "확인"
        )
        adb = self.controller_settings().get("type") == "Adb"
        self.program_path_row.description_label.setText(ADB_MANUAL_PATH_DESCRIPTION if adb else WIN32_MANUAL_PATH_DESCRIPTION)
        self._update_program_description_height()
        self.program_path_input.setPlaceholderText('"앱플레이어 실행 파일.exe" 실행 속성' if adb else '"실행 파일 경로.exe" 인수')
        self.program_auto_status.setEnabled(not adb)
        auto_path = None if adb else find_auto_program_executable(config)
        self._auto_program_path = auto_path
        if adb:
            self._set_status_label(self.program_auto_status, "자동 경로를 사용할 수 없습니다.", None)
        elif auto_path is None:
            self._set_status_label(
                self.program_auto_status,
                "자동 검색: 대상을 확정하지 못했습니다. 수동 경로를 지정하세요.",
                False,
            )
        else:
            self._set_status_label(
                self.program_auto_status,
                f"자동 검색: {auto_path}" + (" (Steam 설치 폴더)" if auto_path.is_dir() else ""),
                True,
            )

        if self._manual_path_error_active:
            self._set_program_active_status_visible(True, animate)
            return
        if not has_manual_path and not adb:
            # 접히는 동안 마지막 수동 경로 상태를 유지해 색상과 문구가 튀지 않게 한다.
            self._set_program_active_status_visible(False, animate)
            return

        active_path = self.program_settings().get("resolved_path")
        if not active_path:
            self._set_status_label(
                self.program_active_status,
                "사용할 실행 파일이 없습니다. 작업 목록의 자동 실행 작업이 비활성화됩니다.",
                False,
            )
        else:
            self._set_status_label(
                self.program_active_status,
                f"사용 경로: {active_path}",
                True,
            )
        self._set_program_active_status_visible(True, animate)

    def _update_program_description_height(self):
        label = self.program_path_row.description_label
        label.setMinimumHeight(max(0, label.heightForWidth(max(1, label.width()))))

    def eventFilter(self, watched, event):
        if (hasattr(self, "program_path_row") and watched is self.program_path_row.description_label
                and event.type() in (QEvent.Type.Resize, QEvent.Type.FontChange)):
            self._update_program_description_height()
        return super().eventFilter(watched, event)

    def _on_controller_changed(self, _index):
        self._update_controller_details()
        self._manual_path_error_active = False
        self._refresh_program_status()
        self._save()
        self.controller_changed.emit(self.controller_settings())
        self.program_changed.emit(self.program_settings())

    def _on_theme_changed(self, _index):
        self._save()
        self.theme_changed.emit(self.theme())

    def _update_controller_details(self):
        controller = self.controller_combo.currentData()
        if not isinstance(controller, dict):
            self.controller_details.setText("선택할 수 있는 컨트롤러가 없습니다.")
            return
        if controller.get("type") == "Adb":
            self.controller_details.setText(f"ID: {controller['name']}  ·  ADB 기기 화면 캡처 및 입력")
            return
        win32_config = controller.get("win32", {})
        values = {
            method: win32_config.get(method, WIN32_METHOD_DEFAULTS[method])
            for method in WIN32_METHOD_PRIORITY
        }
        self.controller_details.setText(
            f"ID: {controller['name']}  ·  캡처: {values['screencap']}  ·  "
            f"마우스: {values['mouse']}  ·  키보드: {values['keyboard']}"
        )

    def minimize_enabled(self):
        return self.minimize_checkbox.isChecked()

    def set_minimize_enabled(self, enabled):
        self.minimize_checkbox.setChecked(bool(enabled))

    def program_launch_task_enabled(self):
        return self.program_launch_checkbox.isChecked()

    def runtime_option_editing_enabled(self):
        return self.runtime_edit_checkbox.isChecked()

    def clear_log_on_start_enabled(self):
        return self.clear_log_checkbox.isChecked()

    def theme(self):
        return self.theme_combo.currentData() or "light"

    def controller_settings(self):
        return SettingsStore.serialize_controller(
            self.controller_combo.currentData()
        )

    def program_settings(self):
        config = {
            **normalize_program_config(self.config.get("program")),
            "manual_path": self._confirmed_manual_path,
            "controller": self.controller_settings(),
        }
        adb = self.controller_settings().get("type") == "Adb"
        config["manual_only"] = adb
        config["connection"] = normalize_connection_preferences(self.config.get("connection"))
        if adb:
            try:
                resolved_path, arguments = parse_manual_program_command(self._confirmed_manual_path)
                config["launch_arguments"] = arguments
            except (OSError, ValueError):
                resolved_path = None
                config["launch_arguments"] = []
        else:
            if self._confirmed_manual_path:
                resolved_path = find_program_executable(config)
            else:
                # Discovery runs on status/controller refresh, not every snapshot/FPS/log event.
                resolved_path = getattr(self, "_auto_program_path", None)
                if resolved_path and not (resolved_path.is_file() or resolved_path.is_dir()):
                    resolved_path = None
            config["launch_arguments"] = []
            if self._confirmed_manual_path and resolved_path:
                try:
                    _, config["launch_arguments"] = parse_manual_program_command(self._confirmed_manual_path)
                except (OSError, ValueError):
                    pass  # Existing unquoted EXE paths and single-EXE folders have no arguments.
        if self._manual_path_error_active:
            resolved_path = None
            config["launch_arguments"] = []
        config["resolved_path"] = str(resolved_path) if resolved_path else ""
        return config
