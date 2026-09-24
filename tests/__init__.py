# -*- coding: utf-8 -*-
"""tests —— 单元测试。

 discovers 加载本包时会先执行这里：为 Qt/PyQt5 UI 测试创建全局 offscreen
 QApplication，避免多个 UI 测试模块在同一进程中反复初始化 Qt 平台插件导致崩溃。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    _APP = QApplication([])
