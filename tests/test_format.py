# -*- coding: utf-8 -*-
"""format_value 显示规则单测：替代 per-field decimals 配置。"""

import unittest

from core.format import format_value


class TestFormatValue(unittest.TestCase):
    def test_integer_floats_show_as_int(self):
        self.assertEqual(format_value(240.0), "240")
        self.assertEqual(format_value(1.0), "1")

    def test_plain_int(self):
        self.assertEqual(format_value(3), "3")

    def test_negative_zero_normalized(self):
        self.assertEqual(format_value(-0.0), "0")

    def test_non_integer_two_decimals(self):
        self.assertEqual(format_value(5.5), "5.50")
        self.assertEqual(format_value(-2.0), "-2")   # 整值仍走整数分支
        self.assertEqual(format_value(1.234), "1.23")

    def test_small_magnitude_protected(self):
        # 小量用 4 位，避免被 2 位吞成 0.00
        self.assertEqual(format_value(0.001), "0.0010")
        self.assertEqual(format_value(0.0001), "0.0001")

    def test_non_numeric_passthrough(self):
        self.assertEqual(format_value("n/a"), "n/a")


if __name__ == "__main__":
    unittest.main()
