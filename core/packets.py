# -*- coding: utf-8 -*-
"""packets —— 按 protocol.yaml 在运行时生成 struct 格式串（禁手写，ARCHITECTURE §8）。

要点：
    - 类型映射 int8→b / int16→h / int32→i / float→f / bool→?，字节序小端 `<`，
      对应 C++ `#pragma pack(push, 1)`。
    - `build_packet_spec` 产出逐字段偏移表；PORT2_Send 期望 182B、PORT1_Recv
      单通道块 8B，由 selfcheck / backend 断言。

纯函数、零 Qt、零 IO。
"""

import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

#: 报文字段类型 → struct 字符
TYPE_MAP = {"int8": "b", "int16": "h", "int32": "i", "float": "f", "bool": "?"}

#: 字节序：小端 + 关闭对齐（等价 #pragma pack(1)）
BYTE_ORDER = "<"


class ProtocolError(Exception):
    """协议定义非法 / 字段缺失 / 字节数不符。"""


# ============================================================
# 字段与包描述
# ============================================================

@dataclass
class FieldSpec:
    """单个（可带 count 的数组）报文字段。"""
    group: str          # 所属结构体组（如 Channel_Header）
    name: str           # 字段名（如 Position）
    type: str           # int8/int16/int32/float/bool
    count: int          # 数组长度，标量为 1
    offset: int         # 包内字节偏移
    size: int           # 占用字节数

    @property
    def fmt_char(self) -> str:
        return TYPE_MAP[self.type]


@dataclass
class PacketSpec:
    """一个 UDP 包的完整字节布局。"""
    key: str                    # 如 PORT2_Send
    fmt: str                    # 完整 struct 格式串（含字节序前缀）
    size: int                   # 期望字节数
    fields: List[FieldSpec]     # 展开后的字段表（顺序 = 字节顺序）
    groups: List[str]           # layout 引用的结构体组（顺序保留）

    def fields_by_name(self) -> Dict[str, FieldSpec]:
        return {f.name: f for f in self.fields}


def _flatten_groups(structs: dict) -> Dict[str, dict]:
    """收集结构体定义：structs 扁平（值含 fields）或按命名空间嵌套均可。"""
    groups: Dict[str, dict] = {}
    for key, value in structs.items():
        if not isinstance(value, dict):
            continue
        if "fields" in value:            # 扁平：structs 直接是结构体定义
            groups[key] = value
        else:                            # 嵌套：一层命名空间
            for gname, gdef in value.items():
                if gname in groups:
                    raise ProtocolError("结构体组名重复: %s" % gname)
                groups[gname] = gdef
    return groups


def build_packet_spec(protocol: dict, packet_key: str) -> PacketSpec:
    """按 packets.<packet_key>.layout 引用的结构体顺序展开字段，生成偏移表与格式串。"""
    packets = protocol.get("packets")
    if not isinstance(packets, dict) or packet_key not in packets:
        raise ProtocolError("protocol.yaml 缺少 packets.%s" % packet_key)
    pk = packets[packet_key]
    if "layout" not in pk:
        raise ProtocolError("packets.%s 缺少 layout 列表" % packet_key)
    groups_def = _flatten_groups(protocol.get("structs", {}))

    fmt_chars: List[str] = [BYTE_ORDER]
    fields: List[FieldSpec] = []
    offset = 0
    group_order: List[str] = []

    for gname in pk["layout"]:
        gdef = groups_def.get(gname)
        if gdef is None:
            raise ProtocolError("包 %s 引用了未定义的结构体组: %s" % (packet_key, gname))
        group_order.append(gname)
        for fdef in gdef.get("fields", []):
            ftype = fdef["type"]
            if ftype not in TYPE_MAP:
                raise ProtocolError("字段 %s 类型未知: %s" % (fdef["name"], ftype))
            count = int(fdef.get("count", 1))
            if count < 1:
                raise ProtocolError("字段 %s count 非法: %r" % (fdef["name"], count))
            unit = struct.calcsize(TYPE_MAP[ftype])
            fields.append(FieldSpec(group=gname, name=fdef["name"], type=ftype,
                                    count=count, offset=offset, size=unit * count))
            fmt_chars.append(TYPE_MAP[ftype] * count)
            offset += unit * count

    return PacketSpec(key=packet_key, fmt="".join(fmt_chars), size=offset,
                      fields=fields, groups=group_order)


# ============================================================
# 打包 / 解包
# ============================================================

def pack_packet(spec: PacketSpec, values: Dict[str, Any]) -> bytes:
    """按字段名取值组包。count>1 的字段要求等长序列。"""
    buf = bytearray(spec.size)
    for f in spec.fields:
        if f.name not in values:
            raise ProtocolError("组包缺少字段 %s（组 %s）" % (f.name, f.group))
        value = values[f.name]
        if f.count > 1:
            if len(value) != f.count:
                raise ProtocolError("字段 %s 需要 %d 个元素，实际 %d 个"
                                    % (f.name, f.count, len(value)))
            packed = struct.pack(BYTE_ORDER + f.fmt_char * f.count, *value)
        else:
            packed = struct.pack(BYTE_ORDER + f.fmt_char, value)
        struct.pack_into("%ds" % f.size, buf, f.offset, packed)
    return bytes(buf)


def unpack_packet(spec: PacketSpec, data: bytes) -> Dict[str, Any]:
    """解包：count>1 → list，标量 → 单值。"""
    if len(data) != spec.size:
        raise ProtocolError("包 %s 字节数不符：期望 %d，实际 %d"
                            % (spec.key, spec.size, len(data)))
    out: Dict[str, Any] = {}
    for f in spec.fields:
        raw = struct.unpack_from(BYTE_ORDER + f.fmt_char * f.count, data, f.offset)
        out[f.name] = list(raw) if f.count > 1 else raw[0]
    return out


def parse_recv_frame(spec: PacketSpec, data: bytes, n_channels: int) -> List[dict]:
    """PORT1 周期帧：n_channels 个单通道块依次拼接，返回每通道 {字段: 值}。"""
    if len(data) != spec.size * n_channels:
        raise ProtocolError("周期帧字节数不符：期望 %d×%d=%d，实际 %d"
                            % (spec.size, n_channels, spec.size * n_channels, len(data)))
    frames = []
    for i in range(n_channels):
        frames.append(unpack_packet(spec, data[i * spec.size:(i + 1) * spec.size]))
    return frames


# ============================================================
# 工艺参数 → 报文字段换算（protocol.yaml 的 curve_sources）
# ============================================================

def build_send_values(channel_data: Dict[str, Any],
                      axis: int,
                      flags: Dict[str, bool]) -> Dict[str, Any]:
    """组装 send 包全部字段值（决策 18：预设/编辑数据即报文原值，无换算）。

    channel_data 必须是**完整**的某通道数据（10 个字段：friction /
    breakout_force / negative_stop / positive_stop / pos_pts[18] /
    force_pts[18] / scale_factor / spring_force / damping_num / damping_den，
    全部来自 presets.yaml）。
    不再有协议层默认值兜底——缺字段会直接 KeyError（强制“填充好才发送”）。

    - channel_data：当前通道数据（报文原值，来自预设或内层编辑）；
      含 force_offset（力偏置），直接随报文下发
    - axis：通道标识常量（protocol.yaml 的 channel_ids）
    - flags：运行时控制标志 {"zero_calib","control_mode","host_mode"}
      （校零脉冲 / 0=OFF..6=阶跃 / 主机）
    """
    values: Dict[str, Any] = dict(channel_data)
    values["axis"] = axis
    values["zero_calib"] = bool(flags.get("zero_calib", False))
    values["control_mode"] = int(flags.get("control_mode", 0))
    values["host_mode"] = bool(flags.get("host_mode", True))    # 作为主机标志位（默认主机）
    return values


# ============================================================
# 自检辅助
# ============================================================

def offset_table(spec: PacketSpec) -> List[Tuple[str, str, str, int, int, int]]:
    """(组, 字段, 类型+数组, 偏移, 字节, 数量) 行列表，供 selfcheck 打印。"""
    rows = []
    for f in spec.fields:
        type_desc = f.type if f.count == 1 else "%s[%d]" % (f.type, f.count)
        rows.append((f.group, f.name, type_desc, f.offset, f.size, f.count))
    return rows
