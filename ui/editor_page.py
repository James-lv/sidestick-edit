# -*- coding: utf-8 -*-
"""editor_page —— 通道编辑页（QTabWidget：按配置显示通道）。

各 tab 由具有完整预设数据的通道驱动（顺序与 protocol.yaml 一致），
每个 tab 内嵌 ChannelPage。切 tab 时重绘该通道（值 + 蓝字），
保证「加载预设 / 下载后回到本页」看到的是最新编辑态。
"""

from PyQt5.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ui.channel_page import ChannelPage


class EditorPage(QWidget):
    """具有完整预设数据的通道编辑容器。"""

    def __init__(self, backend, parent=None, back_callback=None):
        super().__init__(parent)
        self._backend = backend
        self._back_callback = back_callback

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget(self)
        self._pages = []                        # 与可编辑通道顺序一致
        for ch_id in backend.data_channels():
            page = ChannelPage(backend, ch_id["index"], ch_id["name"],
                              back_callback=self._back_callback)
            self._pages.append(page)
            self._tabs.addTab(page, ch_id["name"])
        self._tabs.currentChanged.connect(self._on_tab_changed)
        v.addWidget(self._tabs)

    # ------------------------------------------------------------
    def current_channel(self) -> int:
        """当前激活的通道 index。"""
        idx = self._tabs.currentIndex()
        if 0 <= idx < len(self._pages):
            return self._pages[idx]._ch
        return 0

    def refresh_all(self):
        """整页重绘（进入编辑态/下载后调用）。"""
        for page in self._pages:
            page.refresh()

    def refresh_current(self):
        index = self._tabs.currentIndex()
        if index >= 0 and self._tabs.tabBar().isTabVisible(index):
            self._pages[index].refresh()

    def fit_current(self):
        """自适应当前可见 tab 的曲线（从预设管理页进入编辑页时调用）。"""
        index = self._tabs.currentIndex()
        if index >= 0 and self._tabs.tabBar().isTabVisible(index):
            self._pages[index].fit_curve()

    def set_channel_visible(self, channel_index: int, visible: bool) -> bool:
        """设置通道标签页可见性；无对应编辑页时返回 False。"""
        tab_index = next(
            (index for index, page in enumerate(self._pages)
             if page._ch == channel_index),
            None,
        )
        if tab_index is None:
            return False

        self._tabs.setTabVisible(tab_index, visible)
        visible_indexes = [
            index for index in range(len(self._pages))
            if self._tabs.tabBar().isTabVisible(index)
        ]
        if not visible_indexes:
            self._tabs.hide()
        else:
            self._tabs.show()
            if self._tabs.currentIndex() not in visible_indexes:
                self._tabs.setCurrentIndex(visible_indexes[0])
        return True

    def _on_tab_changed(self, _index):
        self.refresh_current()

    def channel_pages(self):
        return list(self._pages)
