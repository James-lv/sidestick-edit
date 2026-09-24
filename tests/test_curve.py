# -*- coding: utf-8 -*-
"""test_curve —— signed_curve：18 点幅值表 → 带符号绘图坐标（决策 21）。"""
import io
import os
import unittest

from core import preset_store
from core.curve import signed_curve

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRESETS = os.path.join(_REPO, "config", "presets.yaml")


def _ch0(pid):
    presets = preset_store.parse_presets(io.open(_PRESETS, encoding="utf-8").read())
    return next(p["channels"][0] for p in presets if p["id"] == pid)


class TestSignedCurve(unittest.TestCase):
    """用真实出厂数据 state_1（对称力）验证变换规则。"""

    @classmethod
    def setUpClass(cls):
        cls.d = _ch0("state_1")

    def test_length_preserved_and_monotonic(self):
        xs, ys = signed_curve(self.d["pos_pts"], self.d["force_pts"])
        self.assertEqual(len(xs), 18)
        self.assertEqual(len(ys), 18)
        # x 从 -max 单调升到 +max（允许中点两 x 相等 → 启动力竖线）
        self.assertTrue(all(xs[i] <= xs[i + 1] for i in range(17)))

    def test_negative_half_in_third_quadrant(self):
        xs, ys = signed_curve(self.d["pos_pts"], self.d["force_pts"])
        self.assertLess(xs[0], 0)
        self.assertLess(ys[0], 0)
        self.assertAlmostEqual(xs[0], -18.5)
        self.assertAlmostEqual(ys[0], -31.81)
        self.assertAlmostEqual(xs[-1], 18.5)
        self.assertAlmostEqual(ys[-1], 31.81)

    def test_midpoint_breakout_vertical_link(self):
        # 两半首点均在中位 pos=0，力 +F0 / -F0 → 相邻两点画原点竖线
        xs, ys = signed_curve(self.d["pos_pts"], self.d["force_pts"])
        self.assertEqual(xs[8], 0.0)
        self.assertEqual(xs[9], 0.0)
        self.assertAlmostEqual(ys[8], -1.58)   # 负半首点（取负后）
        self.assertAlmostEqual(ys[9], 1.58)    # 正半首点

    def test_asymmetric_force_roll(self):
        # 滚转：正半最大 28.91、负半最大 17（不对称）→ 左低右高，均按幅值还原
        presets = preset_store.parse_presets(io.open(_PRESETS, encoding="utf-8").read())
        roll = next(p["channels"][1] for p in presets if p["id"] == "state_1")
        xs, ys = signed_curve(roll["pos_pts"], roll["force_pts"])
        self.assertAlmostEqual(min(ys[:9]), -17.00, places=2)
        self.assertAlmostEqual(max(ys[9:]), 28.91, places=2)

    def test_arbitrary_input_no_mutation(self):
        pos = [float(i) for i in range(18)]
        force = [float(i) / 2 for i in range(18)]
        xs, ys = signed_curve(pos, force)
        self.assertEqual(xs[:9], [-float(i) for i in range(17, 8, -1)])
        self.assertEqual(ys[9:], force[:9])
        self.assertEqual(pos[9], 9.0)         # 入参未被改写


if __name__ == "__main__":
    unittest.main()
