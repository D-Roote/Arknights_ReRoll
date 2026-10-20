"""Completion settings hosted in the existing central detail pane."""
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QLabel, QPushButton, QStyle, QStyleOptionButton,
    QStyleOptionFocusRect, QVBoxLayout, QWidget,
)

from app.afterActions import SYSTEM_ACTIONS


class OpticalCheckBox(QCheckBox):
    """Keep native interaction, but center visible glyph ink rather than line metrics."""
    def paintEvent(self, _event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        style = self.style()
        indicator = style.subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        text_rect = style.subElementRect(QStyle.SubElement.SE_CheckBoxContents, option, self)
        ink = QFontMetricsF(self.font(), self).tightBoundingRect(self.text())
        # QRect's inclusive bottom differs from a floating rectangle by half a
        # pixel. Anchor the baseline to the actual painted indicator center.
        baseline = indicator.y() + indicator.height() / 2.0 - ink.center().y()
        painter = QPainter(self)
        option.text = ""
        style.drawControl(QStyle.ControlElement.CE_CheckBox, option, painter, self)
        painter.setFont(self.font())
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        painter.setPen(option.palette.color(group, QPalette.ColorRole.WindowText))
        painter.drawText(QPointF(text_rect.x(), baseline), self.text())
        if self.hasFocus():
            focus = QStyleOptionFocusRect()
            focus.initFrom(self)
            focus.rect = text_rect
            style.drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, focus, painter, self)
        painter.end()


class AfterActionPanel(QWidget):
    changed = Signal()

    def __init__(self, preferences, parent=None, controller_type="Win32"):
        super().__init__(parent)
        self.preferences = preferences
        self.controller_type = controller_type
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._title(root, "작업 완료 후 동작", first=True)
        info = QLabel("모든 작업이 정상 완료된 후 실행합니다.\n수동 중지·실패 시에는 실행하지 않습니다.")
        info.setObjectName("afterActionHint")
        info.setWordWrap(True)
        root.addWidget(info)
        self.once_checkbox = OpticalCheckBox("이번에만")
        self.once_checkbox.setObjectName("afterActionChoice")
        self.once_checkbox.setMinimumHeight(28)
        self.once_checkbox.setToolTip("이후 변경은 다음 정상 완료에만 적용합니다. 재실행 시 기존 영구 설정으로 돌아옵니다.")
        root.addWidget(self.once_checkbox)
        self.controls = {}
        self._title(root, "프로그램")
        for key, label in (("close_program", "대상 프로그램 종료"), ("close_app", "앱 종료"),
                           ("close_emulator", "에뮬레이터 종료"), ("close_maa", "MAA 종료")):
            control = self._checkbox(root, key, label)
            control.toggled.connect(lambda checked, name=key: self._update(name, checked))
        self.controls["close_program"].setToolTip("실제 작업 실행 창에 정상 종료를 요청합니다. 강제 종료하지 않습니다.")
        self.controls["close_emulator"].setToolTip("선택하면 앱 종료도 반드시 선택됩니다. 현재는 UI만 제공하며 실제 종료 명령은 준비 중입니다.")
        self.adb_notice = QLabel("ADB 종료 옵션은 UI 준비 단계입니다.\n앱·에뮬레이터 종료 명령은 아직 실행하지 않습니다.")
        self.adb_notice.setObjectName("afterActionHint")
        self.adb_notice.setWordWrap(True)
        root.addWidget(self.adb_notice)
        self._title(root, "시스템 · 하나만 선택")
        for key, label in SYSTEM_ACTIONS.items():
            control = self._checkbox(root, key, label)
            control.toggled.connect(lambda checked, name=key: self._update("system_action", name if checked else ""))
        warning = QLabel("절전·최대 절전은 PC 지원과 전원 권한이 필요합니다.\n시스템 종료 전 저장하지 않은 작업을 확인하세요.")
        warning.setObjectName("afterActionHint")
        warning.setWordWrap(True)
        root.addWidget(warning)
        self.clear_button = QPushButton("모두 해제")
        self.clear_button.setObjectName("monitorActionButton")
        self.clear_button.clicked.connect(self._clear)
        root.addWidget(self.clear_button)
        self.once_checkbox.toggled.connect(self._set_once)
        self.sync()

    def _title(self, layout, text, first=False):
        if not first:
            separator = QFrame(self)
            separator.setObjectName("optionGroupSeparator")
            separator.setFixedHeight(1)
            layout.addWidget(separator)
        label = QLabel(text, self)
        label.setObjectName("optionGroupTitle")
        label.setProperty("firstGroup", first)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setMinimumHeight(24)
        layout.addWidget(label)

    def _checkbox(self, layout, key, label):
        checkbox = OpticalCheckBox(label, self)
        checkbox.setObjectName("afterActionChoice")
        checkbox.setMinimumHeight(28)
        self.controls[key] = checkbox
        layout.addWidget(checkbox)
        return checkbox

    def sync(self):
        is_adb = self.controller_type == "Adb"
        self.controls["close_program"].setVisible(not is_adb)
        for key in ("close_app", "close_emulator"):
            self.controls[key].setVisible(is_adb)
        self.adb_notice.setVisible(is_adb)
        self.controls["close_app"].setEnabled(not self.preferences.current["close_emulator"])
        self.controls["close_app"].setToolTip(
            "에뮬레이터 종료 선택 중에는 앱 종료를 해제할 수 없습니다."
            if self.preferences.current["close_emulator"] else "현재는 UI만 제공하며 실제 앱 종료 명령은 준비 중입니다."
        )
        values = [(self.once_checkbox, self.preferences.once)]
        for key, control in self.controls.items():
            checked = (self.preferences.current["system_action"] == key if key in SYSTEM_ACTIONS
                       else self.preferences.current[key])
            values.append((control, checked))
        for control, checked in values:
            old = control.blockSignals(True)
            control.setChecked(checked)
            control.blockSignals(old)

    def set_controller_type(self, controller_type):
        self.controller_type = controller_type
        self.sync()

    def _update(self, key, value):
        self.preferences.update(key, value)
        self.sync()
        self.changed.emit()

    def _set_once(self, checked):
        self.preferences.set_once(checked)
        self.changed.emit()

    def _clear(self):
        self.preferences.clear()
        self.sync()
        self.changed.emit()
