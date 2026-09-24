# -*- coding: utf-8 -*-
"""selfcheck 集成测试：整体跑一遍阶段 1 自检，作为回归闸门。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import selfcheck


class TestSelfcheckIntegration(unittest.TestCase):
    def test_selfcheck_exits_zero(self):
        # 覆盖：配置加载 / 182B+16B 断言 / 组解包往返 / 换算抽检 /
        # 预设往返 / 出厂自恢复（临时目录，不碰真实 config）
        self.assertEqual(selfcheck.main(), 0)


if __name__ == "__main__":
    unittest.main()
