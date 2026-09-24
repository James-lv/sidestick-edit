# -*- coding: utf-8 -*-
"""main_window —— 主窗口装配（2026-09-09 用户确认的最终形态）。

布局（自上而下）：
    ┌────────────────────────────────────────────────────────────┐
    │ [菜单栏] 设置 → 网络绑定…（IP/端口，决策 25）                  │
    ├────────────────────────────────────────────────────────────┤
    │ [蓝条] ← 返回预设管理 │ …  │ ●网络连接 │ ●作为主机(按钮)      │
    ├────────────────────────────────────────────────────────────┤
    │ QStackedWidget                                             │
    │   页0 PresetManagerPage（预设列表：新建/编辑/删除/下载）       │
    │   页1 EditorPage（俯仰/滚转 两 tab 编辑页）               │
    ├────────────────────────────────────────────────────────────┤
    │ [灰框] 抖杆 脉冲 倍脉冲 扫频 正弦 阶跃（固定操作俯仰，轴1）      │
    └────────────────────────────────────────────────────────────┘

交互要点：
    - 预设管理页启动为首页；Edit/双击 → 加载预设进编辑态并切到编辑页。
    - 编辑页左上角蓝条「← 返回预设管理」返回（仅在编辑页可见）。
    - 蓝条右侧：网络连接 = 指示灯 + 文字（非按钮，link_state_changed）；
      「作为主机」= 指示灯 + 可选中按钮（选中变蓝，旁边灯同步状态；
      host 模式只影响底部灰框控制模式使能，不影响参数发送，ARCHITECTURE §7.3）。
    - 底部灰框固定只操作俯仰通道（axis=1，channel index 0）。
"""

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel,
                             QMainWindow, QPushButton, QStackedWidget,
                             QVBoxLayout, QWidget)

from ui.channel_page import ChannelPage
from ui.editor_page import EditorPage
from ui.preset_manager import PresetManagerPage
from ui.widgets.control_mode_box import ControlModeBox

_ASSETS = Path(__file__).resolve().parent.parent / "assets"


class MainWindow(QMainWindow):
    #: 预设管理页 / 编辑页 / 测试页在 QStackedWidget 中的下标
    PAGE_PRESETS, PAGE_EDITOR, PAGE_TEST = 0, 1, 2

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend

        # 俯仰 = protocol.yaml channel_ids 中 axis==1 的那条
        self._pitch_index = next(
            (ch["index"] for ch in backend.channels() if ch["axis"] == 1), 0)

        self.setWindowTitle("BCLS 侧杆编辑界面")
        self.resize(1440, 800)
        self._build_ui()
        self._wire_signals()
        self._sync_initial_state()

    # ------------------------------------------------------------
    # UI 组装
    # ------------------------------------------------------------
    def _build_ui(self):
        # ① 菜单栏（原版 C++ 最上方「设置」，决策 25：设置→网络绑定…）
        self._build_menu_bar()

        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ② 顶部蓝条（固定高度）
        root.addWidget(self._build_top_bar())

        # ③ 内容区：预设 / 编辑 / 测试三页切换
        self._page_tabs = self._build_page_tabs(central)
        root.addWidget(self._page_tabs)

        self._stack = QStackedWidget(central)
        self._preset_page = PresetManagerPage(self._backend, central)
        self._editor_page = EditorPage(
            self._backend, central,
            back_callback=lambda: self._stack.setCurrentIndex(self.PAGE_PRESETS))
        self._test_page = self._build_test_page(central)
        self._stack.addWidget(self._preset_page)
        self._stack.addWidget(self._editor_page)
        self._stack.addWidget(self._test_page)
        root.addWidget(self._stack, 1)

        self.setCentralWidget(central)

    def _build_page_tabs(self, parent=None):
        """水平页签：预设 / 测试，类似编辑页的俯仰 / 滚转。"""
        container = QWidget(parent)
        container.setObjectName("PageTabs")
        container.setFixedHeight(42)
        container.setStyleSheet(
            "QWidget#PageTabs {"
            "  background-color: #f3f6fa;"
            "  border: none;"
            "}"
            "QPushButton {"
            "  background-color: #eaf2fb;"
            "  color: #3a3a3a;"
            "  border: 1px solid #cfe0ee;"
            "  border-radius: 8px 8px 0px 0px;"
            "  padding: 8px 26px;"
            "  font-size: 17px;"
            "  min-height: 28px;"
            "  margin: 0px;"
            "}"
            "QPushButton:checked {"
            "  background-color: #ffffff;"
            "  color: #1a1a1a;"
            "  border: 1px solid #cfe0ee;"
            "  border-bottom: 1px solid #ffffff;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #dfeefb;"
            "}"
        )
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 6, 10, 0)
        layout.setSpacing(0)

        self._preset_tab_btn = QPushButton("预设", container)
        self._preset_tab_btn.setCheckable(True)
        self._preset_tab_btn.setChecked(True)
        self._preset_tab_btn.clicked.connect(lambda: self._stack.setCurrentIndex(self.PAGE_PRESETS))

        self._test_tab_btn = QPushButton("测试", container)
        self._test_tab_btn.setCheckable(True)
        self._test_tab_btn.clicked.connect(lambda: self._stack.setCurrentIndex(self.PAGE_TEST))

        layout.addWidget(self._preset_tab_btn)
        layout.addWidget(self._test_tab_btn)
        layout.addStretch(1)

        return container

    def _build_menu_bar(self):
        """菜单栏：设置 → 网络绑定…（对齐原版 C++ 顶栏，决策 25）。"""
        menubar = self.menuBar()
        menubar.setObjectName("MainMenuBar")
        m_settings = menubar.addMenu("设置(&S)")
        act_net = m_settings.addAction("网络绑定…")
        act_net.setStatusTip("修改本机/控制器 IP 与端口，立即生效并持久化")
        act_net.triggered.connect(self._open_network_dialog)

    def _build_test_page(self, parent=None):
        page = QWidget(parent)
        page.setObjectName("TestPage")
        page.setStyleSheet(
            "QWidget#TestPage {"
            "  background-color: #f0f0f0;"
            "}"
        )

        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 30)
        layout.setSpacing(12)

        content = QWidget(page)
        content.setObjectName("TestContent")
        content.setStyleSheet(
            "QWidget#TestContent {"
            "  background-color: #ffffff;"
            "  border: 1px solid #d0d0d0;"
            "  border-radius: 8px;"
            "}"
        )
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(0)

        mode_container = QFrame(content)
        mode_container.setObjectName("ModeContainer")
        mode_container.setMinimumWidth(330)
        mode_container.setMaximumWidth(420)
        mode_container.setMinimumHeight(240)
        mode_container.setStyleSheet(
            "QFrame#ModeContainer {"
            "  background-color: #ffffff;"
            "  border: none;"
            "  padding: 0px;"
            "}"
        )
        mode_layout = QVBoxLayout(mode_container)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(0)
        self._mode_box = ControlModeBox(mode_container, columns=1)
        self._mode_box.setEnabled(True)
        mode_layout.addWidget(self._mode_box)

        plot_panel = QWidget(content)
        plot_panel.setObjectName("TestPlotPanel")
        plot_panel.setStyleSheet(
            "QWidget#TestPlotPanel {"
            "  background-color: #ffffff;"
            "  border: none;"
            "}"
        )
        plot_layout = QVBoxLayout(plot_panel)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)

        channel_page = ChannelPage(
            self._backend,
            self._pitch_index,
            "测试通道",
            parent=plot_panel,
            back_callback=lambda: self._stack.setCurrentIndex(self.PAGE_PRESETS),
        )
        channel_page._left_widget.hide()
        plot_layout.addWidget(channel_page, 1)

        content_layout.addWidget(mode_container, 0)
        content_layout.addWidget(plot_panel, 1)
        layout.addWidget(content, 1)

        return page

    def _build_top_bar(self):
        bar = QFrame(self)
        bar.setObjectName("TopBar")
        bar.setFixedHeight(52)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        self._title = QLabel("侧杆编辑界面", bar)
        self._title.setObjectName("BarTitle")
        layout.addWidget(self._title)
        layout.addStretch(1)

        # 右侧：网络连接 = 指示灯 + 文字（非按钮，对齐 MoogStyle）
        self._link_led = QLabel(bar)
        self._link_led.setObjectName("LedLabel")
        self._link_led.setFixedSize(32, 32)
        self._link_led.setScaledContents(True)
        layout.addWidget(self._link_led)

        self._link_text = QLabel("网络连接", bar)
        self._link_text.setObjectName("LinkText")
        layout.addWidget(self._link_text)

        return bar

    # ------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------
    def _wire_signals(self):
        be = self._backend

        # 预设管理 → 切编辑页 / 测试页
        self._preset_page.edit_requested.connect(self._on_edit_requested)
        self._preset_page.test_requested.connect(self._on_test_requested)
        self._stack.currentChanged.connect(self._update_page_tabs)
        self._stack.currentChanged.connect(self._on_page_changed)

        # 蓝条：连接状态
        be.link_state_changed.connect(self._on_link_changed)

        # 测试页内的功能按钮 → 后端：固定俯仰（axis=1）
        self._mode_box.mode_selected.connect(self._on_mode_selected)
        be.control_mode_changed.connect(self._on_control_mode_changed)

        self._update_page_tabs(self.PAGE_PRESETS)

    def _sync_initial_state(self):
        self._mode_box.set_mode(self._backend.get_control_mode(self._pitch_index))
        self._mode_box.setEnabled(True)
        self._set_link(False, "未连接")
        self._stack.setCurrentIndex(self.PAGE_PRESETS)
        # 初始 index 未变化 → currentChanged 不发射，手动补一次可见性同步
        self._on_page_changed(self.PAGE_PRESETS)

    # ------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------
    def _update_page_tabs(self, index):
        visible = index in (self.PAGE_PRESETS, self.PAGE_TEST)
        self._page_tabs.setVisible(visible)
        self._preset_tab_btn.setChecked(index == self.PAGE_PRESETS)
        self._test_tab_btn.setChecked(index == self.PAGE_TEST)

    @pyqtSlot(int)
    def _on_page_changed(self, index):
        pass

    @pyqtSlot(str)
    def _on_edit_requested(self, preset_id):
        # 进入编辑页前，全量刷新所有通道（编辑态已由 load_preset 更新）
        self._editor_page.refresh_all()
        self._stack.setCurrentIndex(self.PAGE_EDITOR)
        self._editor_page.fit_current()     # 决策 #26：上层进入后曲线自动自适应

    @pyqtSlot()
    def _on_test_requested(self):
        self._stack.setCurrentIndex(self.PAGE_TEST)

    @pyqtSlot(bool, str)
    def _on_link_changed(self, connected, info):
        self._set_link(connected, info)

    @pyqtSlot()
    def _open_network_dialog(self):
        """设置→网络绑定…：弹对话框，确认后 backend 重建 socket + 写回配置。"""
        from ui.network_dialog import NetworkDialog
        NetworkDialog(self._backend, self).exec_()

    def _set_link(self, connected, info):
        self._link_led.setPixmap(_load_pixmap(
            "led-green.png" if connected else "led-gry.png"))
        self._link_text.setToolTip(info)

    @pyqtSlot(int)
    def _on_mode_selected(self, mode):
        """灰框点击：固定下发俯仰通道（只有俯仰有抖杆/模式）。"""
        self._backend.set_control_mode(self._pitch_index, mode)

    @pyqtSlot(int, int, bool)
    def _on_control_mode_changed(self, ch, mode, dirty):
        if ch == self._pitch_index:
            self._mode_box.set_mode(mode)


def _load_pixmap(name):
    path = _ASSETS / name
    return QPixmap(str(path)) if path.exists() else QPixmap()
