# -*- coding: utf-8 -*-
"""ControlModeBox —— 底部灰框六模式按钮组。

交互规则（用户 2026-09-09 确认）：
    - 六个按钮对应控制模式 1..6：抖杆/脉冲/倍脉冲/扫频/正弦/阶跃。
    - 点击某按钮：
        • 若当前模式 == 该按钮模式 → 切到 0（OFF），按钮全部抬起。
        • 若当前模式 != 该按钮模式 → 直接切到该模式，原模式按钮抬起，不发 0。
    - 本组件只负责 UI 状态与 mode_selected 信号；调用方负责把模式值下发给后端
      （backend.set_control_mode(channel, mode)），并回灌当前通道的实时模式。

样式：灰色边框容器（与截图底部灰框一致），按钮 checkable，当前选中按钮按下态。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QGroupBox, QHBoxLayout, QLineEdit, QLabel,
                             QVBoxLayout, QPushButton, QSizePolicy, QWidget)


class ControlModeBox(QGroupBox):
    #: 用户选定模式时发出（0..6，0 表示再次点击同一按钮关闭）
    mode_selected = pyqtSignal(int)

    _BUTTONS = [
        (1, "抖杆"),
        (2, "脉冲"),
        (3, "倍脉冲"),
        (4, "扫频"),
        (5, "正弦"),
        (6, "阶跃"),
    ]

    _MODE_DETAILS = {
        1: ("100.0", "10.0", "抖杆：幅值 100.0，频率 10.0 Hz。"),
        2: ("0.5", "0.5", "脉冲：+0.5 持续 1 秒、归零 1 秒，按 2 秒周期重复（0.5 Hz）。"),
        3: (
            "0.5",
            "0",
            "倍脉冲：0–1 秒 +0.5，1–2 秒为 0，2–3 秒 −0.5，3–6 秒为 0。"
            "单次序列，无固定重复频率；幅值按绝对值显示。",
        ),
        4: ("0.5", "0.5–5.0", "扫频：幅值 ±0.5，频率从 0.5 Hz 线性扫至 5.0 Hz，持续 6 秒。"),
        5: ("0.5", "1.0", "正弦：幅值 ±0.5，频率 1.0 Hz。"),
        6: ("0.5", "0", "阶跃：0–6 秒保持 +0.5，之后恢复为 0；无周期振荡。"),
    }

    def __init__(self, parent=None, columns=1):
        super().__init__(parent)
        self._current_mode = 0
        self._buttons = {}
        self._amp_inputs = {}
        self._freq_inputs = {}
        self._time_inputs = {}
        self._columns = max(1, int(columns))

        self.setTitle("测试模式")
        self.setObjectName("ModeContainer")
        self.setStyleSheet(
            "QGroupBox#ModeContainer {"
            "  background-color: #ffffff;"
            "  border: 1px solid #d0d0d0;"
            "  border-radius: 8px;"
            "  margin-top: 1.6ex;"
            "  padding-top: 8px;"
            "  font-weight: bold;"
            "  color: #444444;"
            "  font-size: 13pt;"
            "}"
            "QGroupBox#ModeContainer::title {"
            "  subcontrol-origin: margin;"
            "  subcontrol-position: top left;"
            "  left: 12px;"
            "  padding: 0 6px;"
            "  color: #555555;"
            "  background-color: #ffffff;"
            "}"
            "QGroupBox#ModeContainer > QWidget {"
            "  background: transparent;"
            "}"
            "QGroupBox#ModeContainer QPushButton {"
            "  background-color: #f2f8ff;"
            "  color: #1e1e1e;"
            "  border: 1px solid #7aa9de;"
            "  border-radius: 6px;"
            "  text-align: center;"
            "  padding: 0 12px;"
            "  min-width: 50px;"
            "  max-width: 120px;"
            "  min-height: 32px;"
            "  font-size: 16px;"
            "  qproperty-icon: none;"
            "}"
            "QGroupBox#ModeContainer QPushButton:hover {"
            "  background-color: #edf5ff;"
            "  color: #1f5fbf;"
            "}"
            "QGroupBox#ModeContainer QPushButton:checked {"
            "  background-color: #d6ebff;"
            "  color: #1c5fb3;"
            "  border: 1px solid #5a93e6;"
            "}"
            "QGroupBox#ModeContainer QPushButton:pressed {"
            "  background-color: #a9c9e8;"
            "}"
            "QGroupBox#ModeContainer QPushButton:disabled {"
            "  background: #f0f0f0;"
            "  color: #a0a0a0;"
            "}"
            "QGroupBox#ModeContainer QLineEdit {"
            "  border: 1px solid #a6b5c7;"
            "  background: #ffffff;"
            "  min-height: 30px;"
            "  max-height: 30px;"
            "  min-width: 56px;"
            "  max-width: 56px;"
            "  padding: 0 6px;"
            "  font-size: 14px;"
            "}"
            "QGroupBox#ModeContainer QLabel {"
            "  color: #2a2a2a;"
            "  font-size: 15px;"
            "  padding: 0 2px;"
            "  font-weight: normal;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 20, 12, 8)
        layout.setAlignment(Qt.AlignTop)

        for mode, label in self._BUTTONS:
            amplitude, frequency, description = self._MODE_DETAILS[mode]
            row = QWidget(self)
            row.setFixedHeight(36)
            row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(2)

            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(False)
            btn.setChecked(False)
            btn.setToolTip(description)
            btn.setFixedWidth(68)
            btn.setFixedHeight(32)
            btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #f4f9ff;"
                "  color: #1f1f1f;"
                "  border: 1px solid #7aa9de;"
                "  border-radius: 5px;"
                "}"
                "QPushButton:checked {"
                "  background-color: #d4ebff;"
                "  color: #1c5fb3;"
                "  border: 1px solid #5d9ae9;"
                "}"
            )
            btn.clicked.connect(lambda checked, m=mode: self._on_clicked(m))
            h.addWidget(btn)
            h.addSpacing(6)

            amp_label = QLabel("幅值")
            amp_label.setFixedWidth(40)
            amp_edit = QLineEdit(amplitude)
            amp_edit.setStyleSheet(
                "QLineEdit {"
                "  min-width: 42px;"
                "  max-width: 42px;"
                "  padding: 2px 2px;"
                "}"
            )
            amp_edit.setAlignment(Qt.AlignCenter)
            h.addWidget(amp_label)
            h.addSpacing(2)
            h.addWidget(amp_edit)
            h.addSpacing(14)

            freq_label = QLabel("频率")
            freq_label.setFixedWidth(40)
            freq_edit = QLineEdit(frequency)
            freq_edit.setStyleSheet(
                "QLineEdit {"
                "  min-width: 30px;"
                "  max-width: 30px;"
                "  padding: 2px 2px;"
                "}"
            )
            freq_edit.setAlignment(Qt.AlignCenter)
            h.addWidget(freq_label)
            h.addSpacing(2)
            h.addWidget(freq_edit)
            hz_label = QLabel("Hz")
            hz_label.setFixedWidth(24)
            hz_label.setStyleSheet("padding: 0px;")
            h.addWidget(hz_label)
            h.addSpacing(14)

            time_label = QLabel("时间")
            time_label.setFixedWidth(40)
            time_edit = QLineEdit()
            time_edit.setStyleSheet(
                "QLineEdit {"
                "  min-width: 30px;"
                "  max-width: 30px;"
                "  padding: 2px 2px;"
                "}"
            )
            time_edit.setAlignment(Qt.AlignCenter)
            h.addWidget(time_label)
            h.addSpacing(2)
            h.addWidget(time_edit)
            s_label = QLabel("S")
            s_label.setFixedWidth(18)
            s_label.setStyleSheet("padding: 0px;")
            h.addWidget(s_label)
            

            h.addStretch(1)
            layout.addWidget(row, 0, Qt.AlignTop)
            self._buttons[mode] = btn
            self._amp_inputs[mode] = amp_edit
            self._freq_inputs[mode] = freq_edit
            self._time_inputs[mode] = time_edit

    # ------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------
    def _on_clicked(self, mode: int):
        """点击按钮：同模式再次点击 → 0；不同模式 → 直接切换。"""
        target_mode = 0 if self._current_mode == mode else mode
        self.set_mode(target_mode)
        self.mode_selected.emit(self._current_mode)

    def set_mode(self, mode: int):
        """由调用方回灌当前通道模式（0..6），同步按钮按下态。"""
        if not 0 <= mode <= 6:
            return
        self._current_mode = mode
        for m, btn in self._buttons.items():
            btn.setChecked(m == mode)

    def get_mode(self) -> int:
        return self._current_mode

    def reset(self):
        """切通道或失能前重置为 0。"""
        self.set_mode(0)
