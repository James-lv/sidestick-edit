# -*- coding: utf-8 -*-
"""preset_manager —— 上层预设管理页（Joystick 启动首页）。

布局：
    ┌────────────────────────────┬─────────────────────────────┐
    │ 预设列表（State/User 分组）  │   [新建] [编辑] [删除] [下载] │
    │  行文本 = label（可改名）     │                             │
    │  双击 = 编辑                 │   [实时状态]                 │
    │                             │   俯仰  角度  力             │
    │                             │   滚转  角度  力             │
    └────────────────────────────┴─────────────────────────────┘

行为（决策 17）：
    - 新建：backend.create_preset()（复制 模式6 综合力感，id 自动 user_+时间戳），仅创建预设并选中它，不切到编辑页。
    - 编辑 / 双击：加载预设到编辑态（俯仰+滚转，标蓝不发送）→ emit edit_requested 切编辑页。
    - 删除：确认后删除用户新建；出厂（builtin）预设后端拒绝，界面按钮禁用。
    - 下载：backend.download_preset(id)（发送不写文件）。
    - 改名：仅在 User 分组行内编辑 label（builtin 行只读），触发 update_preset。
"""

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (QAbstractItemView, QGridLayout, QGroupBox, QHBoxLayout,
                             QHeaderView, QLabel, QMessageBox, QPushButton,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from core.backend import USER_CATEGORY
from core.format import format_value


class PresetManagerPage(QWidget):
    #: 用户点了「编辑」（或双击）：携带预设 id，主窗口据此切到编辑页
    edit_requested = pyqtSignal(str)
    test_requested = pyqtSignal()

    #: State / User 分组顺序（State 组界面显示「出厂」，避免与预设名混淆）
    _GROUPS = ("State", USER_CATEGORY)
    _GROUP_LABELS = {"State": "出厂", USER_CATEGORY: "用户"}

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._item_by_id = {}           # preset_id -> QTreeWidgetItem
        self._updating = False

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- 左：预设列表 ------------------------------------------
        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["预设"])
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.setIndentation(28)
        self._tree.setMinimumWidth(420)
        self._tree.itemSelectionChanged.connect(self._on_selection)
        self._tree.itemDoubleClicked.connect(lambda item, col: self._on_edit())
        self._tree.itemChanged.connect(self._on_item_renamed)
        root.addWidget(self._tree, 1)

        # ---- 右：按钮 + 状态 ---------------------------------------
        right = QWidget(self)
        right.setObjectName("PresetRightPanel")
        # 稍宽 + 内边距，避免挤压（按钮 + 状态 panel）
        right.setMaximumWidth(320)
        right.setMinimumWidth(280)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 14, 14, 14)
        rv.setSpacing(10)

        btn_edit = QPushButton("编辑")
        btn_new = QPushButton("新建")
        btn_del = QPushButton("删除")
        btn_dl = QPushButton("下载")
        btn_new.clicked.connect(self._on_new)
        btn_edit.clicked.connect(self._on_edit)
        btn_del.clicked.connect(self._on_delete)
        btn_dl.clicked.connect(self._on_download)
        self._btn_edit, self._btn_del, self._btn_dl = btn_edit, btn_del, btn_dl
        for b in (btn_edit, btn_new, btn_del, btn_dl):
            rv.addWidget(b)
        rv.addStretch(1)              # 弹簧：让「实时状态」与提示文字靠下

        status = QGroupBox("实时状态", right)
        sv = QVBoxLayout(status)
        sv.setContentsMargins(10, 8, 10, 8)
        sv.setSpacing(8)
        self._status_labels = {}
        for ch_id in backend.channels():
            name = QLabel(ch_id["name"], status)
            name.setObjectName("ChName")
            angle = QLabel("—")
            force = QLabel("—")
            angle.setMinimumWidth(44)
            force.setMinimumWidth(44)
            angle.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            force.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            angle.setObjectName("angle_%d" % ch_id["index"])
            force.setObjectName("force_%d" % ch_id["index"])

            # 每通道一行：名字占左，角度/力并排显示
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(6)
            grid.addWidget(name, 0, 0, 1, 1)
            grid.addWidget(QLabel("角度:", status), 0, 1)
            grid.addWidget(angle, 0, 2)
            grid.addWidget(QLabel("力:", status), 0, 3)
            grid.addWidget(force, 0, 4)
            grid.setColumnStretch(0, 1)
            sv.addLayout(grid)
            self._status_labels[ch_id["index"]] = (angle, force)
        rv.addWidget(status)

        self._hint = QLabel("出厂预设不可删除；行内可改「用户」预设名")
        self._hint.setObjectName("Hint")
        self._hint.setWordWrap(True)
        rv.addWidget(self._hint)

        root.addWidget(right, 0)

        self.refresh_list()
        self._wire()

    # ------------------------------------------------------------
    def _wire(self):
        be = self._backend
        be.preset_list_changed.connect(self.refresh_list)
        be.telemetry_received.connect(self._on_telemetry)

    def _current_id(self):
        item = self._tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.UserRole)

    def _current_preset(self):
        return self._find(self._current_id())

    def _find(self, pid):
        if not pid:
            return None
        return next((p for p in self._backend.get_presets() if p["id"] == pid), None)

    # ------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------
    @pyqtSlot()
    def refresh_list(self):
        self._tree.blockSignals(True)
        self._tree.clear()
        self._item_by_id = {}
        presets = self._backend.get_presets()
        groups = {}
        for preset in presets:
            cat = preset.get("category") or "State"
            groups.setdefault(cat, []).append(preset)
        for cat in self._GROUPS:
            entries = sorted(groups.get(cat, []),
                             key=lambda p: p.get("label", p["id"]))
            if not entries:
                continue
            parent = QTreeWidgetItem([self._GROUP_LABELS.get(cat, cat)])
            parent.setFlags(Qt.ItemIsEnabled)
            for preset in entries:
                builtin = bool(preset.get("builtin"))
                item = QTreeWidgetItem([preset.get("label", preset["id"])])
                item.setData(0, Qt.UserRole, preset["id"])
                item.setToolTip(0, preset.get("description", ""))
                if builtin:
                    item.setToolTip(0, (item.toolTip(0) + "（出厂预设，不可删除）").strip())
                else:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                parent.addChild(item)
                self._item_by_id[preset["id"]] = item
            self._tree.addTopLevelItem(parent)
            parent.setExpanded(True)
        self._tree.blockSignals(False)
        self._sync_buttons()

    def select_id(self, pid):
        item = self._item_by_id.get(pid)
        if item is not None:
            self._tree.setCurrentItem(item)

    def _sync_buttons(self):
        preset = self._current_preset()
        has = preset is not None
        self._btn_edit.setEnabled(has)
        self._btn_dl.setEnabled(has)
        self._btn_del.setEnabled(has and not preset.get("builtin"))

    def _on_selection(self):
        self._sync_buttons()

    # ------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------
    def _on_new(self):
        new_id = self._backend.create_preset()
        if not new_id:
            return
        self.refresh_list()
        self.select_id(new_id)
        # 保持在预设管理页，只创建并选中新预设

    def _on_edit(self):
        self._edit_current()

    def _edit_current(self):
        pid = self._current_id()
        if not pid:
            return
        preset = self._find(pid)
        if preset is None:
            return
        for ch in sorted(preset["channels"]):       # 全部通道（俯仰+滚转）
            self._backend.load_preset(ch, pid)
        self.edit_requested.emit(pid)

    def _on_delete(self):
        preset = self._current_preset()
        if not preset or preset.get("builtin"):
            return
        name = preset.get("label", preset["id"])
        ret = QMessageBox.question(
            self, "删除预设",
            "确定删除用户预设「%s」吗？" % name,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self._backend.delete_preset(preset["id"])

    def _on_download(self):
        pid = self._current_id()
        if pid:
            self._backend.download_preset(pid)

    def _on_test(self):
        self.test_requested.emit()

    def _on_item_renamed(self, item, col):
        if self._updating or col != 0:
            return
        preset = self._find(item.data(0, Qt.UserRole))
        if preset is None:
            return
        if preset.get("builtin"):
            self._restore_text(item, preset)            # 出厂只读还原
            return
        label = item.text(0).strip()
        if label and label != preset.get("label"):
            self._backend.update_preset(preset["id"], {"label": label})
        else:
            self._restore_text(item, preset)

    @staticmethod
    def _restore_text(item, preset):
        item.setText(0, preset.get("label", preset["id"]))

    # ------------------------------------------------------------
    # 实时状态
    # ------------------------------------------------------------
    @pyqtSlot(dict)
    def _on_telemetry(self, channels):
        for ch, data in channels.items():
            labels = self._status_labels.get(ch)
            if labels is None:
                continue
            angle, force = labels
            angle.setText(format_value(data.get("Position", 0)))
            force.setText(format_value(data.get("LoadCellForce", 0)))
