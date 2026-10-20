"""Expandable workspace for additional features; no runtime actions on entry."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QScrollArea, QSizePolicy,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)


class ExtraFeaturesPanel(QWidget):
    navigation_collapsed_changed = Signal(bool)
    feature_page_added = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("extraFeaturesPanel")
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 6, 16)
        root.setSpacing(12)

        self.navigation_toggle = QToolButton(self)
        self.navigation_toggle.setObjectName("extraNavigationToggle")
        self.navigation_toggle.setFixedSize(18, 76)
        self.navigation_toggle.setIconSize(QSize(10, 10))
        self.navigation_toggle.setCheckable(True)
        self.navigation_toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.navigation_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self.navigation_toggle, 0, Qt.AlignmentFlag.AlignVCenter)

        self.navigation = QListWidget(self)
        self.navigation.setObjectName("extraNavigation")
        self.navigation.setAccessibleName("추가 기능 목록")
        self.navigation.setFixedWidth(210)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.navigation)

        self.pages = QStackedWidget(self)
        self.pages.setObjectName("extraFeaturePages")
        self.pages.setMinimumWidth(0)
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.pages, 1)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation_toggle.toggled.connect(self._update_navigation_visibility)

        overview = QWidget()
        overview.setObjectName("extraFeatureOverview")
        content = QVBoxLayout(overview)
        content.setContentsMargins(0, 0, 6, 0)
        content.setSpacing(14)
        card = QFrame(overview)
        card.setObjectName("extraFeatureCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        title = QLabel("추가 기능", card)
        title.setObjectName("settingsSectionTitle")
        card_layout.addWidget(title)
        description = QLabel(
            "아직 등록된 추가 기능이 없습니다.\n"
            "기능이 추가되면 왼쪽 목록에서 선택할 수 있습니다.", card)
        description.setObjectName("settingsSectionDescription")
        description.setWordWrap(True)
        card_layout.addWidget(description)
        content.addWidget(card)
        content.addStretch()
        self.add_feature_page("안내", overview)
        self.detail_scroll = self.pages.widget(0)
        self._update_navigation_visibility(False)

    @property
    def navigation_collapsed(self):
        return self.navigation_toggle.isChecked()

    def set_navigation_collapsed(self, collapsed):
        self.navigation_toggle.setChecked(bool(collapsed))

    def _update_navigation_visibility(self, collapsed):
        self.navigation.setVisible(not collapsed)
        self.navigation_toggle.setArrowType(Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.LeftArrow)
        label = "추가 기능 목록 펼치기" if collapsed else "추가 기능 목록 접기"
        self.navigation_toggle.setAccessibleName(label)
        self.navigation_toggle.setToolTip(label)
        self.navigation_collapsed_changed.emit(collapsed)

    def add_feature_page(self, title, contents, *, scrollable=True, index=None):
        """Register contents in an owned, resizable scroll page and its list item."""
        page = contents
        if scrollable:
            page = QScrollArea(self.pages)
            page.setObjectName("extraFeatureScroll")
            page.setFrameShape(QFrame.Shape.NoFrame)
            page.setWidgetResizable(True)
            page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page.setWidget(contents)
        index = self.pages.count() if index is None else index
        self.pages.insertWidget(index, page)
        self.navigation.insertItem(index, title)
        if self.navigation.currentRow() < 0:
            self.navigation.setCurrentRow(0)
        if scrollable:
            self.feature_page_added.emit(page)
        return index
