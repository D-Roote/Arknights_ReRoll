from pathlib import Path
from datetime import datetime
from copy import deepcopy
from enum import Enum
from uuid import uuid4
import base64
import ctypes
import json
import re
import sys

from ctypes import wintypes

from PySide6.QtCore import QByteArray, QDir, QEvent, QMimeData, QModelIndex, QObject, QPoint, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QTextCursor,
                           QColor, QCursor, QDrag, QIcon, QPainter, QPen, QPixmap)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (QApplication, QMainWindow, QAbstractItemView,
                               QHBoxLayout, QVBoxLayout,
                               QFrame, QListWidget, QListWidgetItem, QSizePolicy,
                               QToolButton, QWidget, QSplitter, QSplitterHandle,
                               QButtonGroup, QCheckBox, QLabel, QLineEdit,
                               QListView, QStyledItemDelegate,
                               QFileDialog, QPushButton, QRadioButton, QStyle,
                               QStyleOptionSlider)

from app.runtime import AppRuntime, PROGRAM_LAUNCH_ENTRY
from app.controls import PopupOnlyWheelComboBox
from app.settingsUI import AssociatedControlLabel, SettingsPanel
from app.monitorUI import MonitorCoordinator
from app.extraFeaturesUI import ExtraFeaturesPanel
from app.multiExecutionUI import MultiExecutionPanel
from app.afterActions import AfterActionPreferences, WindowsAfterActionBackend, capture_window_target
from app.afterActionUI import AfterActionPanel


WINDOW_SIZE = [1200, 800]
WINDOW_TITLE = "MAA_Blue Archive"
UI_FILENAME = "baseUI.ui"
QSS_FILENAME = "style.qss"
SETTINGS_QSS_FILENAME = "settings.qss"
DARK_QSS_FILENAME = "dark.qss"
APP_DIR = Path(__file__).resolve().parent
UI_DIR = APP_DIR / "pySide6"
UI_RESOURCE_DIR = APP_DIR / "resources"
SETTINGS_ICON_PATH = UI_RESOURCE_DIR / "icons/actions/settings.svg"
LOG_MENU_EXPAND_ICON_PATH = UI_RESOURCE_DIR / "icons/actions/chevron-left.svg"
LOG_MENU_COLLAPSE_ICON_PATH = UI_RESOURCE_DIR / "icons/actions/chevron-right.svg"
SETTINGS_ICON_SIZE = QSize(20, 20)
SETTINGS_ICON_HOVER_SIZE = QSize(24, 24)
RESET_ICON_SIZE = QSize(18, 18)
RESET_ICON_HOVER_SIZE = QSize(22, 22)
COMPACT_SCROLLBAR_WIDTH = 2
EXPANDED_SCROLLBAR_WIDTH = 5
SCROLLBAR_ACTIVITY_TIMEOUT_MS = 700
LOG_ACTION_MENU_CLOSE_DELAY_MS = 700
LOG_ACTION_MENU_ICON_SIZE = QSize(16, 16)
TASK_SETTINGS_TRAILING_GAP = 4
PROGRAM_LAUNCH_TASK_NAME = "__ProgramLaunch"
PROGRAM_LAUNCH_TASK = {
    "name": PROGRAM_LAUNCH_TASK_NAME,
    "label": "자동 실행",
    "default_check": True,
    "entry": PROGRAM_LAUNCH_ENTRY,
    "builtin": True,
    "requires_program": True,
}


RESULT_ERROR_PREFIXES = (
    "Runtime에서 예기치 않은 오류가 발생했습니다: ",
    "Runtime 초기화 중 오류가 발생했습니다: ",
    "Runtime 정리 중 오류가 발생했습니다: ",
    "작업 중지 중 오류가 발생했습니다: ",
    "정리 중 ",
)


def distinct_result_message(message, seen=None):
    """Only final diagnostics: never discard repeated pipeline/progress logs."""
    seen = set() if seen is None else seen
    lines = []
    for line in message.splitlines():
        key = line.strip()
        while True:
            prefix = next((p for p in RESULT_ERROR_PREFIXES if key.startswith(p)), None)
            if prefix is None:
                break
            key = key[len(prefix):].strip()
        if key and key not in seen:
            seen.add(key)
            lines.append(line)
    return "\n".join(lines)


class TitleBarTheme(str, Enum):
    """애플리케이션 전체와 제목 표시줄에 적용하는 색상 모드."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWM_COLOR_DEFAULT = 0xFFFFFFFF
LIGHT_CAPTION_COLOR = 0x00FFFFFF
LIGHT_CAPTION_TEXT_COLOR = 0x00000000
DARK_CAPTION_COLOR = 0x00382217
DARK_CAPTION_TEXT_COLOR = 0x00F9F5F1


def resolve_effective_theme(theme, system_color_scheme=Qt.ColorScheme.Unknown):
    """설정값과 시스템 색상 모드로 실제 애플리케이션 테마를 결정한다."""
    theme = TitleBarTheme(theme)
    if theme != TitleBarTheme.SYSTEM:
        return theme
    if system_color_scheme == Qt.ColorScheme.Dark:
        return TitleBarTheme.DARK
    return TitleBarTheme.LIGHT


def _create_dwmapi():
    if sys.platform != "win32":
        return None

    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError:
        return None

    dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        wintypes.LPCVOID,
        wintypes.DWORD,
    ]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    return dwmapi


def apply_windows_title_bar_theme(
    hwnd,
    theme,
    dwmapi=None,
    system_color_scheme=Qt.ColorScheme.Unknown,
):
    """Windows 제목 표시줄 테마를 적용하고 지원 여부를 반환한다."""
    theme = TitleBarTheme(theme)
    if sys.platform != "win32" or not hwnd:
        return False

    dwmapi = dwmapi or _create_dwmapi()
    if dwmapi is None:
        return False

    effective_theme = resolve_effective_theme(theme, system_color_scheme)
    dark_mode = wintypes.BOOL(effective_theme == TitleBarTheme.DARK)
    if theme == TitleBarTheme.LIGHT:
        caption_color = wintypes.DWORD(LIGHT_CAPTION_COLOR)
        text_color = wintypes.DWORD(LIGHT_CAPTION_TEXT_COLOR)
    elif theme == TitleBarTheme.DARK:
        caption_color = wintypes.DWORD(DARK_CAPTION_COLOR)
        text_color = wintypes.DWORD(DARK_CAPTION_TEXT_COLOR)
    else:
        caption_color = wintypes.DWORD(DWM_COLOR_DEFAULT)
        text_color = wintypes.DWORD(DWM_COLOR_DEFAULT)

    result = dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_USE_IMMERSIVE_DARK_MODE,
        ctypes.byref(dark_mode),
        ctypes.sizeof(dark_mode),
    )

    # 색상 속성은 Windows 11부터 지원된다. 미지원 환경에서는 위의 테마 속성만 사용한다.
    for attribute, value in (
        (DWMWA_CAPTION_COLOR, caption_color),
        (DWMWA_TEXT_COLOR, text_color),
    ):
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            attribute,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )

    return result == 0


def merge_pipeline_override(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_pipeline_override(target[key], value)
        else:
            target[key] = deepcopy(value)


def convert_input_value(input_config, value):
    pipeline_type = input_config.get("pipeline_type", "string")
    if pipeline_type == "string":
        return value
    if pipeline_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("정수를 입력해 주세요.") from error
    if pipeline_type == "bool":
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        raise ValueError("true, false, 1, 0 중 하나를 입력해 주세요.")
    raise ValueError(f"지원하지 않는 pipeline_type입니다: {pipeline_type}")


def validate_input_value(input_config, value):
    verify_pattern = input_config.get("verify")
    if verify_pattern:
        try:
            if re.fullmatch(verify_pattern, value) is None:
                return False, input_config.get("pattern_msg", "입력 형식이 올바르지 않습니다.")
        except re.error as error:
            return False, f"검증 정규식이 올바르지 않습니다: {error}"

    try:
        convert_input_value(input_config, value)
    except ValueError as error:
        return False, str(error)
    return True, ""


def substitute_input_placeholders(value, converted_values):
    if isinstance(value, dict):
        return {
            key: substitute_input_placeholders(child, converted_values)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [substitute_input_placeholders(child, converted_values) for child in value]
    if not isinstance(value, str):
        return deepcopy(value)

    exact_match = re.fullmatch(r"\{([^{}]+)\}", value)
    if exact_match and exact_match.group(1) in converted_values:
        return deepcopy(converted_values[exact_match.group(1)])

    def replace_placeholder(match):
        name = match.group(1)
        if name not in converted_values:
            return match.group(0)
        replacement = converted_values[name]
        if isinstance(replacement, bool):
            return "true" if replacement else "false"
        return str(replacement)

    return re.sub(r"\{([^{}]+)\}", replace_placeholder, value)


def build_input_pipeline_override(option_config, input_values):
    converted_values = {}
    for input_config in option_config.get("inputs", []):
        input_name = input_config.get("name")
        if not input_name:
            continue
        value = str(input_values.get(input_name, input_config.get("default", "")))
        is_valid, validation_message = validate_input_value(input_config, value)
        if not is_valid:
            raise ValueError(f"{input_name}: {validation_message}")
        converted_values[input_name] = convert_input_value(input_config, value)

    return substitute_input_placeholders(
        option_config.get("pipeline_override", {}), converted_values
    )


def find_switch_cases(cases):
    yes_names = {"yes", "y"}
    no_names = {"no", "n"}
    yes_case_name = None
    no_case_name = None
    for case in cases:
        name = case.get("name", "")
        if name.lower() in yes_names:
            yes_case_name = name
        elif name.lower() in no_names:
            no_case_name = name
    return yes_case_name, no_case_name


class SettingsIconHoverFilter(QObject):
    """설정 아이콘 버튼의 호버 크기 변경을 공통 처리한다."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Enter:
            watched.setIconSize(SETTINGS_ICON_HOVER_SIZE)
        elif event.type() == QEvent.Type.Leave:
            watched.setIconSize(SETTINGS_ICON_SIZE)
        return super().eventFilter(watched, event)


class ResetIconHoverFilter(QObject):
    """초기화 버튼의 히트박스는 유지하고 호버 시 아이콘만 확대한다."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Enter:
            watched.setIconSize(RESET_ICON_HOVER_SIZE)
        elif event.type() == QEvent.Type.Leave:
            watched.setIconSize(RESET_ICON_SIZE)
        return super().eventFilter(watched, event)


class TaskFooterHoverFilter(QObject):
    """두 버튼을 하나의 작업 영역처럼 호버 표시한다."""

    def __init__(self, footer, watched_widgets):
        super().__init__(footer)
        self.footer = footer
        for widget in watched_widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Enter:
            self._set_hovered(True)
        elif event.type() == QEvent.Type.Leave:
            QTimer.singleShot(0, self._sync_hovered)
        return super().eventFilter(watched, event)

    def _sync_hovered(self):
        local_position = self.footer.mapFromGlobal(QCursor.pos())
        self._set_hovered(self.footer.rect().contains(local_position))

    def _set_hovered(self, hovered):
        if self.footer.property("groupHovered") == hovered:
            return
        self.footer.setProperty("groupHovered", hovered)
        self.footer.style().unpolish(self.footer)
        self.footer.style().polish(self.footer)
        self.footer.update()


class WorkspaceSplitterHandlePaintFilter(QObject):
    """Keep the resize hit area, showing a rounded divider only on hover."""

    def __init__(self, handle):
        super().__init__(handle)
        self.handle = handle
        self._hovered = False

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            self._hovered = event.type() == QEvent.Type.Enter
            self.handle.update()
        elif event.type() == QEvent.Type.Paint:
            painter = QPainter(self.handle)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            dark = (
                getattr(self.handle.window(), "_effective_theme", TitleBarTheme.LIGHT)
                == TitleBarTheme.DARK
            )
            painter.fillRect(self.handle.rect(), QColor("#111A2B" if dark else "#F4F7FB"))
            if self._hovered:
                rect = QRectF(
                    (self.handle.width() - 4) / 2, 12,
                    4, max(0, self.handle.height() - 24),
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#30415E" if dark else "#DFE7F0"))
                painter.drawRoundedRect(rect, 2, 2)
            painter.end()
            return True
        return super().eventFilter(watched, event)


class CenteredOptionDelegate(QStyledItemDelegate):
    """Use normal list rows rather than the native combo menu rendering."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = (
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(34, size.height()))
        return size


class RoundedScrollBarPaintFilter(QObject):
    """Paint a pill-shaped handle because narrow Qt handles ignore QSS radius."""

    def __init__(self, scroll_bar, contextual=False, popup=False):
        super().__init__(scroll_bar)
        self.scroll_bar = scroll_bar
        self.contextual = bool(contextual)
        self.popup = bool(popup)

    def eventFilter(self, watched, event):
        if watched is self.scroll_bar and event.type() == QEvent.Type.Paint:
            self._paint()
            return True
        return super().eventFilter(watched, event)

    def _is_dark_theme(self):
        ancestor = self.scroll_bar
        while ancestor is not None:
            if hasattr(ancestor, "_effective_theme"):
                return ancestor._effective_theme == TitleBarTheme.DARK
            ancestor = ancestor.parentWidget()
        return False

    def _surface_color(self):
        if self.popup:
            return QColor("#1E2D46" if self._is_dark_theme() else "#FFFFFF")
        if self.contextual:
            return QColor("#172238" if self._is_dark_theme() else "#F8FAFC")
        return QColor("#111A2B" if self._is_dark_theme() else "#F4F7FB")

    def _handle_color(self):
        return QColor("#168FBE" if self._is_dark_theme() else "#00AEEF")

    def _slider_rect(self):
        option = QStyleOptionSlider()
        self.scroll_bar.initStyleOption(option)
        slider_rect = self.scroll_bar.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            option,
            QStyle.SubControl.SC_ScrollBarSlider,
            self.scroll_bar,
        )
        if self.contextual:
            left_inset = (
                0
                if self.scroll_bar.property("contextualExpanded")
                else EXPANDED_SCROLLBAR_WIDTH - COMPACT_SCROLLBAR_WIDTH - 1
            )
            slider_rect.adjust(left_inset, 0, -1, 0)
        return slider_rect

    def _paint(self):
        painter = QPainter(self.scroll_bar)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.scroll_bar.rect(), self._surface_color())

        should_draw = self.scroll_bar.maximum() > self.scroll_bar.minimum()
        if self.contextual:
            should_draw = should_draw and bool(
                self.scroll_bar.property("contextualVisible")
            )
        if should_draw:
            slider_rect = QRectF(self._slider_rect())
            if slider_rect.width() > 0 and slider_rect.height() > 0:
                radius = min(slider_rect.width(), slider_rect.height()) / 2
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._handle_color())
                painter.drawRoundedRect(slider_rect, radius, radius)
        painter.end()


def setup_rounded_vertical_scrollbar(scroll_area, contextual=False, popup=False):
    scroll_bar = scroll_area.verticalScrollBar()
    scroll_bar._rounded_paint_filter = RoundedScrollBarPaintFilter(
        scroll_bar, contextual=contextual, popup=popup
    )
    scroll_bar.installEventFilter(scroll_bar._rounded_paint_filter)


class ContextualScrollBarController(QObject):
    """Show a compact scrollbar only while its start-page area is in use."""

    def __init__(self, scroll_area):
        super().__init__(scroll_area)
        self.scroll_area = scroll_area
        self.viewport = scroll_area.viewport()
        self.scroll_bar = scroll_area.verticalScrollBar()
        self._activity_active = False
        self._pointer_pressed = False
        self._activity_timer = QTimer(self)
        self._activity_timer.setSingleShot(True)
        self._activity_timer.setInterval(SCROLLBAR_ACTIVITY_TIMEOUT_MS)
        self._activity_timer.timeout.connect(self._finish_activity)

        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll_bar.setFixedWidth(EXPANDED_SCROLLBAR_WIDTH)
        self.scroll_bar.setProperty("contextual", True)
        self.scroll_bar.setProperty("contextualVisible", False)
        self.scroll_bar.setProperty("contextualExpanded", False)
        for widget in (scroll_area, self.viewport, self.scroll_bar):
            widget.installEventFilter(self)
        self.scroll_bar.rangeChanged.connect(self._schedule_sync)
        self._refresh_style()

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.Wheel:
            self._begin_activity()
        elif watched is self.scroll_bar and event_type == QEvent.Type.MouseButtonPress:
            self._pointer_pressed = True
            self._begin_activity(force_expanded=True)
        elif watched is self.scroll_bar and event_type == QEvent.Type.MouseButtonRelease:
            self._pointer_pressed = False
            self._begin_activity()
        elif event_type == QEvent.Type.Enter:
            if watched is self.scroll_bar:
                self._set_state(self._has_scroll_range(), True)
            else:
                self._set_state(self._has_scroll_range(), False)
        elif event_type == QEvent.Type.Leave:
            self._schedule_sync()
        return super().eventFilter(watched, event)

    @staticmethod
    def _contains_global_position(widget, global_position):
        return widget.rect().contains(widget.mapFromGlobal(global_position))

    def _has_scroll_range(self):
        return self.scroll_bar.maximum() > self.scroll_bar.minimum()

    def _begin_activity(self, force_expanded=False):
        self._activity_active = True
        self._activity_timer.start()
        expanded = force_expanded or self._pointer_pressed or self.scroll_bar.underMouse()
        self._set_state(self._has_scroll_range(), expanded)

    def _finish_activity(self):
        self._activity_active = False
        self._sync_state()

    def _schedule_sync(self, *_args):
        QTimer.singleShot(0, self._sync_state)

    def _sync_state(self):
        if not self._has_scroll_range():
            self._set_state(False, False)
            return

        global_position = QCursor.pos()
        pointer_in_area = self._contains_global_position(
            self.scroll_area, global_position
        )
        pointer_on_scrollbar = self._contains_global_position(
            self.scroll_bar, global_position
        )
        visible = (
            pointer_in_area
            or self._activity_active
            or self._pointer_pressed
            or self.scroll_bar.isSliderDown()
        )
        expanded = visible and (
            pointer_on_scrollbar
            or self._pointer_pressed
            or self.scroll_bar.isSliderDown()
        )
        self._set_state(visible, expanded)

    def _set_state(self, visible, expanded):
        visible = bool(visible)
        expanded = bool(visible and expanded)
        if (
            self.scroll_bar.property("contextualVisible") == visible
            and self.scroll_bar.property("contextualExpanded") == expanded
        ):
            return
        self.scroll_bar.setProperty("contextualVisible", visible)
        self.scroll_bar.setProperty("contextualExpanded", expanded)
        self._refresh_style()

    def _refresh_style(self):
        self.scroll_bar.style().unpolish(self.scroll_bar)
        self.scroll_bar.style().polish(self.scroll_bar)
        self.scroll_bar.update()


def setup_contextual_vertical_scrollbar(scroll_area):
    scroll_bar = scroll_area.verticalScrollBar()
    scroll_bar._contextual_controller = ContextualScrollBarController(scroll_area)
    setup_rounded_vertical_scrollbar(scroll_area, contextual=True)


class LogActionMenuController(QObject):
    """Expand log actions to the left and collapse after pointer leave."""

    def __init__(self, container, toggle_button, action_buttons):
        super().__init__(container)
        self.container = container
        self.toggle_button = toggle_button
        self.action_buttons = tuple(action_buttons)
        self._expand_icon = QIcon(str(LOG_MENU_EXPAND_ICON_PATH))
        self._collapse_icon = QIcon(str(LOG_MENU_COLLAPSE_ICON_PATH))
        self.toggle_button.setIconSize(LOG_ACTION_MENU_ICON_SIZE)
        self._expanded = False
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(LOG_ACTION_MENU_CLOSE_DELAY_MS)
        self._close_timer.timeout.connect(self._close_if_pointer_outside)

        for widget in (container, toggle_button, *self.action_buttons):
            widget.installEventFilter(self)
        toggle_button.clicked.connect(self.toggle)
        self.set_expanded(False)

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.Enter:
            self._close_timer.stop()
        elif event_type == QEvent.Type.Leave and self._expanded:
            QTimer.singleShot(0, self._start_close_if_pointer_outside)
        return super().eventFilter(watched, event)

    def _pointer_inside(self):
        local_position = self.container.mapFromGlobal(QCursor.pos())
        return self.container.rect().contains(local_position)

    def _start_close_if_pointer_outside(self):
        if self._expanded and not self._pointer_inside():
            self._close_timer.start()

    def _close_if_pointer_outside(self):
        if not self._pointer_inside():
            self.set_expanded(False)

    def toggle(self):
        self.set_expanded(not self._expanded)

    def is_expanded(self):
        return self._expanded

    def set_expanded(self, expanded):
        self._expanded = bool(expanded)
        if not self._expanded:
            self._close_timer.stop()
        for button in self.action_buttons:
            button.setVisible(self._expanded)
        self.toggle_button.setText("")
        self.toggle_button.setIcon(
            self._collapse_icon if self._expanded else self._expand_icon
        )
        self.toggle_button.setProperty("menuExpanded", self._expanded)
        self.toggle_button.setAccessibleName(
            "로그 작업 메뉴 접기" if self._expanded else "로그 작업 메뉴 펼치기"
        )
        self.toggle_button.style().unpolish(self.toggle_button)
        self.toggle_button.style().polish(self.toggle_button)
        self.toggle_button.update()
        self.container.layout().activate()
        self.container.updateGeometry()


class DeleteDropEventFilter(QObject):
    """삭제 영역 위에서 드래그 가능 커서를 유지하되 삭제는 목록이 처리한다."""

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            event.acceptProposedAction()
            return True
        if event.type() == QEvent.Type.Drop:
            event.ignore()
            return True
        return super().eventFilter(watched, event)


def setup_settings_icon_button(button):
    button.setIcon(QIcon(str(SETTINGS_ICON_PATH)))
    button.setIconSize(SETTINGS_ICON_SIZE)
    button._settings_icon_hover_filter = SettingsIconHoverFilter(button)
    button.installEventFilter(button._settings_icon_hover_filter)


class TaskSettingsButton(QPushButton):
    """클릭 영역은 유지하고 호버 시 아이콘만 확대하는 설정 버튼."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskSettingsButton")
        self.setFixedSize(30, 30)
        setup_settings_icon_button(self)


class TaskPickerPopup(QListWidget):
    task_selected = Signal(object)
    popup_hidden = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anchor_button = None
        self.setObjectName("taskPickerPopup")
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(False)
        self._dismiss_timer.setInterval(80)
        self._dismiss_timer.timeout.connect(self._hide_if_pointer_outside)
        self.itemClicked.connect(self._select_task)
        self.itemActivated.connect(self._select_task)

    def set_anchor_button(self, button):
        self._anchor_button = button

    def eventFilter(self, watched, event):
        if (
            self.isVisible()
            and self._anchor_button is not None
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            global_position = (
                event.globalPosition().toPoint()
                if hasattr(event, "globalPosition")
                else QCursor.pos()
            )
            if self._contains_global_position(
                self._anchor_button, global_position
            ):
                # Qt.Popup grabs outside clicks, so the receiver may be the popup
                # even when the pointer is over the anchor button. Consume that
                # press after closing to avoid both reopening and a stuck :pressed.
                self.hide()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        self._dismiss_timer.start()

    def hideEvent(self, event):
        self._dismiss_timer.stop()
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        if self._anchor_button is not None:
            self._anchor_button.setDown(False)
            self._anchor_button.update()
        super().hideEvent(event)
        self.popup_hidden.emit()

    @staticmethod
    def _contains_global_position(widget, global_position):
        return widget.rect().contains(widget.mapFromGlobal(global_position))

    def _hide_if_pointer_outside(self):
        if not self.isVisible():
            return
        global_position = QCursor.pos()
        if self._contains_global_position(self, global_position):
            return
        if self._anchor_button is not None and self._contains_global_position(
            self._anchor_button, global_position
        ):
            return
        self.hide()

    def show_above(self, anchor, task_list, tasks, width_reference=None):
        self.clear()
        task_row_height = task_list.sizeHintForRow(0)
        if task_row_height <= 0:
            task_row_height = 34
        for task in tasks:
            item = QListWidgetItem(task.get("label", task["name"]))
            item.setData(Qt.UserRole, task)
            item.setSizeHint(QSize(0, task_row_height))
            self.addItem(item)
        if not self.count():
            return

        self.ensurePolished()
        position = anchor.mapToGlobal(QPoint(0, 0))
        available_height = max(1, position.y() - anchor.screen().availableGeometry().top())
        viewport_chrome = max(0, self.height() - self.viewport().height())
        height = min(
            task_row_height * self.count() + viewport_chrome,
            task_list.height(),
            available_height,
        )
        width_reference = width_reference or task_list
        horizontal_position = width_reference.mapToGlobal(QPoint(0, 0))
        self.setFixedSize(width_reference.width(), height)
        self.move(horizontal_position.x(), position.y() - height)
        self.show()
        self.setFocus()
        # show/focus 과정에서 Qt가 첫 행을 current item으로 지정하므로 마지막에 해제한다.
        self.setCurrentRow(-1)
        self.clearSelection()

    def _select_task(self, item):
        task = item.data(Qt.UserRole)
        self.hide()
        self.task_selected.emit(task)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        if self.currentRow() < 0 and self.count():
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Home):
                self.setCurrentRow(0)
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_End):
                self.setCurrentRow(self.count() - 1)
                event.accept()
                return
        super().keyPressEvent(event)


# 동적 List 클래스
class OptionItemWidget(QWidget):
    def __init__(self, task_data, task_options, on_setting_clicked_callback, on_checkbox_toggled_callback, parent=None):
        super().__init__(parent)

        self.task_data = task_data      
        self.task_options = task_options 
        self._available = True
        self._locked = False
        
        self.selected_options = {}
        for opt_name, opt in self.task_options:
            opt_type = opt.get("type", "select")
            default_case = opt.get("default_case")

            if opt_type == "input":
                self.selected_options[opt_name] = {
                    input_config["name"]: str(input_config.get("default", ""))
                    for input_config in opt.get("inputs", [])
                    if input_config.get("name")
                }
            elif opt_type == "switch":
                yes_case_name, no_case_name = find_switch_cases(opt.get("cases", []))
                if default_case and default_case == yes_case_name:
                    self.selected_options[opt_name] = [yes_case_name]
                elif no_case_name is not None:
                    self.selected_options[opt_name] = [no_case_name]
                else:
                    self.selected_options[opt_name] = []
            elif opt_type == "select":
                case_names = [
                    case.get("name") for case in opt.get("cases", []) if case.get("name")
                ]
                if default_case in case_names:
                    self.selected_options[opt_name] = [default_case]
                elif case_names:
                    self.selected_options[opt_name] = [case_names[0]]
                else:
                    self.selected_options[opt_name] = []
            elif isinstance(default_case, list):
                self.selected_options[opt_name] = list(default_case)
            elif default_case:
                self.selected_options[opt_name] = [default_case]
            else:
                self.selected_options[opt_name] = []
        
        layout = QHBoxLayout(self)
        # 설정 아이콘은 30px 버튼 안에서 20px로 중앙 정렬되므로 우측 여백을
        # 0으로 두어 체크박스의 좌측 5px 라인과 시각적 끝을 맞춘다.
        layout.setContentsMargins(5, 2, 0, 2)
        layout.setSpacing(8)

        self.checkbox = QCheckBox("")
        self.checkbox.setFixedSize(30, 30)
        self.checkbox.toggled.connect(on_checkbox_toggled_callback)
        layout.addWidget(self.checkbox)

        display_name = task_data.get("label", task_data.get("name", "Unknown Task"))
        self.label = QLabel(display_name)
        self.label.setObjectName("taskItemLabel")
        self.label.setProperty("muted", False)

        layout.addWidget(self.label, 1) 

        self.setting_btn = TaskSettingsButton()
        self.setting_btn.setToolTip(f"{display_name} 세부 설정")
        self.setting_btn.setAccessibleName(f"{display_name} 세부 설정")
        self.checkbox.setAccessibleName(f"{display_name} 실행 선택")
        
        if self.task_options:
            layout.addWidget(self.setting_btn)
            layout.addSpacing(TASK_SETTINGS_TRAILING_GAP)
            self.setting_btn.clicked.connect(lambda: on_setting_clicked_callback(self))
        else:
            self.setting_btn.hide()

    def is_checked(self):
        return self._available and self.checkbox.isChecked()

    def set_available(self, available, reason=""):
        self._available = bool(available)
        if not self._available:
            self.checkbox.blockSignals(True)
            self.checkbox.setChecked(False)
            self.checkbox.blockSignals(False)
        self.setToolTip("" if self._available else reason)
        self.checkbox.setEnabled(self._available and not self._locked)
        self._set_label_muted(not self._available or self._locked)

    def _set_label_muted(self, muted):
        self.label.setProperty("muted", bool(muted))
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)
        self.label.update()

    def has_valid_input(self):
        for opt_name, opt in self.task_options:
            if opt.get("type", "select") != "input":
                continue

            input_values = self.selected_options.get(opt_name, {})
            if not isinstance(input_values, dict):
                return False
            for input_config in opt.get("inputs", []):
                input_name = input_config.get("name")
                if not input_name:
                    continue
                value = str(input_values.get(input_name, input_config.get("default", "")))
                if not validate_input_value(input_config, value)[0]:
                    return False
        return True

    def get_persisted_options(self):
        persisted_options = deepcopy(self.selected_options)
        for opt_name, opt in self.task_options:
            if opt.get("type", "select") != "input":
                continue
            input_values = persisted_options.get(opt_name)
            if not isinstance(input_values, dict):
                continue
            for input_config in opt.get("inputs", []):
                if input_config.get("password"):
                    input_values.pop(input_config.get("name"), None)
        return persisted_options

    def set_locked(self, locked: bool):
        self._locked = bool(locked)
        self.checkbox.setEnabled(self._available and not self._locked)
        # 실행 중에도 세부 설정 화면은 열 수 있도록 한다.
        self.setting_btn.setEnabled(True)
        self._set_label_muted(self._locked or not self._available)

# 커스텀 리스트 위젯
class DragDropListWidget(QListWidget):
    TASK_DRAG_MIME = "application/x-maaba-task-item"
    DRAG_LINE_MARGIN = 5
    DRAG_LINE_RIGHT_MARGIN = DRAG_LINE_MARGIN + TASK_SETTINGS_TRAILING_GAP
    drag_started = Signal()
    drag_finished = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDropIndicatorShown(False)
        self.drag_line_y = -1
        self.on_order_changed_callback = None
        self._locked = False
        self._dragged_item = None
        self._drop_before_item = None

    def set_locked(self, locked: bool):
        self._locked = locked
        self.setDragDropMode(
            QAbstractItemView.NoDragDrop if locked else QAbstractItemView.InternalMove
        )

    def startDrag(self, supported_actions):
        dragged_item = self.currentItem()
        if dragged_item is None or self._is_pinned_item(dragged_item):
            return

        indexes = self.selectedIndexes()
        mime_data = self.model().mimeData(indexes) if indexes else QMimeData()
        mime_data.setData(self.TASK_DRAG_MIME, b"1")
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        preview = self._create_drag_preview(dragged_item)
        drag.setPixmap(preview)
        cursor_position = self.viewport().mapFromGlobal(QCursor.pos())
        hotspot_x = max(
            8,
            min(
                preview.width() - 8,
                round(cursor_position.x() * preview.width() / max(1, self.viewport().width())),
            ),
        )
        drag.setHotSpot(QPoint(hotspot_x, preview.height() // 2))

        self._dragged_item = dragged_item
        self._drop_before_item = None
        dragged_item.setHidden(True)
        self.viewport().update()
        self.drag_started.emit()
        try:
            drag.exec(Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
        finally:
            if self.row(dragged_item) >= 0:
                dragged_item.setHidden(False)
            self.drag_line_y = -1
            self._dragged_item = None
            self._drop_before_item = None
            self.viewport().update()
            self.drag_finished.emit(dragged_item, QCursor.pos())

    def _create_drag_preview(self, item):
        item_widget = self.itemWidget(item)
        label = getattr(item_widget, "label", None)
        text = label.text() if label is not None else item.text()
        width = max(140, round(self.viewport().width() * 0.86))
        height = max(24, item.sizeHint().height() - 6)
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        background = self.palette().base().color()
        background.setAlpha(205)
        border = QColor("#00AEEF")
        border.setAlpha(220)
        foreground = self.palette().text().color()
        foreground.setAlpha(235)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(background)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 5, 5)
        painter.setPen(foreground)
        painter.setFont(label.font() if label is not None else self.font())
        text_rect = pixmap.rect().adjusted(12, 0, -12, 0)
        elided_text = painter.fontMetrics().elidedText(
            text,
            Qt.TextElideMode.ElideRight,
            text_rect.width(),
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_text,
        )
        painter.end()
        return pixmap

    def dragEnterEvent(self, event):
        super().dragEnterEvent(event)
        if self._is_internal_task_drag(event):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        if self._is_internal_task_drag(event):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            self._update_drop_target(event.position().toPoint())
            self.viewport().update()
            return

        if not event.isAccepted():
            self._clear_drop_indicator()

    def _is_internal_task_drag(self, event):
        return (
            event.source() is self
            and event.mimeData().hasFormat(self.TASK_DRAG_MIME)
        )

    def _visible_items(self):
        return [
            self.item(row)
            for row in range(self.count())
            if self.item(row) is not self._dragged_item
            and not self.item(row).isHidden()
        ]

    @staticmethod
    def _is_pinned_item(item):
        return (
            item is not None
            and item.data(Qt.ItemDataRole.UserRole) == PROGRAM_LAUNCH_TASK_NAME
        )

    def _update_drop_target(self, position):
        visible_items = [
            item for item in self._visible_items() if not self._is_pinned_item(item)
        ]
        if not visible_items:
            self._drop_before_item = None
            pinned_items = [
                self.item(row)
                for row in range(self.count())
                if self._is_pinned_item(self.item(row))
            ]
            self.drag_line_y = (
                self.visualItemRect(pinned_items[0]).bottom() + 1
                if pinned_items
                else 0
            )
            return

        first_item = visible_items[0]
        first_rect = self.visualItemRect(first_item)
        if position.y() <= first_rect.center().y():
            self._drop_before_item = first_item
            self.drag_line_y = first_rect.top()
            return

        for index, item in enumerate(visible_items):
            rect = self.visualItemRect(item)
            if position.y() <= rect.bottom():
                if position.y() < rect.center().y():
                    self._drop_before_item = item
                    self.drag_line_y = rect.top()
                else:
                    self._drop_before_item = (
                        visible_items[index + 1]
                        if index + 1 < len(visible_items)
                        else None
                    )
                    self.drag_line_y = rect.bottom() + 1
                return

        last_rect = self.visualItemRect(visible_items[-1])
        self._drop_before_item = None
        self.drag_line_y = last_rect.bottom() + 1

    def _clear_drop_indicator(self):
        self.drag_line_y = -1
        self._drop_before_item = None
        self.viewport().update()

    def dragLeaveEvent(self, event):
        self._clear_drop_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if self._is_internal_task_drag(event):
            self._update_drop_target(event.position().toPoint())
            moved = self._move_dragged_item(self._drop_before_item)
            self._clear_drop_indicator()
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            if moved and self.on_order_changed_callback:
                self.on_order_changed_callback()
            return

        self._clear_drop_indicator()

        widget_by_id = {}
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            instance_id = item.data(Qt.UserRole + 1)
            if widget is not None and instance_id is not None:
                widget_by_id[instance_id] = widget

        super().dropEvent(event)

        for i in range(self.count()):
            item = self.item(i)
            instance_id = item.data(Qt.UserRole + 1)
            if self.itemWidget(item) is None and instance_id in widget_by_id:
                widget = widget_by_id[instance_id]
                self.setItemWidget(item, widget)
                item.setSizeHint(widget.sizeHint())

        if self.on_order_changed_callback:
            self.on_order_changed_callback()

    def _move_dragged_item(self, before_item):
        dragged_item = self._dragged_item
        if dragged_item is None or self._is_pinned_item(dragged_item):
            return False
        source_row = self.row(dragged_item)
        if source_row < 0:
            return False

        destination_child = self.count() if before_item is None else self.row(before_item)
        if destination_child < 0:
            destination_child = self.count()
        pinned_rows = [
            row
            for row in range(self.count())
            if self._is_pinned_item(self.item(row))
        ]
        if pinned_rows:
            destination_child = max(destination_child, pinned_rows[0] + 1)
        if destination_child in (source_row, source_row + 1):
            return False

        # index widget의 소유권은 Qt가 관리하므로 분리/재연결하지 않고 행 자체를 옮긴다.
        moved = self.model().moveRow(
            QModelIndex(),
            source_row,
            QModelIndex(),
            destination_child,
        )
        if moved:
            self.setCurrentItem(dragged_item)
        return moved

    def paintEvent(self, event):
        super().paintEvent(event)
        
        if self.drag_line_y != -1:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.Antialiasing)
            
            pen = QPen(QColor("#00AEEF"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)

            # 2px 선의 중심이 경계 밖으로 나가지 않게 해 최상단에서도 두께를 보존한다.
            line_y = self._bounded_drag_line_y()
            line_start, line_end = self._drag_line_span()
            painter.drawLine(line_start, line_y, line_end, line_y)
            painter.end()

    def _bounded_drag_line_y(self):
        return max(1, min(self.viewport().height() - 2, self.drag_line_y))

    def _drag_line_span(self):
        return (
            self.DRAG_LINE_MARGIN,
            max(
                self.DRAG_LINE_MARGIN,
                self.viewport().width() - self.DRAG_LINE_RIGHT_MARGIN,
            ),
        )


class MonitorDragHandle(QLabel):
    """모니터링 섹션의 전용 손잡이에서 드래그를 시작한다."""

    def __init__(self, sections, section):
        super().__init__("⋮⋮", section)
        self.sections = sections
        self.section = section
        self.setObjectName("monitorDragHandle")
        self.setAccessibleName("모니터링 영역 순서 변경")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._press_position = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._press_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press_position).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._press_position = None
            self.sections.start_section_drag(self.section, self)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_position = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class MonitorVerticalHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hovered = False
        self.setAccessibleName("화면과 로그 높이 조절")
        self.setToolTip("드래그하여 펼쳐진 화면과 로그의 높이를 조절합니다")

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        if not self.isEnabled():
            return
        dark = getattr(self.window(), "_effective_theme", None) == TitleBarTheme.DARK
        color = "#00AEEF" if self._hovered else ("#405474" if dark else "#CBD5E0")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPoint(self.width() // 2 - 20, self.height() // 2),
                         QPoint(self.width() // 2 + 20, self.height() // 2))


class MonitorVerticalSplitter(QSplitter):
    def createHandle(self):
        return MonitorVerticalHandle(self.orientation(), self)


class MonitorSectionsWidget(QWidget):
    """작업 목록과 동일하게 내부 이동만 허용하는 세로 섹션 목록."""

    DRAG_MIME = "application/x-maaba-monitor-section"
    order_changed = Signal()
    sizes_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._dragged_section = None
        self._drag_source = None
        self._drop_before = None
        self.splitter = None
        self._height_weights = {"screen": 1, "log": 1}
        self._constraint_timer = QTimer(self)
        self._constraint_timer.setSingleShot(True)
        self._constraint_timer.timeout.connect(self.sync_section_layout)

    def sections(self):
        if self.splitter is not None:
            return [self.splitter.widget(index) for index in range(self.splitter.count())]
        layout = self.layout()
        if layout is None:
            return []
        return [
            layout.itemAt(index).widget()
            for index in range(layout.count())
            if layout.itemAt(index).widget() is not None
            and layout.itemAt(index).widget().property("monitorSectionKey")
        ]

    def section_order(self):
        return [section.property("monitorSectionKey") for section in self.sections()]

    def enable_resizing(self):
        cards = self.sections()
        layout = self.layout()
        for card in cards:
            layout.removeWidget(card)
        self.splitter = MonitorVerticalSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setObjectName("monitorVerticalSplitter")
        self.splitter.setHandleWidth(8)
        self.splitter.setChildrenCollapsible(False)
        for card in cards:
            self.splitter.addWidget(card)
            card.installEventFilter(self)
        layout.addWidget(self.splitter)
        self.splitter.splitterMoved.connect(self._remember_sizes)
        self.sync_section_layout()

    def eventFilter(self, obj, event):
        # Connection status can wrap to more lines; it remains content-sized.
        if obj.property("monitorSectionKey") == "connection" and event.type() == QEvent.Type.LayoutRequest:
            self._constraint_timer.start(0)
        return super().eventFilter(obj, event)

    def height_weights(self):
        return dict(self._height_weights)

    def restore_height_weights(self, value):
        if (isinstance(value, dict) and all(type(value.get(key)) is int and 0 < value[key] <= 100000
                                          for key in self._height_weights)):
            self._height_weights = {key: value[key] for key in self._height_weights}
            self.sync_section_layout()

    @staticmethod
    def _is_expanding(card):
        return (card.property("monitorSectionKey") in ("screen", "log")
                and card.property("monitorExpanded") and not card.isHidden())

    def _remember_sizes(self, _position, _index):
        expanding = [card for card in self.sections() if self._is_expanding(card)]
        if len(expanding) == 2:
            self._height_weights = {card.property("monitorSectionKey"): card.height() for card in expanding}
            self.sizes_changed.emit()

    def start_section_drag(self, section, source):
        if section not in self.sections():
            return
        drag = QDrag(source)
        mime_data = QMimeData()
        mime_data.setData(self.DRAG_MIME, b"1")
        drag.setMimeData(mime_data)
        preview = QPixmap(max(140, section.width() - 12), 36)
        preview.fill(Qt.GlobalColor.transparent)
        painter = QPainter(preview)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#E6F5FC"))
        painter.setPen(QPen(QColor("#00AEEF"), 1))
        painter.drawRoundedRect(preview.rect().adjusted(1, 1, -1, -1), 6, 6)
        painter.setPen(QColor("#1D3150"))
        painter.drawText(
            preview.rect().adjusted(12, 0, -12, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            section.property("monitorSectionTitle"),
        )
        painter.end()
        drag.setPixmap(preview)
        drag.setHotSpot(QPoint(preview.width() - 18, preview.height() // 2))

        self._dragged_section = section
        self._drag_source = source
        self._drop_before = None
        section.hide()
        self.sync_section_layout()
        try:
            drag.exec(Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
        finally:
            section.show()
            self.sync_section_layout()
            self._dragged_section = None
            self._drag_source = None
            self._clear_drop_target()

    def _is_internal_drag(self, event):
        return (
            self._dragged_section is not None
            and event.source() is self._drag_source
            and event.mimeData().hasFormat(self.DRAG_MIME)
        )

    def dragEnterEvent(self, event):
        if self._is_internal_drag(event):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._is_internal_drag(event):
            event.ignore()
            self._clear_drop_target()
            return
        self._update_drop_target(event.position().toPoint().y())
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event):
        self._clear_drop_target()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not self._is_internal_drag(event):
            event.ignore()
            self._clear_drop_target()
            return
        self._update_drop_target(event.position().toPoint().y())
        moved = self.move_section(self._dragged_section, self._drop_before)
        self._clear_drop_target()
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if moved:
            self.order_changed.emit()

    def _update_drop_target(self, y):
        # 숨긴 섹션을 제외한 실제 카드 위치로 삽입 대상을 결정한다.
        self.layout().activate()
        visible = [
            section for section in self.sections()
            if section is not self._dragged_section and not section.isHidden()
        ]
        for section in visible:
            if y < section.mapTo(self, QPoint()).y() + section.height() // 2:
                self._drop_before = section
                return
        self._drop_before = None

    def _clear_drop_target(self):
        self._drop_before = None

    def sync_section_layout(self):
        if self.splitter is not None:
            cards = self.sections()
            expanding = [card for card in cards if self._is_expanding(card)]
            fixed = {}
            for index, card in enumerate(cards):
                grows = card in expanding
                if grows:
                    card.setMaximumHeight(16777215)
                    card.setMinimumHeight(max(0, card.minimumSizeHint().height()))
                else:
                    height = max(0, card.sizeHint().height())
                    card.setFixedHeight(height)
                    fixed[index] = 0 if card.isHidden() else height
                self.splitter.setStretchFactor(index, 1 if grows else 0)
            for index in range(1, len(cards)):
                enabled = any(card in expanding for card in cards[:index]) and any(card in expanding for card in cards[index:])
                handle = self.splitter.handle(index)
                handle.setEnabled(enabled)
                handle.setCursor(Qt.CursorShape.SplitVCursor if enabled else Qt.CursorShape.ArrowCursor)
                handle.update()
            self.layout().setAlignment(Qt.AlignmentFlag(0) if expanding else Qt.AlignmentFlag.AlignTop)
            self.splitter.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Expanding if expanding else QSizePolicy.Policy.Maximum)
            self.splitter.setMaximumHeight(16777215 if expanding else sum(fixed.values()) + 8 * (len(cards) - 1))
            if expanding:
                available = max(sum(card.minimumHeight() for card in expanding),
                                self.splitter.height() - sum(fixed.values()) - 8 * (len(cards) - 1))
                total = sum(self._height_weights[card.property("monitorSectionKey")] for card in expanding)
                sizes = [round(available * self._height_weights[card.property("monitorSectionKey")] / total)
                         if card in expanding else fixed[index] for index, card in enumerate(cards)]
                self.splitter.setSizes(sizes)
            self.updateGeometry()
            return
        has_expanding_section = any(
            not section.isHidden()
            and section.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
            for section in self.sections()
        )
        self.layout().setAlignment(
            Qt.AlignmentFlag(0) if has_expanding_section else Qt.AlignmentFlag.AlignTop
        )

    def move_section(self, section, before_section=None):
        before_order = self.sections()
        if section not in before_order or (before_section is not None and before_section not in before_order):
            return False
        if before_section is section:
            return False
        if self.splitter is not None:
            remaining = [card for card in before_order if card is not section]
            destination = remaining.index(before_section) if before_section is not None else len(remaining)
            self.splitter.insertWidget(destination, section)
            self.sync_section_layout()
            return self.sections() != before_order
        layout = self.layout()
        layout.removeWidget(section)
        destination = layout.indexOf(before_section) if before_section is not None else layout.count()
        layout.insertWidget(destination, section)
        return self.sections() != before_order

# 메인 윈도우
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._ui_state_ready = False
        self._first_ui_show = True
        self._saved_ui_state = {}
        self._ui_save_timer = QTimer(self)
        self._ui_save_timer.setSingleShot(True)
        self._ui_save_timer.setInterval(300)
        self._ui_save_timer.timeout.connect(self.save_user_config)

        ui_path = UI_DIR / UI_FILENAME
        base_qss_paths = (UI_DIR / QSS_FILENAME, UI_DIR / SETTINGS_QSS_FILENAME)
        dark_qss_path = UI_DIR / DARK_QSS_FILENAME
        # QSS의 아이콘 경로도 작업 디렉토리와 무관하게 해석한다.
        QDir.setSearchPaths("maabaicons", [str(UI_RESOURCE_DIR / "icons")])
        loader = QUiLoader()
        loader.registerCustomWidget(DragDropListWidget)
        loader.registerCustomWidget(MonitorSectionsWidget)
        self.ui = loader.load(str(ui_path), self)
        if self.ui is None:
            raise RuntimeError(f"UI 파일을 불러오지 못했습니다: {ui_path}: {loader.errorString()}")

        setup_settings_icon_button(self.ui.endSettingBtn)
        
        self._setup_extra_features_ui()
        self._setup_workspace_navigation()
        self._setup_dashboard_layout()
        self._setup_after_action_footer()
        self.ui.mainPages.setCurrentWidget(self.ui.mainTab)

        qss_contents = []
        for qss_path in base_qss_paths:
            if qss_path.exists():
                with open(qss_path, "r", encoding="utf-8") as file:
                    qss_contents.append(file.read())
        self._base_style_sheet = "\n".join(qss_contents)
        self._dark_style_sheet = ""
        if dark_qss_path.exists():
            with open(dark_qss_path, "r", encoding="utf-8") as file:
                self._dark_style_sheet = file.read()
        self.setStyleSheet(self._base_style_sheet)
        setup_contextual_vertical_scrollbar(self.ui.taskOptionList)
        setup_contextual_vertical_scrollbar(self.ui.logPrintText)
        setup_rounded_vertical_scrollbar(self.ui.scrollSettingWidget)
        setup_rounded_vertical_scrollbar(self.extra_features_panel.detail_scroll)
        self.extra_features_panel.feature_page_added.connect(setup_rounded_vertical_scrollbar)
        self.log_action_menu_controller = LogActionMenuController(
            self.ui.logActionMenu,
            self.ui.logMenuToggleButton,
            (
                self.ui.logCopyButton,
                self.ui.logClearButton,
                self.ui.logSaveButton,
            ),
        )

        self.setCentralWidget(self.ui.centralwidget)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(WINDOW_SIZE[0], WINDOW_SIZE[1])
        self._title_bar_theme = TitleBarTheme.LIGHT
        self._effective_theme = TitleBarTheme.LIGHT
        self._style_hints = QApplication.styleHints()
        self._style_hints.colorSchemeChanged.connect(
            self.on_system_color_scheme_changed
        )

        self.runtime = AppRuntime()
        self.after_actions = AfterActionPreferences()
        self.after_action_backend = WindowsAfterActionBackend()
        self.after_action_panel = None
        self._run_after_actions = None
        self._run_completion_target = None
        self._run_succeeded = False
        self._run_stop_requested = False
        self._completion_pending = False
        self._deferred_system_action = ""
        self._closing = False
        try:
            saved = json.loads((self.runtime.user_dir / "config" / "user_config.json").read_text(encoding="utf-8"))
            state = saved.get("ui_state")
            self._saved_ui_state = state if isinstance(state, dict) else {}
            self.after_actions = AfterActionPreferences(saved.get("after_actions"))
        except (OSError, ValueError, AttributeError):
            pass
        self.log_sink = self.runtime.log_sink
        self.worker = None
        self.stop_worker = None
        self.isRunning = False
        self._close_pending = False
        self._options_locked = False
        self._allow_option_edits_while_running = False

        self.setup_settings_ui()
        connection_content = next(
            section.findChild(QWidget, "monitorSectionContent")
            for section in self.ui.monitorSectionsWidget.sections()
            if section.property("monitorSectionKey") == "connection"
        )
        screen_content = next(
            section.findChild(QWidget, "monitorSectionContent")
            for section in self.ui.monitorSectionsWidget.sections()
            if section.property("monitorSectionKey") == "screen"
        )
        self.monitor = MonitorCoordinator(self, connection_content, screen_content)
        self.multi_panel = MultiExecutionPanel(self, self.ui.extraFeaturesTab)
        self.extra_features_panel.add_feature_page("다중 실행", self.multi_panel, scrollable=False, index=0)
        self.extra_features_panel.navigation.setCurrentRow(0)
        setup_rounded_vertical_scrollbar(self.multi_panel.cards_scroll)
        self.multi_panel.manager.activity_changed.connect(self._multi_activity_changed)
        self.multi_panel.manager.wave_finished.connect(self._multi_wave_finished)
        self.multi_panel.shutdown_ready.connect(self._finish_pending_close)
        try:
            multi_saved = json.loads((self.runtime.user_dir / "config" / "user_config.json").read_text(encoding="utf-8"))
            self.multi_panel.manager.restore(multi_saved.get("multi_instances"))
        except (OSError, ValueError, AttributeError):
            pass
        self.monitor.busy_changed.connect(self.check_start_button_state)
        self.monitor.shutdown_ready.connect(self._finish_pending_close)
        self.monitor.preset_changed.connect(self._refresh_after_action_summary)
        setup_rounded_vertical_scrollbar(self.settings_panel.detail_scroll)
        self.setup_connections()

        self._restore_monitor_order()
        self.setup_dynamic_options()
        self.clear_sub_cases()
        self._refresh_after_action_summary()
        self.on_program_settings_changed(self.settings_panel.program_settings())
        self.check_start_button_state()
        self._restore_ui_state()
        self._ui_state_ready = True
        if getattr(self.runtime, "interface_missing", False) is True:
            self.append_log("interface.json이 없습니다. 기본 Win32 설정 UI를 표시하며 작업 실행은 비활성화됩니다.")

    def _setup_after_action_footer(self):
        footer = self.ui.settingStartWidget_2
        footer.setMinimumHeight(70)
        footer.setMaximumHeight(16777215)
        footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        footer.parentWidget().layout().setAlignment(footer, Qt.AlignmentFlag(0))
        outer = footer.layout()
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(4)
        # Balance the icon hitbox on the opposite side so both labels share
        # the full footer's horizontal center, not just the text column's.
        outer.insertSpacing(0, 30)
        self.ui.endLabelWidget.setMaximumWidth(16777215)
        self.ui.endLabelWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.setStretch(1, 1)
        inner = self.ui.endLabelWidget.layout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)
        for label in (self.ui.endWorkStatusLabel, self.ui.endStatusLabel):
            label.setMaximumWidth(16777215)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.ui.endStatusLabel.setWordWrap(True)
        self.ui.line.setMinimumWidth(0)
        self.ui.line.setMaximumWidth(16777215)
        self.ui.line.setFixedHeight(1)
        self.ui.line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ui.endSettingBtn.setFixedSize(30, 30)
        outer.setAlignment(self.ui.endSettingBtn, Qt.AlignmentFlag.AlignVCenter)
        self.ui.endSettingBtn.setToolTip("작업 완료 후 동작 설정")
        self.ui.endSettingBtn.setAccessibleName("작업 완료 후 동작 설정")

    def _after_action_controller_type(self):
        # The shared connection panels already resolve interface declarations
        # and resource allow-lists. Never infer a type from a name or address.
        preset = next((preset for preset in self.monitor.service.presets
                       if preset["name"] == self.monitor.preset_name), None)
        return preset["type"] if preset is not None else "Win32"

    def _refresh_after_action_summary(self):
        self.ui.endWorkStatusLabel.setText("작업 완료 후" + (" · 이번에만" if self.after_actions.once else ""))
        controller_type = self._after_action_controller_type()
        description = self.after_actions.description(controller_type)
        self.ui.endStatusLabel.setText(description)
        self.ui.endStatusLabel.setToolTip(description)
        editable = not self.isRunning and not self._close_pending and not self._completion_pending and not self._closing
        if hasattr(self, "multi_panel"):
            editable = editable and not self.multi_panel.manager.active
        self.ui.endSettingBtn.setEnabled(editable)
        if self.after_action_panel is not None:
            self.after_action_panel.set_controller_type(controller_type)
            self.after_action_panel.setEnabled(editable)

    def show_after_actions(self):
        if self.isRunning or self._close_pending or self._completion_pending or self._closing:
            return
        self.clear_sub_cases(show_placeholder=False)
        panel = AfterActionPanel(self.after_actions, self.ui.scrollSettingContents,
                                 controller_type=self._after_action_controller_type())
        self.after_action_panel = panel
        self._option_content_layout().addWidget(panel)
        panel.changed.connect(self._after_actions_changed)
        self._refresh_after_action_summary()

    def _after_actions_changed(self):
        self._refresh_after_action_summary()
        self.save_user_config()

    def _finish_after_actions(self):
        actions, self._run_after_actions = self._run_after_actions, None
        eligible = self._run_succeeded and not self._run_stop_requested and not self._close_pending
        self._run_succeeded = False
        if not eligible or actions is None:
            self._refresh_after_action_summary()
            return
        self.after_actions.consume()
        self.save_user_config()
        if any(actions.values()):
            self._completion_pending = True
            self.ui.workStartBtn.setEnabled(False)
            QTimer.singleShot(0, lambda: self._execute_after_actions(actions, self._run_completion_target))
        self._refresh_after_action_summary()

    def _execute_after_actions(self, actions, target):
        try:
            if self._close_pending or self._closing:
                return
            if actions.get("close_app") or actions.get("close_emulator"):
                self.append_log("ADB 앱·에뮬레이터 종료는 UI 준비 단계이므로 실제 종료 요청을 생략합니다.")
            if actions["close_program"]:
                try:
                    self.after_action_backend.close_program(target)
                    self.append_log("완료 후 대상 프로그램 정상 종료를 요청했습니다.")
                except Exception as error:
                    self.append_log(f"완료 후 대상 프로그램 종료 실패: {error}")
            if actions["system_action"] and actions["close_maa"]:
                self._deferred_system_action = actions["system_action"]
            elif actions["system_action"]:
                try:
                    self.append_log("완료 후 시스템 동작을 요청합니다.")
                    self.after_action_backend.system_action(actions["system_action"])
                except Exception as error:
                    self.append_log(f"완료 후 시스템 동작 실패: {error}")
            if actions["close_maa"]:
                self.append_log("완료 후 MAA를 종료합니다.")
                self.close()
        finally:
            self._completion_pending = False
            self._run_completion_target = None
            self._refresh_after_action_summary()
            self.check_start_button_state()
            self._finish_pending_close()

    def _capture_ui_state(self):
        return {
            "geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
            "workspace_sizes": self.ui.workspaceSplitter.sizes(),
            "extra_navigation_collapsed": self.extra_features_panel.navigation_collapsed,
            "monitor_expanded": {
                section.property("monitorSectionKey"): bool(section.property("monitorExpanded"))
                for section in self.ui.monitorSectionsWidget.sections()
            },
        }

    def _restore_workspace_sizes(self):
        sizes = self._saved_ui_state.get("workspace_sizes")
        if (isinstance(sizes, list) and len(sizes) == 2
                and all(type(size) is int and 0 < size <= 100000 for size in sizes)):
            self.ui.workspaceSplitter.setSizes(sizes)

    def _restore_ui_state(self):
        collapsed = self._saved_ui_state.get("extra_navigation_collapsed")
        if type(collapsed) is bool:
            self.extra_features_panel.set_navigation_collapsed(collapsed)
        geometry = self._saved_ui_state.get("geometry")
        if isinstance(geometry, str) and 0 < len(geometry) <= 8192:
            try:
                self.restoreGeometry(QByteArray(base64.b64decode(geometry, validate=True)))
                # A minimized exit must not hide the app at the next startup.
                self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
            except ValueError:
                pass
        expanded = self._saved_ui_state.get("monitor_expanded")
        if isinstance(expanded, dict):
            for section in self.ui.monitorSectionsWidget.sections():
                value = expanded.get(section.property("monitorSectionKey"))
                if type(value) is bool:
                    section.findChild(QToolButton, "monitorSectionToggle").setChecked(value)
        self._restore_workspace_sizes()

    def _schedule_ui_state_save(self, *_args):
        if getattr(self, "_ui_state_ready", False) and not self.isMinimized():
            self._ui_save_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if self._ui_state_ready and self._first_ui_show:
            self._first_ui_show = False
            # Apply widths against the actual post-layout window size once.
            self._restore_workspace_sizes()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_ui_state_save()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_ui_state_save()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._schedule_ui_state_save()

    def setup_connections(self):
        self.ui.endSettingBtn.clicked.connect(self.show_after_actions)
        self.ui.workStartBtn.clicked.connect(self.on_task_start)
        self.ui.logLatestButton.clicked.connect(self.scroll_log_to_latest)
        self.ui.logCopyButton.clicked.connect(self.copy_log)
        self.ui.logClearButton.clicked.connect(self.clear_log)
        self.ui.logSaveButton.clicked.connect(self.save_log)
        self.ui.logPrintText.verticalScrollBar().valueChanged.connect(
            self._update_log_follow_button
        )
        self.ui.logPrintText.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.logPrintText.customContextMenuRequested.connect(self.show_log_context_menu)

        if hasattr(self.ui, 'minimizeEnableBtn'):
            self.ui.minimizeEnableBtn.toggled.connect(
                self.on_main_minimize_setting_changed
            )

    def _setup_extra_features_ui(self):
        self.extra_features_panel = ExtraFeaturesPanel(self.ui.extraFeaturesTab)
        layout = QVBoxLayout(self.ui.extraFeaturesTab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.extra_features_panel)
        self.extra_features_panel.navigation_collapsed_changed.connect(self._schedule_ui_state_save)

    def multi_execution_snapshot(self, include_tasks=True):
        queue = self.build_execution_queue() if include_tasks else []
        return deepcopy({
            "interface": self.runtime.interface, "interface_path": str(self.runtime.interface_path),
            "interface_missing": getattr(self.runtime, "interface_missing", False) is True,
            "resource": self.runtime.resource_config, "user_dir": str(self.runtime.user_dir),
            "queue": queue, "controller": self.settings_panel.controller_settings(),
            "program": self.settings_panel.program_settings(), "settings": self.settings_panel.config,
            "minimize": self.settings_panel.minimize_enabled(),
            "clear_log": self.settings_panel.clear_log_on_start_enabled(),
            "after_actions": self.after_actions.current if any(entry != PROGRAM_LAUNCH_ENTRY for entry, _ in queue) else {},
        })

    def _multi_activity_changed(self):
        if hasattr(self, "option_list_widget"):
            self.set_options_locked(self.isRunning or self.multi_panel.manager.active)
            self.check_start_button_state()
            self._refresh_after_action_summary()
        self.monitor._sync()
        self._finish_pending_close()

    def _multi_wave_finished(self, results, actions):
        if self._closing or not results or not all(result["succeeded"] for result in results):
            return
        from app.afterActions import WindowTarget
        self.after_actions.consume()
        self.save_user_config()
        for result in results:
            target = result.get("target")
            if actions.get("close_program") and target:
                try:
                    self.after_action_backend.close_program(WindowTarget(**target))
                except (OSError, RuntimeError) as error:
                    self.append_log(f"다중 실행 완료 후 대상 종료 실패: {error}")
            if result["connection"].get("target", {}).get("kind") == "Adb" and (
                    actions.get("close_app") or actions.get("close_emulator")):
                self.append_log("ADB 앱·에뮬레이터 종료는 UI 준비 단계이므로 실제 종료 요청을 생략합니다.")
        global_actions = dict(actions)
        for key in ("close_program", "close_app", "close_emulator"):
            global_actions[key] = False
        if any(global_actions.values()):
            self._completion_pending = True
            QTimer.singleShot(0, lambda: self._execute_after_actions(global_actions, None))

    def _setup_workspace_navigation(self):
        self.page_navigation = QButtonGroup(self)
        self.page_navigation.setExclusive(True)
        for button, page in (
            (self.ui.dashboardNavButton, self.ui.mainTab),
            (self.ui.extraFeaturesNavButton, self.ui.extraFeaturesTab),
            (self.ui.settingsNavButton, self.ui.settingTab),
        ):
            self.page_navigation.addButton(button)
            button.clicked.connect(
                lambda _checked=False, target=page: self.ui.mainPages.setCurrentWidget(target)
            )
        self.ui.mainPages.currentChanged.connect(self._sync_page_navigation)
        self.ui.workspaceSplitter.splitterMoved.connect(self._schedule_ui_state_save)

    def _sync_page_navigation(self, index):
        self.ui.dashboardNavButton.setChecked(index == self.ui.mainPages.indexOf(self.ui.mainTab))
        self.ui.extraFeaturesNavButton.setChecked(index == self.ui.mainPages.indexOf(self.ui.extraFeaturesTab))
        self.ui.settingsNavButton.setChecked(index == self.ui.mainPages.indexOf(self.ui.settingTab))

    def _setup_dashboard_layout(self):
        task_panel = self.ui.findChild(QWidget, "_1_settingStartWidget")
        option_panel = self.ui.findChild(QWidget, "_2_settingWidget")
        monitor_panel = self.ui.findChild(QWidget, "_3_logPrintWidget")
        task_panel.setFixedWidth(312)
        option_panel.setMinimumWidth(300)
        monitor_panel.setMinimumWidth(309)
        splitter = self.ui.workspaceSplitter
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([480, 360])
        handle = splitter.handle(1)
        handle._rounded_paint_filter = WorkspaceSplitterHandlePaintFilter(handle)
        handle.installEventFilter(handle._rounded_paint_filter)

        task_title = QLabel("작업 목록", task_panel)
        task_title.setObjectName("workspaceSectionTitle")
        task_panel.findChild(QVBoxLayout, "settingStartWidget_1").insertWidget(0, task_title)

        option_title = QLabel("세부 설정", option_panel)
        option_title.setObjectName("workspaceSectionTitle")
        option_panel.findChild(QVBoxLayout, "verticalLayout_5").insertWidget(0, option_title)

        log_layout = monitor_panel.findChild(QVBoxLayout, "logLayout")
        monitor_title = QLabel("모니터링", monitor_panel)
        monitor_title.setObjectName("workspaceSectionTitle")
        log_layout.insertWidget(0, monitor_title)
        setup_rounded_vertical_scrollbar(self.ui.monitorScrollArea)
        self.ui.monitorScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        sections = self.ui.monitorSectionsWidget
        section_layout = sections.layout()
        section_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        connection = self._create_future_monitor_section(
            "connection", "연결", "클라이언트 연결 확인 기능을 이곳에 추가할 예정입니다."
        )
        screen = self._create_future_monitor_section(
            "screen", "화면", "실시간 스크린샷과 테스트 화면을 이곳에 표시할 예정입니다."
        )
        section_layout.insertWidget(0, connection)
        section_layout.insertWidget(1, screen)

        log_section = self.ui.monitorLogSection
        self._add_monitor_section_header(
            log_section, self.ui.monitorLogContent, "log", "로그", expanded=True
        )
        self._log_section_expanded = True
        self.ui.logPrintText.setMinimumHeight(160)
        self.ui.logPrintText.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.ui.monitorLogContent.layout().setStretch(1, 1)
        log_section.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.ui.monitorLogContent.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        sections.enable_resizing()
        self.ui.logPrintText.setAcceptDrops(False)
        sections.order_changed.connect(self.save_user_config)
        sections.sizes_changed.connect(self.save_user_config)

    def _create_future_monitor_section(self, key, title, description):
        section = QFrame(self.ui.monitorSectionsWidget)
        section.setObjectName("monitorSection")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(0)
        content = QWidget(section)
        content.setObjectName("monitorSectionContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 10, 12, 14)
        description_label = QLabel(description, content)
        description_label.setObjectName("monitorFutureDescription")
        description_label.setWordWrap(True)
        content_layout.addWidget(description_label)
        section_layout.addWidget(content)
        self._add_monitor_section_header(section, content, key, title, expanded=False)
        return section

    def _add_monitor_section_header(self, section, content, key, title, expanded):
        section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        section.setProperty("monitorSectionKey", key)
        section.setProperty("monitorSectionTitle", title)
        section.setProperty("monitorExpanded", expanded)
        header = QWidget(section)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.setObjectName("monitorSectionHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 3, 8, 3)
        header_layout.setSpacing(4)
        handle = MonitorDragHandle(self.ui.monitorSectionsWidget, section)
        toggle = QToolButton(header)
        toggle.setObjectName("monitorSectionToggle")
        toggle.setAccessibleName(f"{title} 영역 펼치기 또는 접기")
        toggle.setText(title)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        toggle.toggled.connect(
            lambda checked, target=content, button=toggle, name=key:
            self._set_monitor_section_expanded(target, button, name, checked)
        )
        header_layout.addWidget(toggle, 1)
        header_layout.addWidget(handle)
        section.layout().insertWidget(0, header)
        content.setVisible(expanded)

    def _set_monitor_section_expanded(self, content, button, key, expanded):
        section = content.parentWidget()
        section.setProperty("monitorExpanded", expanded)
        section.setMinimumHeight(0)
        section.setMaximumHeight(16777215)
        content.setVisible(expanded)
        button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        if key in ("screen", "log"):
            policy = QSizePolicy.Policy.Expanding if expanded else QSizePolicy.Policy.Maximum
            section.setSizePolicy(QSizePolicy.Policy.Expanding, policy)
            content.setSizePolicy(QSizePolicy.Policy.Expanding, policy)
            section.layout().setStretch(section.layout().indexOf(content), 1 if expanded else 0)
        self.ui.monitorSectionsWidget.sync_section_layout()
        if key == "log":
            self._log_section_expanded = expanded
            self._update_log_follow_button()
        self._schedule_ui_state_save()

    def _restore_monitor_order(self):
        config_path = self.runtime.user_dir / "config" / "user_config.json"
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            saved_order = saved.get("monitor_order")
        except (OSError, ValueError, AttributeError):
            return
        sections = self.ui.monitorSectionsWidget
        sections.restore_height_weights(saved.get("monitor_height_weights"))
        if (
            not isinstance(saved_order, list)
            or len(saved_order) != 3
            or not all(isinstance(key, str) for key in saved_order)
            or set(saved_order) != {"connection", "screen", "log"}
        ):
            return
        section_by_key = {
            section.property("monitorSectionKey"): section for section in sections.sections()
        }
        for index, key in enumerate(saved_order):
            section = section_by_key[key]
            sections.move_section(section, sections.sections()[index])

    def setup_settings_ui(self):
        config_dir = self.runtime.user_dir / "config"
        resource_config = (
            self.runtime.resource_config
            if isinstance(self.runtime.resource_config, dict)
            else {}
        )
        self.settings_panel = SettingsPanel(
            config_path=config_dir / "maa_config.json",
            legacy_user_config_path=config_dir / "user_config.json",
            controllers=self.runtime.interface.get("controller", []),
            supported_controller_names=resource_config.get("controller"),
            parent=self.ui.settingTab,
        )

        setting_layout = self.ui.settingTab.layout()
        if setting_layout is None:
            setting_layout = QVBoxLayout(self.ui.settingTab)
            setting_layout.setContentsMargins(0, 0, 0, 0)
        setting_layout.addWidget(self.settings_panel)

        self.settings_panel.minimize_changed.connect(
            self.sync_main_minimize_setting
        )
        self.settings_panel.program_launch_task_enabled_changed.connect(
            self.set_program_launch_task_enabled
        )
        self.settings_panel.runtime_option_editing_changed.connect(
            self.set_runtime_option_editing_enabled
        )
        self.settings_panel.theme_changed.connect(self.set_title_bar_theme)
        self.settings_panel.program_changed.connect(
            self.on_program_settings_changed
        )

        self.sync_main_minimize_setting(self.settings_panel.minimize_enabled())
        self.set_runtime_option_editing_enabled(
            self.settings_panel.runtime_option_editing_enabled()
        )
        self.set_title_bar_theme(self.settings_panel.theme())

    def sync_main_minimize_setting(self, enabled):
        if not hasattr(self.ui, 'minimizeEnableBtn'):
            return
        self.ui.minimizeEnableBtn.blockSignals(True)
        self.ui.minimizeEnableBtn.setChecked(bool(enabled))
        self.ui.minimizeEnableBtn.blockSignals(False)

    def on_main_minimize_setting_changed(self, enabled):
        self.settings_panel.set_minimize_enabled(enabled)

    def on_program_settings_changed(self, program_settings):
        if not hasattr(self, "option_list_widget"):
            return
        available = bool(program_settings.get("resolved_path"))
        reason = "설정에서 실행할 프로그램 경로를 먼저 확인해 주세요."
        for row in range(self.option_list_widget.count()):
            item = self.option_list_widget.item(row)
            widget = self.option_list_widget.itemWidget(item)
            if (
                widget is not None
                and widget.task_data.get("name") == PROGRAM_LAUNCH_TASK_NAME
            ):
                widget.set_available(available, reason)
        self.check_start_button_state()
        self.save_user_config()

    def on_system_color_scheme_changed(self, _color_scheme):
        if self._title_bar_theme == TitleBarTheme.SYSTEM:
            self.set_title_bar_theme(TitleBarTheme.SYSTEM)

    def set_title_bar_theme(self, theme):
        """선택한 색상 모드를 애플리케이션 전체와 제목 표시줄에 적용한다."""
        self._title_bar_theme = TitleBarTheme(theme)
        system_color_scheme = self._style_hints.colorScheme()
        self._effective_theme = resolve_effective_theme(
            self._title_bar_theme,
            system_color_scheme,
        )
        style_sheet = self._base_style_sheet
        if self._effective_theme == TitleBarTheme.DARK:
            style_sheet = "\n".join(
                content
                for content in (style_sheet, self._dark_style_sheet)
                if content
            )
        self.setStyleSheet(style_sheet)
        if hasattr(self.ui, "monitorSectionsWidget"):
            sections = self.ui.monitorSectionsWidget
            for child in sections.findChildren(QWidget):
                child.ensurePolished()
            sections.sync_section_layout()
        return apply_windows_title_bar_theme(
            int(self.winId()),
            self._title_bar_theme,
            system_color_scheme=system_color_scheme,
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.set_title_bar_theme(self._title_bar_theme)

    def append_log(self, message):
        current_time = datetime.now().strftime("%H:%M:%S")
        time_text = f"[{current_time}] "

        log_view = self.ui.logPrintText
        scroll_bar = log_view.verticalScrollBar()
        previous_scroll_value = scroll_bar.value()
        was_at_bottom = previous_scroll_value >= scroll_bar.maximum() - 1

        cursor = QTextCursor(log_view.document())
        cursor.movePosition(QTextCursor.End)

        block_format = cursor.blockFormat()
        block_format.setAlignment(Qt.AlignLeft)

        block_format.setTopMargin(0)
        block_format.setBottomMargin(0)

        block_format.setLeftMargin(0)
        block_format.setTextIndent(0)
        cursor.setBlockFormat(block_format)
        cursor.insertText(time_text)

        block_format.setLeftMargin(58)
        block_format.setTextIndent(-58)
        cursor.setBlockFormat(block_format)

        cursor.insertText(message + "\n")

        if was_at_bottom:
            self.scroll_log_to_latest()
        else:
            scroll_bar.setValue(previous_scroll_value)
            self._update_log_follow_button()

    def _append_run_result(self, message, prefix=""):
        if not hasattr(self, "_run_result_keys"):
            self._run_result_keys = set()
        unique = distinct_result_message(message, self._run_result_keys)
        if unique:
            self.append_log(f"{prefix}{unique}")

    def _update_log_follow_button(self, _value=None):
        scroll_bar = self.ui.logPrintText.verticalScrollBar()
        is_at_bottom = scroll_bar.value() >= scroll_bar.maximum() - 1
        self.ui.logLatestButton.setVisible(
            self._log_section_expanded and not is_at_bottom
        )

    def scroll_log_to_latest(self):
        scroll_bar = self.ui.logPrintText.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        self.ui.logLatestButton.hide()

    def copy_log(self):
        log_view = self.ui.logPrintText
        cursor = log_view.textCursor()
        text = cursor.selectedText().replace("\u2029", "\n")
        QApplication.clipboard().setText(text if cursor.hasSelection() else log_view.toPlainText())

    def _create_log_context_menu(self):
        # Keep Qt's selection/clipboard actions, but not the OS dark popup skin.
        menu = self.ui.logPrintText.createStandardContextMenu()
        menu.setObjectName("logContextMenu")
        menu.setStyleSheet(self.styleSheet())
        # Native standard icons follow the system palette, not our forced theme.
        for action in menu.actions():
            action.setIcon(QIcon())
            # Qt embeds keyboard hints in the label even when the log's
            # interaction mode does not provide those keyboard operations.
            action.setText(action.text().split("\t", 1)[0])
        return menu

    def show_log_context_menu(self, position):
        menu = self._create_log_context_menu()
        try:
            menu.exec(self.ui.logPrintText.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def clear_log(self):
        self.ui.logPrintText.clear()
        self.ui.logLatestButton.hide()

    def save_log(self):
        default_name = f"MAABA-log-{datetime.now():%Y%m%d-%H%M%S}.txt"
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "실행 로그 저장",
            default_name,
            "텍스트 파일 (*.txt);;모든 파일 (*)",
        )
        if not file_path:
            return False
        try:
            Path(file_path).write_text(
                self.ui.logPrintText.toPlainText(), encoding="utf-8"
            )
        except OSError as error:
            self.append_log(f"로그를 저장하지 못했습니다: {error}")
            return False
        return True

    def on_task_start(self):
        if getattr(self.runtime, "interface_missing", False) is True:
            self.append_log("interface.json을 준비한 후 앱을 다시 실행하세요.")
            return
        if not self.multi_panel.ready_to_close:
            self.append_log("다중 실행 또는 대상 탐색이 끝난 뒤 기본 작업을 시작하세요.")
            return
        if self.worker is not None or self.stop_worker is not None or self._close_pending or self._completion_pending or self._closing:
            return
        if self.monitor.prepare_task_start(self.on_task_start):
            return
        if self.settings_panel.clear_log_on_start_enabled():
            self.clear_log()
        self.append_log("작업을 시작합니다...")
        self.ui.workStartBtn.setEnabled(False)

        execution_queue = self.build_execution_queue()
        self._run_after_actions = self.after_actions.for_controller(self._after_action_controller_type()) if any(
            entry != PROGRAM_LAUNCH_ENTRY for entry, _override in execution_queue
        ) else None
        self._run_succeeded = False
        self._run_stop_requested = False
        self._run_completion_target = None

        self._run_result_keys = set()

        minimize_window = False
        if hasattr(self.ui, 'minimizeEnableBtn'):
            minimize_window = self.ui.minimizeEnableBtn.isChecked()

        self.worker = RuntimeWorker(
            self.runtime,
            execution_queue,
            minimize_window,
            controller_settings=self.settings_panel.controller_settings(),
            program_settings=self.settings_panel.program_settings(),
            completion_actions=self._run_after_actions,
        )

        self.worker.log.connect(self.append_log, Qt.QueuedConnection)
        self.worker.finished.connect(self.on_task_finished)

        self.runtime.log_sink.set_log_callback(self.worker.log.emit)

        self.worker.start()

        self.isRunning = True
        self.multi_panel.refresh()
        self.monitor.task_state_changed()

        self.ui.workStartBtn.setText("작업 중지")
        self.ui.workStartBtn.clicked.disconnect(self.on_task_start)
        self.ui.workStartBtn.clicked.connect(self.on_task_stop)
        self.ui.workStartBtn.setEnabled(True)

        self.set_options_locked(True)
        self._refresh_after_action_summary()

    def on_task_stop(self):
        self._run_stop_requested = True
        self.ui.workStartBtn.setEnabled(False)

        if not self.worker:
            self.check_start_button_state()
            return

        # MaaFW task가 아직 시작되지 않은 초기화 단계도 취소할 수 있게 한다.
        self.worker.requestInterruption()

        # 정지 요청이 이미 진행 중이면 재실행하지 않음
        if self.stop_worker is not None:
            return

        self.stop_worker = StopWorker(self.runtime)
        self.stop_worker.finished.connect(self.on_stop_worker_finished)
        self.stop_worker.start()

    def on_stop_worker_finished(self):
        if self.stop_worker is not None:
            if self.stop_worker.succeeded:
                self._append_run_result(self.stop_worker.result_message)
            elif self.stop_worker.result_message != "실행 중인 Tasker가 없습니다.":
                self._append_run_result(self.stop_worker.result_message)
            self.stop_worker.deleteLater()
        self.stop_worker = None
        self._finish_run_if_idle()

    def on_task_finished(self):
        worker = self.worker
        self.runtime.log_sink.set_log_callback(None)

        if worker is not None:
            self._run_succeeded = bool(worker.succeeded)
            self._run_completion_target = getattr(worker, "completion_target", None)
            """따옴표 내부에 기호(이모티콘) 추가/수정 가능"""
            prefix = "▶ " if worker.succeeded else ""
            self._append_run_result(worker.result_message, prefix)
            worker.deleteLater()
        self.worker = None
        self.ui.workStartBtn.setEnabled(False)
        self._finish_run_if_idle()

    def _finish_run_if_idle(self):
        # 두 finished 콜백이 모두 처리되기 전에는 새 실행을 허용하지 않는다.
        if self.worker is not None or self.stop_worker is not None:
            return
        was_running = self.isRunning
        if was_running:
            self.isRunning = False
            self.multi_panel.refresh()
            self.monitor.task_state_changed()
            self.ui.workStartBtn.setText("작업 시작")
            self.ui.workStartBtn.clicked.disconnect(self.on_task_stop)
            self.ui.workStartBtn.clicked.connect(self.on_task_start)
        self.set_options_locked(False)
        self.check_start_button_state()
        if was_running:
            self._finish_after_actions()
        self._finish_pending_close()

    def closeEvent(self, event):
        self._closing = True
        self._run_stop_requested = True
        self._ui_save_timer.stop()
        self.save_user_config()
        worker_running = self.worker is not None
        stop_running = self.stop_worker is not None

        self.monitor.shutdown()
        self.multi_panel.shutdown()
        if worker_running or stop_running or not self.monitor.ready_to_close or not self.multi_panel.ready_to_close:
            self._close_pending = True
            event.ignore()
            if worker_running:
                self.on_task_stop()
            return

        if self._deferred_system_action:
            action, self._deferred_system_action = self._deferred_system_action, ""
            try:
                self.after_action_backend.defer_system_action(action, self.runtime.user_dir / "debug" / "after_action.log")
            except Exception as error:
                self.append_log(f"MAA 종료 후 시스템 동작 예약 실패: {error}")
        super().closeEvent(event)

    def _finish_pending_close(self):
        if not self._close_pending:
            return

        worker_running = self.worker is not None
        stop_running = self.stop_worker is not None
        if not worker_running and not stop_running and self.monitor.ready_to_close and self.multi_panel.ready_to_close:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

    def setup_dynamic_options(self):
        self.option_list_widget = self.ui.taskOptionList
        self.option_list_widget.on_order_changed_callback = self.on_user_config_changed

        self.task_list_actions = self.ui.taskListFooter
        self.task_list_actions_stack = self.ui.taskListActionsStack
        self.task_delete_page = self.ui.taskDeletePage
        self.task_delete_drop_zone = self.ui.taskDeleteDropZone
        self.task_reset_button = self.ui.taskResetButton
        self.task_add_button = self.ui.taskAddButton
        self.task_reset_button._reset_icon_hover_filter = ResetIconHoverFilter(
            self.task_reset_button
        )

        self.task_reset_button.installEventFilter(
            self.task_reset_button._reset_icon_hover_filter
        )
        self.task_list_actions._footer_hover_filter = TaskFooterHoverFilter(
            self.task_list_actions,
            (
                self.task_list_actions,
                self.task_reset_button,
                self.task_add_button,
            ),
        )
        self.task_delete_drop_zone._drop_event_filter = DeleteDropEventFilter(
            self.task_delete_drop_zone
        )
        self.task_delete_drop_zone.installEventFilter(
            self.task_delete_drop_zone._drop_event_filter
        )
        self.option_list_widget.drag_started.connect(self.on_task_drag_started)
        self.option_list_widget.drag_finished.connect(self.on_task_drag_finished)
        self.task_picker = TaskPickerPopup(self)
        self.task_picker.set_anchor_button(self.task_add_button)
        self.task_picker.task_selected.connect(self.add_task)
        self.task_picker.popup_hidden.connect(
            self.task_list_actions._footer_hover_filter._sync_hovered
        )
        self.task_add_button.clicked.connect(self.show_task_picker)
        self.task_reset_button.clicked.connect(self.reset_task_list)

        raw_tasks = self.runtime.interface.get("task", [])
        
        task_dict = {t["name"]: t for t in raw_tasks}
        task_dict_by_entry = {}
        for task in raw_tasks:
            task_dict_by_entry.setdefault(task["entry"], task)

        user_config_path = self.runtime.user_dir / "config" / "user_config.json"
        user_config = {}
        if user_config_path.exists():
            try:
                with open(user_config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                if not isinstance(user_config, dict):
                    user_config = {}
            except Exception as e:
                print(f"설정 파일 로드 실패: {e}")

        saved_tasks = user_config.get("tasks", [])
        if not isinstance(saved_tasks, list):
            saved_tasks = []
        added_tasks = set()

        saved_program_task = next(
            (
                task
                for task in saved_tasks
                if isinstance(task, dict)
                and task.get("name") == PROGRAM_LAUNCH_TASK_NAME
            ),
            None,
        )
        self._program_launch_checked_before_disable = (
            saved_program_task.get("checked", True)
            if saved_program_task is not None
            else PROGRAM_LAUNCH_TASK["default_check"]
        )
        if self.settings_panel.program_launch_task_enabled():
            self.add_task_widget(
                PROGRAM_LAUNCH_TASK,
                self._program_launch_checked_before_disable,
            )

        for saved_task in saved_tasks:
            if not isinstance(saved_task, dict):
                continue
            if saved_task.get("name") == PROGRAM_LAUNCH_TASK_NAME:
                continue
            task_data = task_dict.get(saved_task.get("name"))
            if task_data is None:
                # 기존 entry 기반 설정 파일을 name 기반 형식으로 자동 마이그레이션한다.
                task_data = task_dict_by_entry.get(saved_task.get("entry"))

            if task_data is not None:
                self.add_task_widget(
                    task_data,
                    saved_task.get("checked", task_data.get("default_check", False)),
                    saved_task.get("selected_options", None)
                )
                added_tasks.add(task_data["name"])

        for task_data in raw_tasks:
            if task_data["name"] not in added_tasks:
                self.add_task_widget(task_data, task_data.get("default_check", False), None)

        self._apply_option_editing_policy()
        self.check_start_button_state()

    def add_task_widget(self, task_data, is_checked, saved_options=None):
        item = QListWidgetItem()
        item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
        item.setData(Qt.UserRole, task_data["name"])
        # 같은 Task를 여러 번 추가해도 드래그 시 각 항목의 옵션을 유지한다.
        item.setData(Qt.UserRole + 1, uuid4().hex)
        if task_data.get("name") == PROGRAM_LAUNCH_TASK_NAME:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self.option_list_widget.insertItem(0, item)
        else:
            self.option_list_widget.addItem(item)

        options_dict = self.runtime.interface.get("option", {})
        task_options = [
            (name, options_dict[name])
            for name in task_data.get("option", [])
            if name in options_dict
        ]
        custom_widget = OptionItemWidget(
            task_data, task_options, self.show_sub_cases, self.on_task_checkbox_toggled
        )
        if isinstance(saved_options, dict):
            for opt_name, opt in custom_widget.task_options:
                saved_value = saved_options.get(opt_name)
                if opt.get("type", "select") == "input":
                    if not isinstance(saved_value, dict):
                        continue
                    current_values = custom_widget.selected_options[opt_name]
                    for input_config in opt.get("inputs", []):
                        input_name = input_config.get("name")
                        if not input_name or input_config.get("password"):
                            continue
                        saved_input = saved_value.get(input_name)
                        if isinstance(saved_input, str):
                            current_values[input_name] = saved_input
                    continue

                if not isinstance(saved_value, list):
                    continue
                valid_names = [case.get("name") for case in opt.get("cases", [])]
                selected = [name for name in valid_names if name in saved_value]
                if opt.get("type", "select") != "checkbox":
                    selected = selected[:1]
                if selected or opt.get("type", "select") == "checkbox":
                    custom_widget.selected_options[opt_name] = selected

        custom_widget.checkbox.blockSignals(True)
        custom_widget.checkbox.setChecked(is_checked)
        custom_widget.checkbox.blockSignals(False)
        if task_data.get("requires_program"):
            program_settings = self.settings_panel.program_settings()
            custom_widget.set_available(
                bool(program_settings.get("resolved_path")),
                "설정에서 실행할 프로그램 경로를 먼저 확인해 주세요.",
            )
        custom_widget.adjustSize()
        item.setSizeHint(custom_widget.sizeHint())
        self.option_list_widget.setItemWidget(item, custom_widget)

    def show_task_picker(self):
        if not self.task_add_button.isEnabled():
            return
        if self.task_picker.isVisible():
            self.task_picker.hide()
            return
        self.task_picker.show_above(
            self.task_list_actions,
            self.option_list_widget,
            self.runtime.interface.get("task", []),
            self.ui.taskListContainer,
        )

    def set_program_launch_task_enabled(self, enabled):
        launch_item = None
        for row in range(self.option_list_widget.count()):
            item = self.option_list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == PROGRAM_LAUNCH_TASK_NAME:
                launch_item = item
                break

        if not enabled and launch_item is not None:
            widget = self.option_list_widget.itemWidget(launch_item)
            if widget is not None:
                self._program_launch_checked_before_disable = widget.is_checked()
                widget.hide()
                widget.deleteLater()
            row = self.option_list_widget.row(launch_item)
            removed_item = self.option_list_widget.takeItem(row)
            del removed_item
        elif enabled and launch_item is None:
            self.add_task_widget(
                PROGRAM_LAUNCH_TASK,
                getattr(
                    self,
                    "_program_launch_checked_before_disable",
                    PROGRAM_LAUNCH_TASK["default_check"],
                ),
            )
            self.option_list_widget.scrollToTop()
            self._apply_option_editing_policy()

        self.clear_sub_cases()
        self.check_start_button_state()
        self.save_user_config()

    def on_task_drag_started(self):
        self.task_picker.hide()
        self.ui.taskListSeparator.hide()
        self.task_list_actions_stack.setCurrentWidget(self.task_delete_page)

    def on_task_drag_finished(self, dragged_item, global_position):
        try:
            drop_position = self.task_delete_drop_zone.mapFromGlobal(global_position)
            if not self.task_delete_drop_zone.rect().contains(drop_position):
                return
            row = self.option_list_widget.row(dragged_item)
            if row < 0:
                return
            item_widget = self.option_list_widget.itemWidget(dragged_item)
            removed_item = self.option_list_widget.takeItem(row)
            if item_widget is not None:
                item_widget.hide()
                item_widget.deleteLater()
            del removed_item
            self.clear_sub_cases()
            self.check_start_button_state()
            self.save_user_config()
        finally:
            self.task_list_actions_stack.setCurrentWidget(self.task_list_actions)
            self.ui.taskListSeparator.show()

    def add_task(self, task_data):
        if not self.task_add_button.isEnabled():
            return
        if task_data.get("name") == PROGRAM_LAUNCH_TASK_NAME:
            for row in range(self.option_list_widget.count()):
                widget = self.option_list_widget.itemWidget(
                    self.option_list_widget.item(row)
                )
                if (
                    widget is not None
                    and widget.task_data.get("name") == PROGRAM_LAUNCH_TASK_NAME
                ):
                    return
        self.add_task_widget(task_data, task_data.get("default_check", False))
        if task_data.get("name") == PROGRAM_LAUNCH_TASK_NAME:
            self.option_list_widget.scrollToTop()
        else:
            self.option_list_widget.scrollToBottom()
        self._apply_option_editing_policy()
        self.check_start_button_state()
        self.save_user_config()

    def reset_task_list(self):
        if not self.task_reset_button.isEnabled():
            return
        self.task_picker.hide()
        # 삭제되는 항목을 참조하는 세부 옵션 컨트롤도 함께 비운다.
        self.clear_sub_cases()
        self.option_list_widget.clear()
        if self.settings_panel.program_launch_task_enabled():
            self.add_task_widget(
                PROGRAM_LAUNCH_TASK, PROGRAM_LAUNCH_TASK["default_check"]
            )
        for task in self.runtime.interface.get("task", []):
            self.add_task_widget(task, task.get("default_check", False))
        self._apply_option_editing_policy()
        self.check_start_button_state()
        self.save_user_config()

    def _option_content_layout(self):
        container = self.ui.scrollSettingContents
        layout = container.layout()
        if layout is None:
            layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 4, 8)
        layout.setSpacing(8)
        return layout

    def clear_sub_cases(self, show_placeholder=True):
        self.after_action_panel = None
        layout = self._option_content_layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().hide()
                child.widget().deleteLater()
        if show_placeholder:
            self._add_option_placeholder(layout, "작업 목록의 설정 버튼을 눌러\n세부 옵션을 확인하세요.")

    def _add_option_placeholder(self, layout, message):
        label = QLabel(message, self.ui.scrollSettingContents)
        label.setObjectName("optionEmptyState")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)

    def show_sub_cases(self, item_widget):
        task_options = item_widget.task_options

        container_widget = self.ui.scrollSettingContents
        layout = self._option_content_layout()
            
        self.clear_sub_cases(show_placeholder=False)

        if not task_options:
            self._add_option_placeholder(layout, "이 작업에는 세부 옵션이 없습니다.")
            return

        for index, (opt_name, opt) in enumerate(task_options):
            opt_type = opt.get("type", "select")
            if index:
                separator = QFrame(container_widget)
                separator.setObjectName("optionGroupSeparator")
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFixedHeight(1)
                layout.addWidget(separator)
            
            title_label = QLabel(opt.get('label', opt_name))
            title_label.setObjectName("optionGroupTitle")
            title_label.setProperty("firstGroup", index == 0)
            title_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            title_label.setWordWrap(True)
            layout.addWidget(title_label)

            cases = opt.get("cases", [])

            if opt_type == "radio":
                select_container = QWidget(container_widget)
                select_layout = QVBoxLayout(select_container)
                select_layout.setContentsMargins(0, 0, 0, 0)
                select_layout.setSpacing(0)
                button_group = QButtonGroup(select_container)
                
                for case in cases:
                    case_name = case["name"]

                    row_widget = QWidget(select_container)
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(0, 2, 0, 2)
                    row_layout.setSpacing(8)

                    radio_btn = QRadioButton("")
                    button_group.addButton(radio_btn)
                    
                    if case_name in item_widget.selected_options.get(opt_name, []):
                        radio_btn.setChecked(True)

                    case_label = AssociatedControlLabel(case.get('label', case_name))
                    case_label.setObjectName("optionChoiceLabel")
                    case_label.setWordWrap(True)
                    case_label.setAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                    case_label.activated.connect(radio_btn.click)
                    
                    def make_radio_slot(w, o_name, c_name):
                        return lambda checked: self.update_widget_option_radio(w, o_name, c_name, checked)
                        
                    radio_btn.toggled.connect(make_radio_slot(item_widget, opt_name, case_name))
                    
                    row_layout.addWidget(
                        radio_btn, 0, Qt.AlignmentFlag.AlignVCenter
                    )
                    row_layout.addWidget(
                        case_label, 1, Qt.AlignmentFlag.AlignVCenter
                    )
                    select_layout.addWidget(row_widget)

                layout.addWidget(select_container)

            elif opt_type == "select":
                combo_box = PopupOnlyWheelComboBox(container_widget)
                combo_box.setObjectName("optionSelect")
                combo_box.setProperty("optionName", opt_name)
                combo_box.setAccessibleName(opt.get("label", opt_name))
                combo_box.ensurePolished()
                popup = QListView(combo_box)
                popup.setObjectName("optionSelectPopup")
                popup.setMouseTracking(True)
                popup.viewport().setMouseTracking(True)
                popup.setUniformItemSizes(True)
                popup.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
                popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                combo_box.setView(popup)
                popup.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                combo_box.setItemDelegate(CenteredOptionDelegate(popup))
                combo_box.setMaxVisibleItems(8)
                setup_rounded_vertical_scrollbar(popup, popup=True)

                for case in cases:
                    case_name = case.get("name")
                    if not case_name:
                        continue
                    combo_box.addItem(case.get("label", case_name), case_name)
                    description = case.get("description")
                    if description:
                        combo_box.setItemData(
                            combo_box.count() - 1, description, Qt.ToolTipRole
                        )

                selected_cases = item_widget.selected_options.get(opt_name, [])
                selected_name = selected_cases[0] if selected_cases else None
                selected_index = combo_box.findData(selected_name)
                if selected_index < 0 and combo_box.count() > 0:
                    selected_index = 0
                    item_widget.selected_options[opt_name] = [combo_box.itemData(0)]
                combo_box.setCurrentIndex(selected_index)

                def make_select_slot(w, o_name, select_widget):
                    return lambda index: self.update_widget_option_select(
                        w, o_name, select_widget, index
                    )

                combo_box.currentIndexChanged.connect(
                    make_select_slot(item_widget, opt_name, combo_box)
                )
                layout.addWidget(combo_box)

            elif opt_type == "checkbox":
                for case in cases:
                    case_name = case["name"]
                    
                    row_widget = QWidget()
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(0, 2, 0, 2)
                    row_layout.setSpacing(8)

                    case_cb = QCheckBox("")
                    
                    if case_name in item_widget.selected_options.get(opt_name, []):
                        case_cb.setChecked(True)
                    
                    case_label = AssociatedControlLabel(case.get('label', case_name))
                    case_label.setObjectName("optionChoiceLabel")
                    case_label.setWordWrap(True)
                    case_label.setAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                    case_label.activated.connect(case_cb.click)
                    
                    def make_checkbox_slot(w, o_name, c_name):
                        return lambda checked: self.update_widget_option_checkbox(w, o_name, c_name, checked)
                    
                    case_cb.toggled.connect(make_checkbox_slot(item_widget, opt_name, case_name))
                    
                    row_layout.addWidget(
                        case_cb, 0, Qt.AlignmentFlag.AlignVCenter
                    )
                    row_layout.addWidget(
                        case_label, 1, Qt.AlignmentFlag.AlignVCenter
                    )
                    layout.addWidget(row_widget)

            elif opt_type == "switch":
                yes_case_name, no_case_name = find_switch_cases(cases)
                yes_case = next((c for c in cases if c.get("name") == yes_case_name), None)
                if yes_case_name is not None:
                    case_label_text = yes_case.get('label', yes_case_name) if yes_case else yes_case_name

                    row_widget = QWidget()
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(0, 2, 0, 2)
                    row_layout.setSpacing(8)

                    # 기능은 CheckBox와 동일 (추후 스타일시트로 토글 모양 변경)
                    switch_cb = QCheckBox("")

                    if yes_case_name in item_widget.selected_options.get(opt_name, []):
                        switch_cb.setChecked(True)

                    case_label = AssociatedControlLabel(case_label_text)
                    case_label.setObjectName("optionChoiceLabel")
                    case_label.setWordWrap(True)
                    case_label.setAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                    case_label.activated.connect(switch_cb.click)

                    def make_switch_slot(w, o_name, y_name, n_name):
                        return lambda checked: self.update_widget_option_switch(w, o_name, y_name, n_name, checked)

                    switch_cb.toggled.connect(make_switch_slot(item_widget, opt_name, yes_case_name, no_case_name))

                    row_layout.addWidget(
                        switch_cb, 0, Qt.AlignmentFlag.AlignVCenter
                    )
                    row_layout.addWidget(
                        case_label, 1, Qt.AlignmentFlag.AlignVCenter
                    )
                    layout.addWidget(row_widget)

            elif opt_type == "input":
                input_values = item_widget.selected_options.get(opt_name, {})
                for input_config in opt.get("inputs", []):
                    input_name = input_config.get("name")
                    if not input_name:
                        continue

                    input_container = QWidget(container_widget)
                    input_layout = QVBoxLayout(input_container)
                    input_layout.setContentsMargins(0, 2, 0, 4)
                    input_layout.setSpacing(4)

                    input_label = QLabel(input_config.get("label", input_name))
                    input_label.setObjectName("optionInputLabel")
                    input_layout.addWidget(input_label)

                    line_edit = QLineEdit(input_container)
                    line_edit.setObjectName("optionInput")
                    line_edit.setProperty("optionName", opt_name)
                    line_edit.setProperty("inputName", input_name)
                    line_edit.setText(
                        str(input_values.get(input_name, input_config.get("default", "")))
                    )
                    description = input_config.get("description")
                    if description:
                        line_edit.setToolTip(description)
                    if input_config.get("password"):
                        line_edit.setEchoMode(QLineEdit.EchoMode.Password)
                    line_edit.setAccessibleName(input_config.get("label", input_name))
                    input_layout.addWidget(line_edit)

                    error_label = QLabel(input_container)
                    error_label.setObjectName("optionInputError")
                    error_label.setWordWrap(True)
                    input_layout.addWidget(error_label)

                    def make_input_slot(w, o_name, i_config, editor, error):
                        return lambda text: self.update_widget_option_input(
                            w, o_name, i_config, editor, error, text
                        )

                    line_edit.textChanged.connect(
                        make_input_slot(
                            item_widget,
                            opt_name,
                            input_config,
                            line_edit,
                            error_label,
                        )
                    )
                    self.update_input_validation_state(
                        line_edit, error_label, input_config, line_edit.text()
                    )
                    layout.addWidget(input_container)

        layout.addStretch()

    def update_widget_option_radio(self, widget, opt_name, case_name, is_checked):
        if is_checked:
            widget.selected_options[opt_name] = [case_name]
            self.on_user_config_changed()

    def update_widget_option_select(self, widget, opt_name, combo_box, index):
        case_name = combo_box.itemData(index)
        if case_name is None:
            return
        widget.selected_options[opt_name] = [case_name]
        self.on_user_config_changed()

    def update_widget_option_checkbox(self, widget, opt_name, case_name, is_checked):
        if opt_name not in widget.selected_options:
            widget.selected_options[opt_name] = []
            
        if is_checked:
            if case_name not in widget.selected_options[opt_name]:
                widget.selected_options[opt_name].append(case_name)
        else:
            if case_name in widget.selected_options[opt_name]:
                widget.selected_options[opt_name].remove(case_name)

        self.on_user_config_changed()

    def update_widget_option_switch(self, widget, opt_name, yes_case_name, no_case_name, is_checked):
        if is_checked and yes_case_name is not None:
            widget.selected_options[opt_name] = [yes_case_name]
        elif not is_checked and no_case_name is not None:
            widget.selected_options[opt_name] = [no_case_name]

        self.on_user_config_changed()

    def update_input_validation_state(self, line_edit, error_label, input_config, value):
        is_valid, validation_message = validate_input_value(input_config, value)
        line_edit.setProperty("inputValid", is_valid)
        line_edit.style().unpolish(line_edit)
        line_edit.style().polish(line_edit)
        error_label.setText(validation_message)
        error_label.setVisible(not is_valid)
        return is_valid

    def update_widget_option_input(
        self, widget, opt_name, input_config, line_edit, error_label, value
    ):
        input_name = input_config["name"]
        input_values = widget.selected_options.setdefault(opt_name, {})
        input_values[input_name] = value
        self.update_input_validation_state(
            line_edit, error_label, input_config, value
        )
        self.check_start_button_state()
        self.on_user_config_changed()

    def check_start_button_state(self):
        if getattr(self.runtime, "interface_missing", False) is True:
            self.ui.workStartBtn.setEnabled(False)
            return
        if hasattr(self, "multi_panel") and not self.multi_panel.ready_to_close and not self.isRunning:
            self.ui.workStartBtn.setEnabled(False)
            return
        if self._completion_pending or self._closing:
            self.ui.workStartBtn.setEnabled(False)
            return
        if self.isRunning:
            self.ui.workStartBtn.setEnabled(
                self.stop_worker is None and not self._close_pending
            )
            return
        if self.stop_worker is not None or self._close_pending or self.monitor.pending_start is not None:
            self.ui.workStartBtn.setEnabled(False)
            return
        any_checked = False
        for i in range(self.option_list_widget.count()):
            item = self.option_list_widget.item(i)
            widget = self.option_list_widget.itemWidget(item)
            if widget and widget.is_checked():
                any_checked = True
                if not widget.has_valid_input():
                    self.ui.workStartBtn.setEnabled(False)
                    return
        self.ui.workStartBtn.setEnabled(any_checked)

    def on_task_checkbox_toggled(self, checked):
        self.check_start_button_state()
        self.on_user_config_changed()

    def on_user_config_changed(self):
        self.save_user_config()

    def set_options_locked(self, locked: bool):
        self._options_locked = locked
        self._apply_option_editing_policy()

    def _apply_option_editing_policy(self):
        controls_locked = (
            self._options_locked and not self._allow_option_edits_while_running
        )

        if hasattr(self, "option_list_widget"):
            for i in range(self.option_list_widget.count()):
                item = self.option_list_widget.item(i)
                widget = self.option_list_widget.itemWidget(item)
                if widget:
                    widget.set_locked(controls_locked)

            self.option_list_widget.set_locked(controls_locked)

        if hasattr(self, "task_list_actions"):
            self.task_list_actions.setEnabled(not controls_locked)
            self.task_reset_button.setEnabled(not controls_locked)
            self.task_add_button.setEnabled(not controls_locked)
            if controls_locked:
                self.task_picker.hide()

        if hasattr(self.ui, 'minimizeEnableBtn'):
            self.ui.minimizeEnableBtn.setEnabled(not controls_locked)

        if hasattr(self.ui, 'scrollSettingContents'):
            self.ui.scrollSettingContents.setEnabled(not controls_locked)

    def set_runtime_option_editing_enabled(self, enabled: bool):
        """실행 중 전체 옵션 편집 정책을 즉시 적용한다."""
        self._allow_option_edits_while_running = bool(enabled)
        self._apply_option_editing_policy()

    def build_execution_queue(self):
        execution_queue = []
        
        for i in range(self.option_list_widget.count()):
            item = self.option_list_widget.item(i)
            widget_in_item = self.option_list_widget.itemWidget(item)
            
            if widget_in_item and widget_in_item.is_checked():
                task_entry = widget_in_item.task_data["entry"]
                override_params = {}
                task_override = widget_in_item.task_data.get("pipeline_override", {})
                if isinstance(task_override, dict):
                    merge_pipeline_override(override_params, task_override)
                
                for opt_name, opt in widget_in_item.task_options:
                    selected_cases = widget_in_item.selected_options.get(opt_name, [])

                    if opt.get("type", "select") == "input":
                        if not isinstance(selected_cases, dict):
                            continue
                        input_override = build_input_pipeline_override(opt, selected_cases)
                        if isinstance(input_override, dict):
                            merge_pipeline_override(override_params, input_override)
                        continue
                    
                    if not selected_cases:
                        continue
                        
                    for case in opt.get("cases", []):
                        if case["name"] in selected_cases:
                            pipeline_override = case.get("pipeline_override", {})
                            if isinstance(pipeline_override, dict):
                                merge_pipeline_override(override_params, pipeline_override)
                
                execution_queue.append((task_entry, override_params))
                
        return execution_queue

    def save_user_config(self):
        config_dir = self.runtime.user_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True) # 폴더가 없으면 자동 생성
        config_path = config_dir / "user_config.json"
        
        tasks_data = []
        
        for i in range(self.option_list_widget.count()):
            item = self.option_list_widget.item(i)
            widget = self.option_list_widget.itemWidget(item)
            if widget:
                tasks_data.append({
                    "name": widget.task_data["name"],
                    "entry": widget.task_data["entry"],
                    "checked": widget.is_checked(),
                    "selected_options": widget.get_persisted_options()
                })
                
        try:
            temp_path = config_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "tasks": tasks_data,
                        "monitor_order": self.ui.monitorSectionsWidget.section_order(),
                        "monitor_height_weights": self.ui.monitorSectionsWidget.height_weights(),
                        "ui_state": self._capture_ui_state() if self._ui_state_ready else self._saved_ui_state,
                        "after_actions": dict(self.after_actions.saved),
                        "multi_instances": self.multi_panel.manager.saved_sessions() if hasattr(self, "multi_panel") else [],
                    },
                    f,
                    ensure_ascii=False,
                    indent=4,
                )
                f.flush()
            temp_path.replace(config_path)
        except Exception as e:
            print(f"설정 파일 저장 실패: {e}")

# 정지 요청 전용 스레드
class StopWorker(QThread):
    def __init__(self, runtime, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self.succeeded = False
        self.result_message = ""

    def run(self):
        try:
            self.succeeded, self.result_message = self.runtime.stop_task()
        except Exception as error:
            self.succeeded = False
            self.result_message = f"작업 중지 중 오류가 발생했습니다: {error}"

# Tasker 스레드
class RuntimeWorker(QThread):
    log = Signal(str)

    def __init__(
        self,
        runtime,
        execution_queue,
        minimize_window=False,
        controller_settings=None,
        program_settings=None,
        completion_actions=None,
    ):
        super().__init__()
        self.runtime = runtime
        self.execution_queue = execution_queue
        self.minimize_window = minimize_window
        self.controller_settings = controller_settings
        self.program_settings = program_settings
        self.completion_actions = completion_actions or {}
        self.completion_target = None
        self.succeeded = False
        self.result_message = "작업을 시작하지 못했습니다."

    def run(self):
        try:
            initialized, init_message = self.runtime.initialize(
                self.controller_settings,
                program_settings=self.program_settings,
                execution_queue=self.execution_queue,
                minimize_window=self.minimize_window,
                cancellation_requested=self.isInterruptionRequested,
            )
            if not initialized:
                self.result_message = init_message
                if self.isInterruptionRequested():
                    self.result_message = distinct_result_message(
                        f"{init_message}\n작업이 중지되었습니다."
                    )
                return

            self.log.emit(init_message)
            if self.completion_actions.get("close_program"):
                try:
                    self.completion_target = capture_window_target(self.runtime._target_hwnd)
                except (OSError, RuntimeError) as error:
                    self.log.emit(f"완료 후 종료 대상 확인 실패: {error}")
            if self.isInterruptionRequested():
                self.result_message = "작업 시작이 취소되었습니다."
                return

            self.log.emit("▶ 작업 시작...")
            self.succeeded, self.result_message = self.runtime.run_task(
                self.execution_queue,
                self.minimize_window,
                cancellation_requested=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                self.succeeded = False
                self.result_message = "작업이 중지되었습니다."
        except Exception as error:
            self.succeeded = False
            self.result_message = f"Runtime에서 예기치 않은 오류가 발생했습니다: {error}"
        finally:
            try:
                released, release_message = self.runtime.release_session()
            except Exception as error:
                released = False
                release_message = f"Runtime 정리 중 오류가 발생했습니다: {error}"
            if not released:
                self.succeeded = False
                self.result_message = distinct_result_message(
                    f"{self.result_message}\n{release_message}"
                )
