# -*- coding: utf-8 -*-
"""editor_page —— 通道编辑页（QTabWidget：俯仰 / 滚转）。

两个 tab 由 protocol.yaml 的 channel_ids 驱动（顺序 = index 0/1），
每个 tab 内嵌 ChannelPage。切 tab 时重绘该通道（值 + 蓝字），
保证「加载预设 / 下载后回到本页」看到的是最新编辑态。
"""

from PyQt5.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ui.channel_page import ChannelPage


class EditorPage(QWidget):
    """双通道（俯仰/滚转）编辑容器。"""

    def __init__(self, backend, parent=None, back_callback=None):
        super().__init__(parent)
        self._backend = backend
        self._back_callback = back_callback

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget(self)
        self._pages = []                        # 与 channel_ids 顺序一致
        for ch_id in backend.channels():
            page = ChannelPage(backend, ch_id["index"], ch_id["name"],
                              back_callback=self._back_callback)
            self._pages.append(page)
            self._tabs.addTab(page, ch_id["name"])
        self._tabs.currentChanged.connect(self._on_tab_changed)
        v.addWidget(self._tabs)

    # ------------------------------------------------------------
    def current_channel(self) -> int:
        """当前激活的通道 index（0/1）。"""
        idx = self._tabs.currentIndex()
        if 0 <= idx < len(self._pages):
            return self._pages[idx]._ch
        return 0

    def refresh_all(self):
        """整页重绘（进入编辑态/下载后调用）。"""
        for page in self._pages:
            page.refresh()

    def refresh_current(self):
        page = self._pages[self._tabs.currentIndex()]
        page.refresh()

    def fit_current(self):
        """自适应当前可见 tab 的曲线（从预设管理页进入编辑页时调用）。"""
        self._pages[self._tabs.currentIndex()].fit_curve()

    def _on_tab_changed(self, _index):
        self.refresh_current()

    def channel_pages(self):
        return list(self._pages)
