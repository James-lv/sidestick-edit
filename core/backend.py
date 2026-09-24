# -*- coding: utf-8 -*-
"""backend —— BackendService(QObject)，唯一后端边界（ARCHITECTURE §5）。

状态模型（决策 10/17/18）：
    每通道两份数据：editing_data（界面显示）/ sent_data（已下发，组包只从它取数）。
    dirty = 两者不等 → 回灌 state_changed / points_changed 驱动 UI 蓝字。
    启动基线 = 模式1 通道数据（俯仰/滚转两通道），全黑。

交互规则：
    - 内层「下载」send_parameters(ch)：提交 + 直接发 182B（无条件，无差异也发）；
      编辑中的是用户新建预设 → 该通道数据回写 presets.yaml（出厂不回写）。
    - 外层「下载」download_preset(id)：加载全部通道 + 发送，不写文件（决策 17）。
    - 校零 zero(ch)：置位→发→延时清 两帧脉冲（决策 5.3-2）。
    - 发送：无条件直接 sendto（UDP 无连接，对端不在顶多丢包，绝不阻塞/缓存）。
    - 控制模式 set_control_mode(ch, mode)：0=OFF..6=阶跃，随参数包下发。

UI 不持有业务状态、不碰 socket/struct/文件 IO。
"""

import copy
from collections import deque
import re
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from core import packets, preset_store
from core.config_loader import NETWORK_KEYS, persist_network_file
from network.udp_manager import UdpManager

#: 内层可编辑的 4 个报文参数（决策 18）
PARAM_FIELDS = (
    "scale_factor",
    "spring_force",
    "damping_num",
    "damping_den",
    "friction",
    "negative_stop",
    "breakout_force",
    "positive_stop",
    "force_offset",
)
#: 18 点表数组字段（侧杆力感曲线，下发给侧杆）
ARRAY_FIELDS = ("pos_pts", "force_pts")
#: 表格单元格字段名：pos_pts[5] / force_pts[17]
_CELL_FIELD_RE = re.compile(r"^(pos_pts|force_pts)\[(\d+)\]$")

#: 校零脉冲清除帧延时（ms）
ZERO_PULSE_CLEAR_DELAY_MS = 100
#: 启动基线预设（编辑页初始显示，全黑）
STARTUP_PRESET_ID = "state_1"
#: 新建预设复制源：模式6 综合力感模式（摩擦/启动力/非线性梯度/硬限制组合，决策 22）
NEW_PRESET_SOURCE_ID = "state_6"
#: 用户新建预设分组
USER_CATEGORY = "User"


class BackendService(QObject):
    telemetry_received = pyqtSignal(dict)                       # {通道: {Position, LoadCellForce}}
    link_state_changed = pyqtSignal(bool, str)
    host_mode_changed = pyqtSignal(bool)                # 作为主机状态变化时通知 UI
    params_ack = pyqtSignal(int, bool)
    state_changed = pyqtSignal(int, str, object, bool)          # (通道, 字段, 值, dirty)
    points_changed = pyqtSignal(int, list, list, bool)          # (通道, position18, force18, dirty)
    control_mode_changed = pyqtSignal(int, int, bool)           # (通道, mode, dirty)
    preset_list_changed = pyqtSignal()
    log_message = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str, str)

    def __init__(self, bundle, presets_path, udp_enabled=True, parent=None):
        super().__init__(parent)
        self._bundle = bundle
        self._presets_path = Path(presets_path)
        self._presets = preset_store.load_presets(self._presets_path)
        self._channel_indexes = [ch["index"] for ch in self.channels()]

        self._send_spec = packets.build_packet_spec(bundle.protocol, "send")
        self._recv_spec = packets.build_packet_spec(bundle.protocol, "recv")

        # 双状态（决策 10/18）：启动基线 = 模式1 通道数据（俯仰/滚转），全黑
        baseline = self._find_preset(STARTUP_PRESET_ID)
        if baseline is None:
            raise RuntimeError("presets.yaml 缺少启动基线预设: %s" % STARTUP_PRESET_ID)
        self._editing = {}
        self._sent = {}
        for ch in self._channel_indexes:
            self._editing[ch] = copy.deepcopy(baseline["channels"][ch])
            self._sent[ch] = copy.deepcopy(self._editing[ch])
        self._editing_preset_id = STARTUP_PRESET_ID
        self._flags = {ch: {"control_mode": 0}
                       for ch in self._channel_indexes}
        self._connected = False
        self._host = False                      # 默认不作为主机
        self._tx_log = deque(maxlen=256)         # 已下发包记录（观测/测试用，环形保留）
        self._zero_timers = {ch: QTimer(self) for ch in self._channel_indexes}
        for t in self._zero_timers.values():
            t.setSingleShot(True)

        self._udp = None
        if udp_enabled:
            net = bundle.protocol["network"]
            self._udp = UdpManager(net["local_ip"], net["local_port"],
                                   net["target_ip"], net["target_port"])
            self._udp.frame_received.connect(self._on_frame)
            self._udp.link_changed.connect(self._on_link)
            self._udp.socket_error.connect(lambda msg: self._error("UDP", msg))
        self._log("后端就绪：%d 条预设（启动基线 %s）"
                  % (len(self._presets), STARTUP_PRESET_ID))

    # ------------------------------------------------------------
    # 生命周期 / 只读访问（UI 启动渲染用）
    # ------------------------------------------------------------
    def start(self):
        if self._udp is not None:
            self._udp.start()
            self._log("UDP 已启动（单 socket 收发共用，决策 14）")
        else:
            self._log("UDP 未启用（--no-udp 调试模式）")

    def stop(self):
        for t in self._zero_timers.values():
            t.stop()
        if self._udp is not None:
            self._udp.stop()

    def is_connected(self):
        """链路是否已建立（供 UI 按钮状态显示用）。"""
        return self._connected

    # ------------------------------------------------------------
    # 网络设置（菜单「设置→网络绑定…」，决策 25）
    # ------------------------------------------------------------
    def get_network(self) -> dict:
        """当前生效网络 4 值（设置对话框预填用）。"""
        net = self._bundle.protocol["network"]
        return {k: net[k] for k in NETWORK_KEYS}

    def apply_network(self, values: dict) -> "tuple":
        """应用新网络 4 值：试绑(local 变更时) → 重建 socket → 写回 protocol.yaml。

        返回 (ok: bool, msg: str)。ok=False 未做任何改动；ok=True 但 msg 含
        “写回失败”提示时，运行态已生效、磁盘未持久化（重启恢复旧值）。
        """
        if self._udp is None:
            return False, "UDP 未启用（--no-udp 调试模式），无法绑定"
        net = self._bundle.protocol["network"]
        local_ip = str(values["local_ip"]).strip()
        target_ip = str(values["target_ip"]).strip()
        try:
            local_port = int(values["local_port"])
            target_port = int(values["target_port"])
        except (TypeError, ValueError):
            return False, "端口必须是整数"
        # 仅当本机绑定地址变更才试绑（未变更时当前 socket 正占着该端口，probe 必假失败）
        if (local_ip, local_port) != (str(net["local_ip"]), int(net["local_port"])):
            err = UdpManager.probe_bind(local_ip, local_port)
            if err:
                return False, err
        try:
            self._udp.reconfig(local_ip, local_port, target_ip, target_port)
        except Exception as exc:
            return False, "重建 socket 失败：%s" % exc
        # 内存态（bundle）与磁盘同步
        net.update(local_ip=local_ip, local_port=local_port,
                   target_ip=target_ip, target_port=target_port)
        try:
            cfg_path = self._bundle.config_dir / "protocol.yaml"
            persist_network_file(cfg_path, net)
        except Exception as exc:
            self._log("网络已生效但写回 protocol.yaml 失败：%s" % exc)
            return True, "已生效，但写回配置文件失败：%s（重启将恢复旧值）" % exc
        self._log("网络设置已应用并持久化：本机 %s:%d → 控制器 %s:%d"
                  % (local_ip, local_port, target_ip, target_port))
        return True, "已生效"

    @pyqtSlot(bool)
    def set_host_mode(self, enabled: bool):
        """作为主机开关：仅切换本地状态 + 随包携带 host_mode 标志位，不触发/不阻止参数发送。

        非主机时控制模式按钮组禁用（set_control_mode 直接返回）。
        host_mode 位在下一次任何参数包中随字段下发（packets.build_send_values 读取）。
        """
        self._host = bool(enabled)
        self.host_mode_changed.emit(self._host)
        self._log("作为主机 = %s（标志位随参数包下发，不影响 UDP 发送）" % self._host)

    def get_presets(self):
        return self._presets

    def channels(self):
        """通道标识列表（俯仰/滚转，含 axis）。"""
        return self._bundle.channels()

    def send_fields(self):
        """send 结构体字段元数据列表（name/type/count/unit/zh），UI 渲染标签/单位用。

        只读透传 protocol.yaml，UI 不直接持有配置；zh 为空表示内部字段（不渲染）。
        """
        return self._bundle.protocol["structs"][
            "UDP_UI_Send_To_Controller_Parameter"]["fields"]

    def field_unit(self, name, default=""):
        """取某字段单位（如 friction→"N"），查不到返回 default。"""
        for f in self.send_fields():
            if f["name"] == name:
                return f.get("unit", default)
        return default

    def is_host(self) -> bool:
        """当前是否作为主机（UI 初始渲染灰框使能用）。"""
        return self._host

    def get_editing(self, ch):
        return self._editing[ch]

    def get_sent(self, ch):
        return self._sent[ch]

    def get_editing_preset_id(self):
        """当前编辑态关联的预设 id（UI 标题/返回提示用）。"""
        return self._editing_preset_id

    # ------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------
    def _log(self, text):
        self.log_message.emit("INFO", text)

    def _error(self, where, msg):
        self.error_occurred.emit(where, msg)
        self.log_message.emit("ERROR", "%s: %s" % (where, msg))

    def _find_preset(self, pid):
        return next((p for p in self._presets if p["id"] == pid), None)

    def _is_dirty(self, ch):
        return self._editing[ch] != self._sent[ch]

    def _is_dirty_field(self, ch, field):
        return self._editing[ch][field] != self._sent[ch][field]

    def _push_all(self, ch):
        """整通道回灌：9 个参数 + 18 点表（携带各自 dirty）。"""
        for field in PARAM_FIELDS:
            self.state_changed.emit(ch, field, self._editing[ch][field],
                                    self._is_dirty_field(ch, field))
        self.points_changed.emit(ch, list(self._editing[ch]["pos_pts"]),
                                 list(self._editing[ch]["force_pts"]),
                                 self._editing[ch] != self._sent[ch])

    # ------------------------------------------------------------
    # UDP 回调
    # ------------------------------------------------------------
    def _on_frame(self, data):
        try:
            n = len(self._channel_indexes)
            frames = packets.parse_recv_frame(self._recv_spec, data, n)
        except packets.ProtocolError as exc:
            self._error("周期帧解析", str(exc))
            return
        self.telemetry_received.emit({i: frames[i] for i in range(n)})

    def _on_link(self, connected):
        self._connected = connected
        self.link_state_changed.emit(connected, "已连接" if connected else "未连接")

    # ------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------
    def _build_and_send(self, ch, zero_calib=False):
        """从已下发态组包并直接发送（UDP 无连接；对端不在顶多丢包）。"""
        ch_id = self._bundle.channel_by_index(ch)
        values = packets.build_send_values(
            self._sent[ch],
            ch_id["axis"],
            flags=dict(self._flags[ch], zero_calib=zero_calib, host_mode=self._host))
        packet = packets.pack_packet(self._send_spec, values)
        self._deliver(packet)
        return True

    def _deliver(self, packet):
        """实际下发：记录到 _tx_log（供观测/测试），UDP 启用时真正 sendto。"""
        self._tx_log.append(packet)
        if self._udp is not None:
            self._udp.send_datagram(packet)

    @pyqtSlot(int)
    def send_parameters(self, ch):
        """内层「下载」：提交编辑态 + 直接发送 + 用户预设回写（决策 17）。"""
        if ch not in self._editing:
            self._error("send_parameters", "通道不存在: %r" % ch)
            return
        self._sent[ch] = copy.deepcopy(self._editing[ch])
        ok = self._build_and_send(ch)
        self.params_ack.emit(ch, ok)
        self._push_all(ch)
        self._maybe_writeback(ch)
        self._log("通道 %d 参数已下发" % ch)

    @pyqtSlot(int, str, object)
    def set_packet_field(self, ch, field, value):
        """编辑态提交（lineedit / 表格单元格），不下发。

        field：9 个参数名，或表格单元格 "pos_pts[5]" / "force_pts[17]"，
        或整表 "pos_pts" / "force_pts"（18 元素列表）。
        """
        data = self._editing.get(ch)
        if data is None:
            self._error("set_packet_field", "通道不存在: %r" % ch)
            return
        cell = _CELL_FIELD_RE.match(field)
        if cell is not None:
            arr_name, idx = cell.group(1), int(cell.group(2))
            if not 0 <= idx < preset_store.POINT_COUNT:
                self._error("set_packet_field", "点序号越界: %s" % field)
                return
            data[arr_name][idx] = float(value)
            return
        if field in PARAM_FIELDS:
            ftype = self._send_spec.fields_by_name()[field].type
            data[field] = int(value) if ftype.startswith("int") else float(value)
            self.state_changed.emit(ch, field, data[field],
                                    self._is_dirty_field(ch, field))
            return
        if field in ARRAY_FIELDS:
            arr = [float(v) for v in value]
            if len(arr) != preset_store.POINT_COUNT:
                self._error("set_packet_field", "%s 需要 18 个元素" % field)
                return
            data[field] = arr
            return
        self._error("set_packet_field", "未知字段: %s" % field)

    @pyqtSlot(int)
    def zero(self, ch):
        """校零脉冲：置位帧 → 延时 → 清除帧（防 latch）。"""
        self._log("通道 %d 校零脉冲：置位 → 发 → 清" % ch)
        self._build_and_send(ch, zero_calib=True)
        t = self._zero_timers[ch]
        t.stop()
        t.timeout.disconnect() if t.receivers(t.timeout) else None
        t.timeout.connect(lambda: self._build_and_send(ch, zero_calib=False))
        t.start(ZERO_PULSE_CLEAR_DELAY_MS)

    @pyqtSlot(int, int)
    def set_control_mode(self, ch, mode):
        """设置控制模式（0=OFF, 1=抖杆, 2=脉冲, 3=倍脉冲, 4=扫频, 5=正弦, 6=阶跃）。

        该功能已从主机切换按钮中移出，测试页直接可用；mode 会随参数包立即下发，并触发 control_mode_changed。
        """
        if not 0 <= mode <= 6:
            self._error("set_control_mode", "模式值非法: %d（应为 0..6）" % mode)
            return
        self._flags[ch]["control_mode"] = int(mode)
        self._build_and_send(ch)
        self.control_mode_changed.emit(ch, self._flags[ch]["control_mode"], False)
        self._log("通道 %d 控制模式 = %d" % (ch, self._flags[ch]["control_mode"]))

    def get_control_mode(self, ch):
        return self._flags[ch]["control_mode"]

    # ------------------------------------------------------------
    # 预设
    # ------------------------------------------------------------
    def _data_from_preset(self, ch, preset_id):
        preset = self._find_preset(preset_id)
        if preset is None:
            self._error("load_preset", "预设不存在: %r" % preset_id)
            return None
        if ch in preset["channels"]:
            return preset["channels"][ch]
        self._error("load_preset", "预设 %r 不含通道 %d" % (preset_id, ch))
        return None

    @pyqtSlot(int, str)
    def load_preset(self, ch, preset_id):
        data = self._data_from_preset(ch, preset_id)
        if data is None:
            return
        self._editing[ch] = copy.deepcopy(data)
        self._editing_preset_id = preset_id
        self._push_all(ch)
        self._log("通道 %d 已加载预设 %r（未下发，蓝字为未下发项）" % (ch, preset_id))

    @pyqtSlot(str)
    def download_preset(self, preset_id):
        """外层「下载」：加载全部通道 + 直接发送；不写文件（决策 17）。"""
        preset = self._find_preset(preset_id)
        if preset is None:
            self._error("download_preset", "预设不存在: %r" % preset_id)
            return
        self._editing_preset_id = preset_id
        for ch in sorted(preset["channels"]):
            self._editing[ch] = copy.deepcopy(preset["channels"][ch])
            self._sent[ch] = copy.deepcopy(self._editing[ch])
            ok = self._build_and_send(ch)
            self.params_ack.emit(ch, ok)
            self._push_all(ch)
        self._log("预设 %r 已下发（俯仰/滚转两通道）" % preset_id)

    def _maybe_writeback(self, ch):
        """内层「下载」后：用户新建预设 → 回写当前通道数据（出厂不回写）。"""
        preset = self._find_preset(self._editing_preset_id)
        if preset is None or preset_store.is_builtin(preset):
            return
        preset["channels"][ch] = copy.deepcopy(self._editing[ch])
        preset_store.save_presets(self._presets_path, self._presets)
        self.preset_list_changed.emit()
        self._log("已把通道 %d 数据回写预设 %r" % (ch, preset["id"]))

    @pyqtSlot()
    def create_preset(self):
        """上层「新建」：免弹窗复制 模式6 综合力感 生成用户新预设（决策 17/22）。"""
        base = self._find_preset(NEW_PRESET_SOURCE_ID)
        if base is None:
            self._error("create_preset", "缺少复制源 %s" % NEW_PRESET_SOURCE_ID)
            return None
        new_id = "user_%s" % datetime.now().strftime("%Y%m%d_%H%M%S")
        n = 1 + sum(1 for p in self._presets if p.get("category") == USER_CATEGORY)
        entry = {"id": new_id,
                 "label": "新建预设%d" % n,
                 "category": USER_CATEGORY,
                 "channels": copy.deepcopy(base["channels"])}
        self._presets.append(entry)
        preset_store.save_presets(self._presets_path, self._presets)
        self.preset_list_changed.emit()
        self._log("已新建预设 %r（复制 %s）" % (new_id, base["id"]))
        return new_id

    @pyqtSlot(str, dict)
    def update_preset(self, preset_id, data):
        """修改用户新建预设条目（文本字段 / 通道数据）。出厂预设拒绝。"""
        preset = self._find_preset(preset_id)
        if preset is None:
            self._error("update_preset", "预设不存在: %r" % preset_id)
            return
        if preset_store.is_builtin(preset):
            self._error("update_preset", "出厂预设不可修改: %r" % preset_id)
            return
        for key in ("label", "category", "description"):
            if key in data:
                preset[key] = str(data[key])
        if "channels" in data:
            preset["channels"] = preset_store._parse_channels(data["channels"], preset_id)
        preset_store.save_presets(self._presets_path, self._presets)
        self.preset_list_changed.emit()
        self._log("已更新预设 %r" % preset_id)

    @pyqtSlot(str)
    def delete_preset(self, preset_id):
        """删除用户新建预设；出厂（builtin）拒绝（决策 17）。"""
        preset = self._find_preset(preset_id)
        if preset is None:
            self._error("delete_preset", "预设不存在: %r" % preset_id)
            return False
        if preset_store.is_builtin(preset):
            self._error("delete_preset", "出厂预设不可删除: %r" % preset_id)
            return False
        self._presets.remove(preset)
        preset_store.save_presets(self._presets_path, self._presets)
        if self._editing_preset_id == preset_id:
            self._editing_preset_id = STARTUP_PRESET_ID
        self.preset_list_changed.emit()
        self._log("已删除预设 %r" % preset_id)
        return True
