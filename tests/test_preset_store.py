# -*- coding: utf-8 -*-
"""preset_store 单元测试：YAML 解析/渲染往返、通道数据校验、出厂状态、报错路径、原子写。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import preset_store


def _ch_data(**overrides):
    data = {
        "friction": 2.5,
        "breakout_force": 2,
        "negative_stop": -2010.87,
        "positive_stop": 2010.87,
        "pos_pts": [float(i) for i in range(18)],
        "force_pts": [float(i) / 2 for i in range(18)],
        "scale_factor": 100,
        "spring_force": 0,
        "damping_num": 0,
        "damping_den": 1,
        "force_offset": 0,
    }
    data.update(overrides)
    return data


def _state_block(pid, builtin=True):
    lines = ["  - id: %s" % pid,
             "    label: 状态",
             "    category: State"]
    if builtin:
        lines.append("    builtin: true")
    lines.append("    channels:")
    for ch in (0, 1):
        lines.append("      %d:" % ch)
        lines.append("        scale_factor: 100")
        lines.append("        spring_force: 0")
        lines.append("        damping_num: 0")
        lines.append("        damping_den: 1")
        lines.append("        force_offset: 0")
        lines.append("        friction: 2.5")
        lines.append("        breakout_force: 2")
        lines.append("        negative_stop: -1.0")
        lines.append("        positive_stop: 1.0")
        lines.append("        pos_pts: [%s]" % ", ".join(str(ch + i) for i in range(18)))
        lines.append("        force_pts: [%s]" % ", ".join(str(i / 2) for i in range(18)))
    return "\n".join(lines) + "\n"


def _state_text():
    """最小合法 presets.yaml（1 条状态，含俯仰 0 + 滚转 1）。"""
    return "presets:\n" + _state_block("state_1")


class TestParseRealFile(unittest.TestCase):
    """读真实 config/presets.yaml（只读）。"""

    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parent.parent / "config" / "presets.yaml"
        cls.presets = preset_store.parse_presets(
            cls.path.read_text(encoding="utf-8"))

    def test_seven_factory_presets(self):
        self.assertEqual(len(self.presets), 7)
        ids = [p["id"] for p in self.presets]
        self.assertEqual(ids, ["state_%d" % i for i in range(1, 8)])
        self.assertTrue(all(preset_store.is_builtin(p) for p in self.presets))

    def test_states_contain_pitch_and_roll_only(self):
        """预设只含俯仰(0)+滚转(1)。"""
        for p in self.presets:
            self.assertEqual(sorted(p["channels"]), [0, 1])

    def test_channel_data_structure(self):
        ch0 = self.presets[0]["channels"][0]
        self.assertEqual(set(preset_store.CHANNEL_DATA_KEYS) <= set(ch0), True)
        self.assertEqual(len(ch0["pos_pts"]), 18)
        self.assertEqual(len(ch0["force_pts"]), 18)
        self.assertIsInstance(ch0["breakout_force"], int)


class TestParseUserPreset(unittest.TestCase):
    def test_parse_user_preset(self):
        presets = preset_store.parse_presets(
            "presets:\n" + _state_block("user_1", builtin=False))
        self.assertEqual(presets[0]["id"], "user_1")
        self.assertFalse(preset_store.is_builtin(presets[0]))


class TestRenderRoundtrip(unittest.TestCase):
    def test_real_file_roundtrip(self):
        path = Path(__file__).resolve().parent.parent / "config" / "presets.yaml"
        presets = preset_store.parse_presets(path.read_text(encoding="utf-8"))
        text = preset_store.render_presets(presets)
        self.assertEqual(preset_store.parse_presets(text), presets)

    def test_no_yaml_anchors_on_shared_data(self):
        """多条预设引用同一数据对象时，渲染不得产生 YAML 锚点/别名。"""
        shared = {0: _ch_data(), 1: _ch_data()}
        presets = [{"id": "a", "channels": shared}, {"id": "b", "channels": shared}]
        text = preset_store.render_presets(presets)
        self.assertNotIn("&id", text)
        self.assertNotIn("*id", text)
        parsed = preset_store.parse_presets(text)
        self.assertEqual(len(parsed), 2)               # 深拷贝后两条数据各自完整


class TestParseErrors(unittest.TestCase):
    def _assert_bad(self, text):
        with self.assertRaises(preset_store.PresetFormatError):
            preset_store.parse_presets(text)

    def test_yaml_syntax_error(self):
        self._assert_bad("presets: [1")

    def test_presets_not_list(self):
        self._assert_bad("presets: 5\n")

    def test_duplicate_id(self):
        text = "presets:\n" + _state_block("s1") + _state_block("s1")
        self._assert_bad(text)

    def test_preset_with_channel_2_forbidden(self):
        """预设不能包含通道 2（脚蹬已删，只剩 0=俯仰 1=滚转）。"""
        block = _state_block("a").replace("      1:", "      2:")
        self._assert_bad("presets:\n" + block)

    def test_preset_missing_roll_channel(self):
        """预设必须同时含俯仰+滚转。"""
        block = ("  - id: a\n"
                 "    channels:\n"
                 "      0:\n"
                 "        scale_factor: 100\n"
                 "        spring_force: 0\n"
                 "        damping_num: 0\n"
                 "        damping_den: 1\n"
                 "        force_offset: 0\n"
                 "        friction: 2.5\n"
                 "        breakout_force: 2\n"
                 "        negative_stop: -1.0\n"
                 "        positive_stop: 1.0\n"
                 "        pos_pts: [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17]\n"
                 "        force_pts: [0.0,0.5,1.0,1.5,2.0,2.5,3.0,3.5,4.0,4.5,5.0,5.5,6.0,6.5,7.0,7.5,8.0,8.5]\n")
        self._assert_bad("presets:\n" + block)

    def test_empty_file_returns_empty_list(self):
        """空文件 / 无 presets 键 → 空列表（load_presets 层对空库告警）。"""
        self.assertEqual(preset_store.parse_presets(""), [])
        self.assertEqual(preset_store.parse_presets("其它键: 1\n"), [])


class TestValidateChannelData(unittest.TestCase):
    def test_valid_passthrough_normalized(self):
        out = preset_store.validate_channel_data(_ch_data(breakout_force="3"), "ctx")
        self.assertEqual(out["breakout_force"], 3)
        self.assertIsInstance(out["breakout_force"], int)
        self.assertEqual(out["friction"], 2.5)

    def test_missing_key_raises(self):
        bad = _ch_data()
        del bad["friction"]
        with self.assertRaises(preset_store.PresetFormatError):
            preset_store.validate_channel_data(bad, "ctx")

    def test_wrong_length_raises(self):
        bad = _ch_data(pos_pts=[0.0] * 17)
        with self.assertRaises(preset_store.PresetFormatError):
            preset_store.validate_channel_data(bad, "ctx")

    def test_non_numeric_raises(self):
        bad = _ch_data(friction="高")
        with self.assertRaises(preset_store.PresetFormatError):
            preset_store.validate_channel_data(bad, "ctx")

    def test_damping_den_zero_raises(self):
        """决策 6：damping_den 是阻尼分母，不可为 0。"""
        bad = _ch_data(damping_den=0)
        with self.assertRaises(preset_store.PresetFormatError):
            preset_store.validate_channel_data(bad, "ctx")


class TestFileIO(unittest.TestCase):
    """报错路径 + 原子写（决策 16：代码层不恢复，全部明确报错）。"""

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(preset_store.PresetFormatError):
                preset_store.load_presets(Path(tmp) / "presets.yaml")

    def test_corrupt_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "presets.yaml"
            p.write_text("a: [1", encoding="utf-8")
            with self.assertRaises(preset_store.PresetFormatError):
                preset_store.load_presets(p)

    def test_save_atomic_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "presets.yaml"
            presets = [{"id": "state_1", "label": "状态1", "category": "State",
                        "builtin": True, "channels": {0: _ch_data(), 1: _ch_data()}}]
            preset_store.save_presets(p, presets)
            self.assertFalse((Path(tmp) / "presets.yaml.tmp").exists())  # 原子写无残留
            new = [{"id": "user_1", "channels": {0: _ch_data(), 1: _ch_data()}}]
            preset_store.save_presets(p, new)
            saved_presets = preset_store.parse_presets(
                p.read_text(encoding="utf-8"))
            self.assertEqual([x["id"] for x in saved_presets], ["user_1"])


if __name__ == "__main__":
    unittest.main()
