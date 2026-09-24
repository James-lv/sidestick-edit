# -*- coding: utf-8 -*-
"""packets 单元测试：偏移表逐字段对齐 C++ struct、组包/解包、send 值组装与异常路径。

C++ 权威：CommunicationPackets.h 的 UDP_UI_Send_To_Controller_Parameter
（#pragma pack(push,1)，小端）与 UDP_UI_Recieve_Controller_Periodical（2×8B）。
"""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config_loader, packets


def _spec2():
    bundle = config_loader.load_all()
    return bundle, packets.build_packet_spec(bundle.protocol, "send")


def _spec1():
    bundle = config_loader.load_all()
    return bundle, packets.build_packet_spec(bundle.protocol, "recv")


def _sample_channel_data():
    # 完整通道数据：11 字段（friction/breakout_force/negative_stop/positive_stop
    # + 2×18点曲线 + scale_factor/spring_force/damping_num/damping_den + force_offset）
    return {
        "friction": 2.5,
        "breakout_force": 2,
        "negative_stop": -2010.8696,
        "positive_stop": 2010.8696,
        "pos_pts": [-0.5 * i for i in range(18)],
        "force_pts": [0.1 * i for i in range(18)],
        "scale_factor": 100,
        "spring_force": 0,
        "damping_num": 0,
        "damping_den": 1,
        "force_offset": 905,
    }


class TestPacketSpecLayout(unittest.TestCase):
    """字节布局 = 协议权威（与 C++ 逐字段一致，改动即测试失败）。"""

    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.spec = _spec2()

    def test_total_size_182(self):
        self.assertEqual(self.spec.size, 182)

    def test_generated_format_string(self):
        # ① 4个1B控制位(host_mode? + axis b + zero_calib? + control_mode b)
        # ② 2×float[18]曲线
        # ③ scale_factor h
        # ④ friction f + 4×int32(breakout/spring/damp_num/damp_den) +
        #    2×float(neg/pos_stop) + force_offset i
        self.assertEqual(
            self.spec.fmt,
            "<?b?b" + "f" * 36 + "hfiiiiffi")

    def test_field_offsets_match_cpp(self):
        expected = {
            # 字段: (偏移, 字节) —— 与 C++ #pragma pack(1) 逐项核对
            # 顺序：①控制位(4×1B) → ②曲线(2×72B) → ③比例(h) → ④工艺参数(7×4B)
            "host_mode": (0, 1),
            "axis": (1, 1),
            "zero_calib": (2, 1),
            "control_mode": (3, 1),
            "pos_pts": (4, 72),
            "force_pts": (76, 72),
            "scale_factor": (148, 2),
            "friction": (150, 4),
            "breakout_force": (154, 4),
            "spring_force": (158, 4),
            "damping_num": (162, 4),
            "damping_den": (166, 4),
            "negative_stop": (170, 4),
            "positive_stop": (174, 4),
            "force_offset": (178, 4),
        }
        by_name = self.spec.fields_by_name()
        self.assertEqual(set(by_name), set(expected))
        for name, (offset, size) in expected.items():
            self.assertEqual((by_name[name].offset, by_name[name].size), (offset, size),
                             "字段 %s 偏移/字节数与 C++ 不符" % name)

    def test_single_flat_struct(self):
        """整个 182B 就是一个结构体：无独立报文头，axis=1/2 选通道，两通道共用。"""
        self.assertEqual(self.spec.groups, ["UDP_UI_Send_To_Controller_Parameter"])


class TestRecvFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.spec = _spec1()

    def test_block_is_8_bytes(self):
        self.assertEqual(self.spec.size, 8)
        self.assertEqual(self.spec.fmt, "<ff")

    def test_parse_two_channels(self):
        payload = b"".join(
            packets.pack_packet(self.spec, {"Position": float(i), "LoadCellForce": -float(i) / 2})
            for i in range(2))
        frames = packets.parse_recv_frame(self.spec, payload, 2)
        self.assertEqual([f["Position"] for f in frames], [0.0, 1.0])
        self.assertEqual([f["LoadCellForce"] for f in frames], [0.0, -0.5])

    def test_bad_frame_size_raises(self):
        with self.assertRaises(packets.ProtocolError):
            packets.parse_recv_frame(self.spec, b"\x00" * 23, 2)


class TestPackUnpack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.spec = _spec2()

    def _sample_values(self):
        ch0 = self.bundle.channel_by_index(0)
        values = packets.build_send_values(
            _sample_channel_data(),
            ch0["axis"],
            flags={"zero_calib": True, "control_mode": 5})
        return values

    def test_roundtrip_all_fields(self):
        values = self._sample_values()
        decoded = packets.unpack_packet(self.spec, packets.pack_packet(self.spec, values))
        self.assertEqual(decoded["axis"], 1)
        self.assertEqual(decoded["scale_factor"], 100)
        self.assertAlmostEqual(decoded["friction"], 2.5, places=6)
        self.assertEqual(decoded["spring_force"], 0)
        self.assertEqual(decoded["damping_den"], 1)
        self.assertIs(decoded["zero_calib"], True)
        self.assertEqual(decoded["control_mode"], 5)
        self.assertEqual(len(decoded["force_pts"]), 18)
        self.assertAlmostEqual(decoded["force_pts"][17], 1.7, places=6)
        self.assertAlmostEqual(decoded["pos_pts"][3], -1.5, places=6)

    def test_little_endian_bytes_on_wire(self):
        values = self._sample_values()
        values["axis"] = 2
        values["scale_factor"] = 100
        packet = packets.pack_packet(self.spec, values)
        # 逐字节检查小端：offset 0 host_mode(默认 True=1)、offset 1 axis int8、
        # offset 3 control_mode int8、offset 148 scale_factor int16、offset 150 friction float32
        self.assertEqual(packet[0:1], struct.pack("<?", True))
        self.assertEqual(packet[1:2], struct.pack("<b", 2))
        self.assertEqual(packet[3:4], struct.pack("<b", 5))
        self.assertEqual(packet[148:150], struct.pack("<h", 100))
        self.assertEqual(packet[150:154], struct.pack("<f", 2.5))
        # force_offset @178（int32，值 905）
        self.assertEqual(packet[178:182], struct.pack("<i", 905))

    def test_missing_field_raises(self):
        values = self._sample_values()
        del values["breakout_force"]
        with self.assertRaises(packets.ProtocolError):
            packets.pack_packet(self.spec, values)

    def test_wrong_array_length_raises(self):
        values = self._sample_values()
        values["pos_pts"] = [0.0] * 17
        with self.assertRaises(packets.ProtocolError):
            packets.pack_packet(self.spec, values)

    def test_unpack_bad_size_raises(self):
        with self.assertRaises(packets.ProtocolError):
            packets.unpack_packet(self.spec, b"\x00" * 185)


class TestBuildSendValues(unittest.TestCase):
    """build_send_values：完整通道数据（报文原值）+ 通道标识 + 标志位。
    不再有协议层默认值兜底——缺字段会直接 KeyError。"""

    @classmethod
    def setUpClass(cls):
        cls.bundle = config_loader.load_all()
        cls.spec = packets.build_packet_spec(cls.bundle.protocol, "send")

    def test_fixed_fields_in_channel_data(self):
        # 4 固定字段现必须随预设通道数据提供
        data = _sample_channel_data()
        self.assertNotEqual(data["damping_den"], 0)     # 阻尼分母不可为 0
        self.assertEqual(data["scale_factor"], 100)
        self.assertEqual(data["spring_force"], 0)
        self.assertEqual(data["damping_num"], 0)

    def test_build_full_packet_182(self):
        ch0 = self.bundle.channel_by_index(0)
        values = packets.build_send_values(
            _sample_channel_data(),
            ch0["axis"],
            flags={"zero_calib": False, "control_mode": 1})
        packet = packets.pack_packet(self.spec, values)     # 缺字段会在此抛错
        self.assertEqual(len(packet), 182)
        self.assertEqual(values["axis"], 1)
        self.assertEqual(values["force_offset"], 905)
        self.assertEqual(values["control_mode"], 1)         # 运行时标志位透传

    def test_channel_data_keys_are_packet_fields(self):
        # 决策 18：通道数据的键 = send 报文字段名（无换算），多一个少一个都组不齐包
        spec_names = set(self.spec.fields_by_name())
        self.assertTrue(set(_sample_channel_data()) <= spec_names)


class TestSpecErrors(unittest.TestCase):
    """协议定义非法时的报错路径（用假 protocol dict 构造）。"""

    def test_unknown_packet_key(self):
        with self.assertRaises(packets.ProtocolError):
            packets.build_packet_spec({"packets": {}}, "NOPE")

    def test_missing_layout_raises(self):
        with self.assertRaises(packets.ProtocolError):
            packets.build_packet_spec({"packets": {"X": {}}}, "X")

    def test_undefined_group_reference(self):
        proto = {"structs": {"param": {}},
                 "packets": {"X": {"layout": ["Ghost"]}}}
        with self.assertRaises(packets.ProtocolError):
            packets.build_packet_spec(proto, "X")

    def test_duplicate_group_name(self):
        with self.assertRaises(packets.ProtocolError):
            packets._flatten_groups({"param": {"A": {}}, "comm": {"A": {}}})

    def test_unknown_field_type(self):
        proto = {"structs": {"param": {"A": {"fields": [{"name": "f", "type": "double"}]}}},
                 "packets": {"X": {"layout": ["A"]}}}
        with self.assertRaises(packets.ProtocolError):
            packets.build_packet_spec(proto, "X")


if __name__ == "__main__":
    unittest.main()
