# -*- coding: utf-8 -*-
"""backend 单元/集成测试：双状态脏标记、无条件发送、校零两帧脉冲、预设 CRUD、UDP 环回。

需要 PyQt5（QObject/信号/QUdpSocket）；UDP 环回用 127.0.0.1 临时端口，不碰真实网络。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QCoreApplication, QEventLoop, QTimer
from PyQt5.QtNetwork import QHostAddress, QUdpSocket

from core import config_loader, packets, preset_store
from core.backend import BackendService

_APP = QCoreApplication.instance() or QCoreApplication([])
_CFG = Path(__file__).resolve().parent.parent / "config"


def _wait(ms):
    """跑事件循环 ms 毫秒（让 QTimer / 队列信号得以处理）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec_()


class _Capture:
    """信号捕获器：把 (args...) 追加到 records。"""

    def __init__(self, signal):
        self.records = []
        signal.connect(self._on)

    def _on(self, *args):
        self.records.append(args)


class BackendTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bcls_backend_"))
        self.presets_path = self.tmp / "presets.yaml"
        shutil.copyfile(_CFG / "presets.yaml", self.presets_path)
        self.bundle = config_loader.load_all()
        self.errors = []

    def tearDown(self):
        if hasattr(self, "be"):
            self.be.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_backend(self, udp_enabled=False):
        be = BackendService(self.bundle, self.presets_path, udp_enabled=udp_enabled)
        err = _Capture(be.error_occurred)
        ack = _Capture(be.params_ack)
        logs = _Capture(be.log_message)
        be.errors = self.errors
        self.be = be
        self.err = err
        self.ack = ack
        self.logs = logs
        return be


class TestStartupBaseline(BackendTestBase):
    def test_baseline_is_state1_all_clean(self):
        be = self._make_backend()
        state1 = next(p for p in be.get_presets() if p["id"] == "state_1")
        self.assertEqual(be.get_editing(0), state1["channels"][0])
        self.assertEqual(be.get_editing(1), state1["channels"][1])
        self.assertFalse(be._is_dirty(0))
        self.assertFalse(be._is_dirty(1))
        self.assertEqual(sorted(be._editing), [0, 1])   # 只剩俯仰/滚转两通道
        self.assertEqual(len(be.get_presets()), 7)


class TestDirtyAndSend(BackendTestBase):
    def test_edit_makes_dirty_send_clears_and_detects_no_change(self):
        be = self._make_backend()
        dirty_seen = _Capture(be.state_changed)
        pts_seen = _Capture(be.points_changed)

        be.set_packet_field(0, "friction", 9.9)
        self.assertAlmostEqual(be.get_editing(0)["friction"], 9.9)
        self.assertTrue(be._is_dirty(0))
        self.assertEqual(dirty_seen.records[-1], (0, "friction", 9.9, True))

        # 直接发送（无门控）：ack True，已提交变黑（sent 更新）
        be.send_parameters(0)
        self.assertFalse(be._is_dirty(0))
        self.assertEqual(be._sent[0]["friction"], 9.9)
        self.assertEqual(len(be._tx_log), 1)
        self.assertEqual(self.ack.records[-1], (0, True))
        self.assertEqual(pts_seen.records[-1][:2], (0, be._sent[0]["pos_pts"]))
        self.assertFalse(pts_seen.records[-1][3])       # 提交后全黑

        # 无变化检测：再次下载同一参数，仍会重新下发
        n = len(be._tx_log)
        be.send_parameters(0)
        self.assertEqual(len(be._tx_log), n + 1)

    def test_table_cell_edit(self):
        be = self._make_backend()
        be.set_packet_field(1, "pos_pts[3]", -7.5)
        self.assertAlmostEqual(be.get_editing(1)["pos_pts"][3], -7.5)
        be.set_packet_field(1, "pos_pts", [1.0] * 18)
        self.assertEqual(be.get_editing(1)["pos_pts"], [1.0] * 18)
        be.set_packet_field(1, "pos_pts[99]", 0.0)     # 越界 → error，不改数据
        self.assertEqual(be.get_editing(1)["pos_pts"], [1.0] * 18)

    def test_zero_pulse_two_frames(self):
        be = self._make_backend()
        be.set_packet_field(0, "friction", 3.3)
        be.send_parameters(0)
        n = len(be._tx_log)
        be.zero(0)
        self.assertEqual(len(be._tx_log), n + 1)       # 置位帧立即缓存
        spec = packets.build_packet_spec(self.bundle.protocol, "send")

        def zero_of(packet):
            return packets.unpack_packet(spec, packet)["zero_calib"]

        self.assertTrue(zero_of(be._tx_log[-1]))
        _wait(250)                                       # 等清除帧定时器
        self.assertEqual(len(be._tx_log), n + 2)       # 清除帧已入队
        self.assertFalse(zero_of(be._tx_log[-1]))

    def test_control_mode_send_and_report(self):
        be = self._make_backend()
        seen = _Capture(be.control_mode_changed)
        be.set_control_mode(0, 2)      # 通道 0 设为脉冲
        self.assertEqual(be._flags[0]["control_mode"], 2)
        self.assertEqual(seen.records[-1], (0, 2, False))
        self.assertEqual(len(be._tx_log), 1)           # 切换即发(无门控)
        be.set_control_mode(1, 4)      # 通道 1 设为扫频
        self.assertEqual(be._flags[1]["control_mode"], 4)


class TestPresets(BackendTestBase):
    def test_load_preset_makes_dirty(self):
        be = self._make_backend()
        pts = _Capture(be.points_changed)
        # 内存注入：让 state_2 与基线 state_1 不同（不依赖 presets.yaml 占位数据全相同）
        for p in be.get_presets():
            if p["id"] == "state_2":
                p["channels"][0]["friction"] = 1.234
                p["channels"][0]["breakout_force"] = 99
        be.load_preset(0, "state_2")
        self.assertEqual(be._editing_preset_id, "state_2")
        self.assertAlmostEqual(be.get_editing(0)["friction"], 1.234, places=6)
        self.assertTrue(pts.records[-1][3])             # 与已下发态有差异 → 脏
        # 通道 2 已删除 → 报错，不崩溃
        be.load_preset(2, "state_2")
        self.assertTrue(any("不含通道" in m for _, m in self.err.records))

    def test_download_preset_sends_two_channels(self):
        be = self._make_backend()
        # 整体下载 state_2：俯仰+滚转都下发 → 2 条
        n = len(be._tx_log)
        be.download_preset("state_2")
        self.assertEqual(len(be._tx_log) - n, 2)
        self.assertFalse(be._is_dirty(0))
        self.assertFalse(be._is_dirty(1))
        # 再次下载同一预设：无变化检测，两通道全部重新下发 → 仍为 2 条
        n = len(be._tx_log)
        be.download_preset("state_2")
        self.assertEqual(len(be._tx_log) - n, 2)
        self.assertFalse(be._is_dirty(0))
        self.assertFalse(be._is_dirty(1))

    def test_create_and_delete_user_preset(self):
        be = self._make_backend()
        n = len(be.get_presets())
        new_id = be.create_preset()
        self.assertTrue(new_id.startswith("user_"))
        self.assertEqual(len(be.get_presets()), n + 1)
        new = next(p for p in be.get_presets() if p["id"] == new_id)
        self.assertEqual(new["category"], "User")
        self.assertFalse(preset_store.is_builtin(new))
        # 新建默认模板 = 模式6 综合力感（决策 22）
        s6 = next(p for p in be.get_presets() if p["id"] == "state_6")
        self.assertEqual(new["channels"], s6["channels"])
        # 出厂拒绝删除
        self.assertFalse(be.delete_preset("state_1"))
        self.assertTrue(any("不可删除" in msg for _, msg in self.err.records))
        # 用户预设可删
        self.assertTrue(be.delete_preset(new_id))
        self.assertEqual(len(be.get_presets()), n)

    def test_update_builtin_refused_user_ok(self):
        be = self._make_backend()
        be.update_preset("state_1", {"label": "X"})
        self.assertEqual(next(p for p in be.get_presets()
                              if p["id"] == "state_1")["label"], "模式1 摩擦力")
        new_id = be.create_preset()
        be.update_preset(new_id, {"label": "我的预设"})
        self.assertEqual(next(p for p in be.get_presets()
                              if p["id"] == new_id)["label"], "我的预设")

    def test_writeback_only_for_user_preset(self):
        be = self._make_backend()
        # 出厂：下载后不回写文件
        be.load_preset(0, "state_2")
        be.set_packet_field(0, "friction", 8.8)
        be.send_parameters(0)
        on_disk = preset_store.load_presets(self.presets_path)
        s2 = next(p for p in on_disk if p["id"] == "state_2")
        self.assertNotAlmostEqual(s2["channels"][0]["friction"], 8.8)
        # 用户：下载后回写
        new_id = be.create_preset()
        be.load_preset(0, new_id)
        be.set_packet_field(0, "friction", 8.8)
        be.send_parameters(0)
        on_disk = preset_store.load_presets(self.presets_path)
        u = next(p for p in on_disk if p["id"] == new_id)
        self.assertAlmostEqual(u["channels"][0]["friction"], 8.8)


class TestUdpLoopback(unittest.TestCase):
    """UDP 环回集成：单 socket 绑定 + 收帧 + 看门狗上线 + 下发 182B。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bcls_udp_"))
        self.presets_path = self.tmp / "presets.yaml"
        shutil.copyfile(_CFG / "presets.yaml", self.presets_path)
        self.bundle = config_loader.load_all()
        net = self.bundle.protocol["network"]
        net["local_ip"] = "127.0.0.1"
        net["local_port"] = 19200
        net["target_ip"] = "127.0.0.1"
        net["target_port"] = 19230
        self.helper = QUdpSocket()
        self.assertTrue(self.helper.bind(QHostAddress("127.0.0.1"), 19230))
        self.rx = []
        self.helper.readyRead.connect(self._drain)
        self.be = BackendService(self.bundle, self.presets_path, udp_enabled=True)
        self.telemetry = _Capture(self.be.telemetry_received)
        self.link = _Capture(self.be.link_state_changed)
        self.be.start()

    def tearDown(self):
        self.be.stop()
        self.helper.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _drain(self):
        while self.helper.hasPendingDatagrams():
            size = self.helper.pendingDatagramSize()
            data, _, _ = self.helper.readDatagram(size)
            self.rx.append(bytes(data))

    def _pump(self, ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def test_loopback_link_telemetry_and_send(self):
        # 1) 模拟控制器发周期帧 → 看门狗上线 + 遥测解析
        recv_spec = packets.build_packet_spec(self.bundle.protocol, "recv")
        frame = b"".join(
            packets.pack_packet(recv_spec, {"Position": 1.5, "LoadCellForce": -2.0})
            for _ in range(2))
        self.helper.writeDatagram(frame, QHostAddress("127.0.0.1"), 19200)
        self._pump(800)
        self.assertTrue(self.be._connected)
        # telemetry_received 合同：单字典 {ch: {Position, LoadCellForce}}（后端信号为 pyqtSignal(dict)）
        self.assertEqual(self.telemetry.records[-1][0][0]["Position"], 1.5)
        self.assertEqual(self.telemetry.records[-1][0][1]["LoadCellForce"], -2.0)

        # 2) 改参数 → 内层下载 → helper 收到 182B，axis=1、zero_calib=False
        self.be.set_packet_field(0, "friction", 5.5)
        self.be.send_parameters(0)
        self._pump(800)
        self.assertEqual(len(self.rx), 1)
        self.assertEqual(len(self.rx[0]), 182)
        spec = packets.build_packet_spec(self.bundle.protocol, "send")
        decoded = packets.unpack_packet(spec, self.rx[0])
        self.assertEqual(decoded["axis"], 1)
        self.assertAlmostEqual(decoded["friction"], 5.5, places=6)
        self.assertFalse(decoded["zero_calib"])

        # 3) 滚转下载 → axis=2（先制造变更，否则后端按"无变化跳过"不发，rx 仍停在 ch0）
        self.be.set_packet_field(1, "friction", 7.7)
        self.be.send_parameters(1)
        self._pump(800)
        self.assertEqual(len(self.rx), 2)   # 累计：ch0(改friction) + ch1(改friction)
        decoded = packets.unpack_packet(spec, self.rx[-1])
        self.assertEqual(decoded["axis"], 2)


class TestHostMode(BackendTestBase):
    def test_control_mode_sets_int_mode(self):
        """控制模式设 0..6 整型值，UI 收到 control_mode_changed 信号。"""
        be = self._make_backend()
        seen = _Capture(be.control_mode_changed)
        be.set_control_mode(0, 3)       # 通道 0 设为倍脉冲
        self.assertEqual(be._flags[0]["control_mode"], 3)
        self.assertEqual(seen.records[-1], (0, 3, False))
        self.assertEqual(len(be._tx_log), 1)   # 切换即发(无门控)

    def test_non_host_disables_control_mode(self):
        be = self._make_backend()
        be.set_host_mode(False)
        self.assertFalse(be._host)
        n = len(be._tx_log)
        be.set_control_mode(0, 1)
        be.set_control_mode(1, 2)
        # 非主机：控制模式直接返回，不发送、不改状态
        self.assertEqual(len(be._tx_log), n)
        self.assertEqual(be._flags[0]["control_mode"], 0)
        self.assertEqual(be._flags[1]["control_mode"], 0)
        # 参数下发不受主机模式影响
        be.set_packet_field(0, "friction", 9.9)
        be.send_parameters(0)
        self.assertEqual(len(be._tx_log), n + 1)

    def test_invalid_mode_rejected(self):
        be = self._make_backend()
        n = len(be._tx_log)
        be.set_control_mode(0, 7)
        self.assertEqual(len(be._tx_log), n)
        self.assertEqual(be._flags[0]["control_mode"], 0)

    def test_host_flag_in_packet(self):
        be = self._make_backend()
        spec = packets.build_packet_spec(self.bundle.protocol, "send")
        be.set_host_mode(False)
        be.set_packet_field(0, "friction", 5.5)
        be.send_parameters(0)
        self.assertFalse(packets.unpack_packet(spec, be._tx_log[-1])["host_mode"])
        be.set_host_mode(True)
        be.set_packet_field(0, "friction", 6.6)
        be.send_parameters(0)
        self.assertTrue(packets.unpack_packet(spec, be._tx_log[-1])["host_mode"])


class TestApplyNetwork(unittest.TestCase):
    """菜单「设置→网络绑定…」（决策 25）：运行时重建 socket + 原子写回（tmp 隔离）。"""

    PORT_LOCAL = 19300
    PORT_TARGET_OLD = 19330
    PORT_TARGET_NEW = 19430

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bcls_net_"))
        shutil.copyfile(_CFG / "presets.yaml", self.tmp / "presets.yaml")
        shutil.copyfile(_CFG / "protocol.yaml", self.tmp / "protocol.yaml")
        self.bundle = config_loader.load_all(config_dir=self.tmp)
        net = self.bundle.protocol["network"]
        net.update(local_ip="127.0.0.1", local_port=self.PORT_LOCAL,
                   target_ip="127.0.0.1", target_port=self.PORT_TARGET_OLD)
        self.be = BackendService(self.bundle, self.tmp / "presets.yaml",
                                 udp_enabled=True)
        self.errors = []
        self.be.error_occurred.connect(lambda src, msg: self.errors.append(msg))
        self.be.start()
        # 模拟控制器：同时听新旧 target 两个端口
        self.rx_old, self.rx_new = [], []
        self.old = QUdpSocket()
        self.old.bind(QHostAddress("127.0.0.1"), self.PORT_TARGET_OLD)
        self.old.readyRead.connect(lambda: self._drain(self.old, self.rx_old))
        self.new = QUdpSocket()
        self.new.bind(QHostAddress("127.0.0.1"), self.PORT_TARGET_NEW)
        self.new.readyRead.connect(lambda: self._drain(self.new, self.rx_new))

    def tearDown(self):
        self.be.stop()
        self.old.close()
        self.new.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _drain(self, sock, box):
        while sock.hasPendingDatagrams():
            size = sock.pendingDatagramSize()
            data, _, _ = sock.readDatagram(size)
            box.append(bytes(data))

    def _pump(self, ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def _send_frame_to(self, port):
        spec = packets.build_packet_spec(self.bundle.protocol, "recv")
        frame = b"".join(
            packets.pack_packet(spec, {"Position": 1.0, "LoadCellForce": -2.0})
            for _ in range(2))
        self.old.writeDatagram(frame, QHostAddress("127.0.0.1"), port)

    def test_target_change_reconfigures_and_persists(self):
        # 1) 旧地址链路先上线
        self._send_frame_to(self.PORT_LOCAL)
        self._pump(600)
        self.assertTrue(self.be._connected)

        # 2) 仅改控制器 target（local 不变 → 不试绑）→ 立即生效
        ok, msg = self.be.apply_network({
            "local_ip": "127.0.0.1", "local_port": self.PORT_LOCAL,
            "target_ip": "127.0.0.1", "target_port": self.PORT_TARGET_NEW})
        self.assertTrue(ok, msg)
        self.assertEqual(msg, "已生效")
        self.assertEqual(self.errors, [])

        # 3) 内存 bundle 与磁盘 protocol.yaml 均已更新
        net = self.bundle.protocol["network"]
        self.assertEqual(net["target_port"], self.PORT_TARGET_NEW)
        reloaded = config_loader.load_all(config_dir=self.tmp)
        self.assertEqual(reloaded.protocol["network"]["target_port"],
                         self.PORT_TARGET_NEW)

        # 4) 新 socket 重新上线 → 参数包发到新 target；旧 target 收不到
        self._send_frame_to(self.PORT_LOCAL)
        self._pump(600)
        self.assertTrue(self.be._connected)
        self.be.set_packet_field(0, "friction", 5.5)
        self.be.send_parameters(0)
        self._pump(500)
        self.assertTrue(any(len(p) == 182 for p in self.rx_new),
                        "新 target 未收到 182B 参数包")
        self.assertEqual(self.rx_old, [], "旧 target 不应再收到参数包")

    def test_occupied_local_port_rejected(self):
        blocker = QUdpSocket()
        self.assertTrue(blocker.bind(QHostAddress("127.0.0.1"),
                                     self.PORT_LOCAL + 1))
        disk_before = (self.tmp / "protocol.yaml").read_text(encoding="utf-8")
        ok, msg = self.be.apply_network({
            "local_ip": "127.0.0.1", "local_port": self.PORT_LOCAL + 1,
            "target_ip": "127.0.0.1", "target_port": self.PORT_TARGET_OLD})
        blocker.close()
        self.assertFalse(ok)
        self.assertIn("绑定失败", msg)
        # 未做任何改动：内存与磁盘都与 apply 前一致
        self.assertEqual(self.bundle.protocol["network"]["target_port"],
                         self.PORT_TARGET_OLD)
        self.assertEqual((self.tmp / "protocol.yaml").read_text(encoding="utf-8"),
                         disk_before)


if __name__ == "__main__":
    unittest.main()
