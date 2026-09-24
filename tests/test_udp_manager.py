# -*- coding: utf-8 -*-
"""udp_manager 网络重连辅助的单元测试：probe_bind 试绑（纯 socket，不起线程）。"""

import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from network.udp_manager import UdpManager


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestProbeBind(unittest.TestCase):
    """菜单「设置→网络绑定…」的本地试绑（决策 25）。"""

    def test_occupied_port_reports_error_then_releases(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        try:
            err = UdpManager.probe_bind("127.0.0.1", port)
            self.assertIsNotNone(err)
            self.assertIn("绑定失败", err)
        finally:
            holder.close()
        # 释放后可绑定
        self.assertIsNone(UdpManager.probe_bind("127.0.0.1", port))

    def test_free_port_returns_none(self):
        self.assertIsNone(UdpManager.probe_bind("127.0.0.1", _free_udp_port()))


if __name__ == "__main__":
    unittest.main()
