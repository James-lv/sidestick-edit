# -*- coding: utf-8 -*-
"""config_loader 单元测试：加载 / 命令行覆盖 / 校验 / YAML 缺失报错（不做自恢复）。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config_loader

# 最小合法 protocol（供临时目录测试用）
_MIN_PROTOCOL = """\
network:
  target_ip: "1.1.1.1"
  target_port: 1
  local_ip: "0.0.0.0"
  local_port: 2
channel_ids:
  - {index: 0, name: a, axis: 1}
"""


def _write_min_protocol(tmp, text=_MIN_PROTOCOL):
    Path(tmp) / "protocol.yaml"
    (Path(tmp) / "protocol.yaml").write_text(text, encoding="utf-8")


class TestLoadRealConfig(unittest.TestCase):
    """读真实 config/protocol.yaml（只读）。"""

    @classmethod
    def setUpClass(cls):
        cls.bundle = config_loader.load_all()

    def test_two_channels_with_unique_axis(self):
        chans = self.bundle.channels()
        self.assertEqual(len(chans), 2)
        self.assertEqual([ch["axis"] for ch in chans], [1, 2])
        self.assertEqual(self.bundle.channel_by_index(0)["name"], "俯仰")
        self.assertEqual(self.bundle.channel_by_index(1)["name"], "滚转")

    def test_ports_coerced_to_int(self):
        net = self.bundle.protocol["network"]
        self.assertIsInstance(net["local_port"], int)
        self.assertIsInstance(net["target_port"], int)
        self.assertEqual((net["local_port"], net["target_port"]), (9200, 9300))

    def test_no_send_defaults_section(self):
        """决策：协议层不再有 send_defaults 段（固定字段随预设下发）。"""
        self.assertNotIn("send_defaults", self.bundle.protocol)


class TestCliOverrides(unittest.TestCase):
    def test_apply_and_log(self):
        bundle = config_loader.load_all()
        args = config_loader.build_arg_parser().parse_args(
            ["--target-ip", "9.9.9.9", "--local-port", "12345"])
        applied = config_loader.apply_cli_overrides(bundle, args)
        net = bundle.protocol["network"]
        self.assertEqual(net["target_ip"], "9.9.9.9")
        self.assertEqual(net["local_port"], 12345)
        self.assertEqual(len(applied), 2)

    def test_no_args_no_change(self):
        bundle = config_loader.load_all()
        args = config_loader.build_arg_parser().parse_args([])
        applied = config_loader.apply_cli_overrides(bundle, args)
        self.assertEqual(applied, [])
        self.assertEqual(bundle.protocol["network"]["local_port"], 9200)


class TestYamlNotSelfRecovered(unittest.TestCase):
    """决策 12/16：代码层不做恢复，配置缺失/损坏 → 明确报错（打包层负责恢复）。"""

    def test_missing_protocol_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config_loader.ConfigError):
                config_loader.load_all(config_dir=Path(tmp))

    def test_corrupt_protocol_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_min_protocol(tmp, text="a: [1")
            with self.assertRaises(config_loader.ConfigError):
                config_loader.load_all(config_dir=Path(tmp))

    def test_missing_channel_ids_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_min_protocol(tmp, text="network: {target_port: 1, local_port: 2}\n")
            with self.assertRaises(config_loader.ConfigError):
                config_loader.load_all(config_dir=Path(tmp))

    def test_duplicate_axis_raises(self):
        bad = _MIN_PROTOCOL.replace(
            "  - {index: 0, name: a, axis: 1}",
            "  - {index: 0, name: a, axis: 1}\n"
            "  - {index: 1, name: b, axis: 1}")
        with tempfile.TemporaryDirectory() as tmp:
            _write_min_protocol(tmp, text=bad)
            with self.assertRaises(config_loader.ConfigError):
                config_loader.load_all(config_dir=Path(tmp))

    def test_missing_network_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_min_protocol(tmp, text="structs: {}\n")
            with self.assertRaises(config_loader.ConfigError):
                config_loader.load_all(config_dir=Path(tmp))


# 带注释的 network 段（模拟真实 protocol.yaml 排版：值从第 17 列起）
_NET_TXT = """\
# 本机单 socket（绑定 local_port）收发共用；target_* 为控制器端
network:
  target_ip:   "1.1.1.1"    # 控制器 IP
  target_port: 1            # 控制器收包端口
  local_ip:    "0.0.0.0"    # 本机绑定 IP（0.0.0.0 = 任一网卡）
  local_port:  2            # 本机端口（收发共用）
"""


class TestNetworkPersist(unittest.TestCase):
    """菜单「设置→网络绑定…」持久化：行级替换保留注释/引号/对齐。"""

    def test_update_keeps_comments_quotes_and_alignment(self):
        new = config_loader.update_network_yaml(
            _NET_TXT, {"target_ip": "2.2.2.2", "local_port": 99})
        # 注释全部保留
        for comment in ("# 控制器 IP", "# 控制器收包端口",
                        "# 本机绑定 IP（0.0.0.0 = 任一网卡）", "# 本机端口（收发共用）"):
            self.assertIn(comment, new)
        # IP 保持引号风格；端口不带引号
        self.assertIn('"2.2.2.2"', new)
        self.assertRegex(new, r"local_port:\s+99\s+#")
        # 值从第 17 列起（对齐文件原有风格）
        ip_line = next(ln for ln in new.splitlines() if ln.startswith("  target_ip:"))
        self.assertEqual(ip_line.index('"'), 16)
        # 未给的键保持原样（端口不带引号；两空格缩进风格）
        self.assertRegex(new, r"target_port:\s+1\s+#")
        self.assertIn('"0.0.0.0"', new)

    def test_update_written_file_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "protocol.yaml"
            p.write_text(_NET_TXT + "channel_ids:\n"
                         "  - {index: 0, name: a, axis: 1}\n"
                         "  - {index: 1, name: b, axis: 2}\n",
                         encoding="utf-8")
            config_loader.persist_network_file(
                p, {"target_ip": "3.3.3.3", "target_port": 4,
                    "local_ip": "5.5.5.5", "local_port": 6})
            # 无 .tmp 残留
            self.assertFalse(p.with_name(p.name + ".tmp").exists())
            # 重新加载校验通过且值正确
            bundle = config_loader.load_all(config_dir=Path(tmp))
            net = bundle.protocol["network"]
            self.assertEqual(net["target_ip"], "3.3.3.3")
            self.assertEqual((net["target_port"], net["local_port"]), (4, 6))

    def test_no_network_keys_raises(self):
        with self.assertRaises(config_loader.ConfigError):
            config_loader.update_network_yaml("structs: {}\n",
                                              {"target_ip": "x"})

    def test_persist_invalid_port_does_not_touch_disk(self):
        """替换结果若校验失败（端口非整数）→ ConfigError 且原文件不动。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "protocol.yaml"
            p.write_text(_NET_TXT + "channel_ids:\n"
                         "  - {index: 0, name: a, axis: 1}\n",
                         encoding="utf-8")
            original = p.read_text(encoding="utf-8")
            with self.assertRaises(config_loader.ConfigError):
                config_loader.persist_network_file(p, {"target_port": "abc"})
            self.assertEqual(p.read_text(encoding="utf-8"), original)
            self.assertFalse(p.with_name(p.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
