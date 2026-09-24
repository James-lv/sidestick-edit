# -*- coding: utf-8 -*-
"""network_dialog —— 「设置→网络绑定…」对话框（对齐原版 C++ 菜单栏，决策 25）。

四个字段与 protocol.yaml network 段一一对应：
    本机绑定（local_ip/local_port）：本机收发包端口，0.0.0.0 = 任意网卡
    控制器   （target_ip/target_port）：下行报文目标地址

确定 → backend.apply_network：本地试绑 → 重建 socket 立即生效。
失败保留对话框提示；成功即关闭。
"""

import ipaddress

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel,
                             QLineEdit, QMessageBox, QVBoxLayout)

#: 字段中文名（与 network 段键一一对应，顺序即表单行序）
_FIELD_ZH = {
    "local_ip": "本机绑定 IP",
    "local_port": "本机端口",
    "target_ip": "控制器 IP",
    "target_port": "控制器端口",
}
#: 值带引号风格（IP 习惯引号，端口纯数字——与 render 对齐）
_HINT = ("本机端口 = 收发包共用端口；绑定 IP 用 0.0.0.0 表示任意网卡。\n"
         "确定后立即重建 socket 生效。")


class NetworkDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self.setWindowTitle("网络绑定")
        self.setModal(True)
        self._edits = {}
        self._build()

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(6)

        net = self._backend.get_network()
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        for key in ("local_ip", "local_port", "target_ip", "target_port"):
            edit = QLineEdit(str(net[key]), self)
            edit.setObjectName("NetField_" + key)
            edit.setMinimumWidth(200)
            if key.endswith("_ip"):
                edit.setPlaceholderText("0.0.0.0 = 任意网卡" if key == "local_ip"
                                        else "如 192.168.1.100")
            self._edits[key] = edit
            form.addRow(_field_label(_FIELD_ZH[key]), edit)
        root.addLayout(form)

        hint = QLabel(_HINT, self)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addSpacing(4)
        root.addWidget(hint)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                               self)
        box.button(QDialogButtonBox.Ok).setText("确定")
        box.button(QDialogButtonBox.Cancel).setText("取消")
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        root.addSpacing(6)
        root.addWidget(box)

        self.setMinimumWidth(420)
        self._edits["local_ip"].setFocus()

    # ------------------------------------------------------------
    # 槽
    # ------------------------------------------------------------
    def _collect(self):
        """收集并校验 4 字段；返回 (values: dict|None, err: str|None)。"""
        vals = {k: e.text().strip() for k, e in self._edits.items()}
        for key in ("local_ip", "target_ip"):
            try:
                ipaddress.IPv4Address(vals[key])
            except ValueError:
                return None, "%s 需为 IPv4 地址（如 192.168.1.100）" % _FIELD_ZH[key]
        for key in ("local_port", "target_port"):
            try:
                port = int(vals[key])
            except ValueError:
                return None, "%s 需为整数端口" % _FIELD_ZH[key]
            if not 1 <= port <= 65535:
                return None, "%s 超出范围（1-65535）" % _FIELD_ZH[key]
            vals[key] = port
        return vals, None

    def _on_accept(self):
        vals, err = self._collect()
        if err is not None:
            QMessageBox.warning(self, "网络绑定", err)
            return
        ok, msg = self._backend.apply_network(vals)
        if not ok:
            QMessageBox.warning(self, "网络绑定", msg)
            return
        if msg != "已生效":
            QMessageBox.information(self, "网络绑定", msg)
        self.accept()


def _field_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setMinimumWidth(76)
    return lab
