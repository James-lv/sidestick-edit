# -*- coding: utf-8 -*-
"""preset_store —— config/presets.yaml 的加载、原子写与数据校验（决策 18）。

每条预设（状态）= 俯仰(0) + 滚转(1) 两个通道的完整数据，报文原值（无换算）。
每通道 11 字段（7 个力曲线/限位字段 + 4 个固定字段，全部随预设下发）：
    channels:
      0:
        friction:        <float>   # 摩擦力
        breakout_force:  <int>     # 启动力
        negative_stop:   <float>   # 负限位
        positive_stop:   <float>   # 正限位
        pos_pts:        [18 floats]  # 侧杆力感位置点（先发正方向9点，再发负方向9点，均为绝对值）
        force_pts:      [18 floats]  # 侧杆力感拟合力值
        scale_factor:    <int>     # 比例因子
        spring_force:    <int>     # 弹簧力
        damping_num:     <int>     # 阻尼分子
        damping_den:     <int>     # 阻尼分母（不可为 0）
        force_offset:    <int>     # 力偏置（随报文下发，不再由通道常量覆盖）

两类条目（决策 17）：
    出厂模式：builtin: true（state_1..state_7，对应 7 种力感模式）—— 界面不可删除、下载不回写文件。
    用户新建：可编辑、可删除、内层下载时把当前通道数据回写快照。

自恢复（决策 16）：本模块不做恢复——presets.yaml 缺失/损坏直接抛
PresetFormatError；打包版的恢复由 main.py 启动层从 exe 内置模板
（sys._MEIPASS datas）逐文件补齐。纯函数、零 Qt。
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

__all__ = [
    "PresetFormatError", "CHANNEL_DATA_KEYS", "POINT_COUNT",
    "parse_presets", "render_presets", "save_presets", "load_presets",
    "PRESET_CHANNEL_KEYS",
    "validate_channel_data", "is_builtin",
]


class PresetFormatError(Exception):
    """presets.yaml 格式非法。"""


#: 每通道数据必备键（= send 报文字段名，无换算）。
#: 7 个力曲线/限位字段 + 4 个固定字段。
CHANNEL_DATA_KEYS = ("friction", "breakout_force", "negative_stop", "positive_stop",
                     "force_offset",
                     "pos_pts", "force_pts",
                     "scale_factor", "spring_force", "damping_num", "damping_den")
#: 拟合点数（协议固定 18）
POINT_COUNT = 18
#: 每条预设包含的全部通道（俯仰 0 + 滚转 1）
PRESET_CHANNEL_KEYS = (0, 1)

_TEXT_KEYS = ("label", "category", "description")

_HEADER = """\
# ============================================================
# BCLS Joystick 预设库
#
#   presets：每条状态含【俯仰 0 + 滚转 1】两个通道，数据为报文原值。
#     每通道 11 字段（7 个力曲线/限位 + 4 个固定：scale_factor/spring_force/
#     damping_num/damping_den/force_offset，全部随预设下发，不再有协议层兜底）。
#     18 点表 pos_pts/force_pts 渲染为 flow 并按「正半 9 + 负半 9」折成两行，
#     与 UI 点表/报文逐位对应，可直接手改（决策 23）。
#   两类条目（决策 17）：
#   ① 出厂模式 state_1..state_7：builtin: true —— 不可删除、下载不回写本文件
#   ② 用户新建：界面「新建」复制 模式6 综合力感 生成（id 自动 user_+时间戳，
#      category: User）—— 可编辑、可删除、下载时把当前通道数据回写快照
#
#   - 界面增删改会全量重写本文件（原子写；文件头注释保留）
#   - 误删/损坏：打包版由启动层从 exe 内置模板恢复（决策 16）；开发环境直接报错
# ============================================================
"""


# ============================================================
# 数据校验
# ============================================================

def _as_float(value: Any, ctx: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise PresetFormatError("%s 不是数值: %r" % (ctx, value))


def _as_int(value: Any, ctx: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise PresetFormatError("%s 不是整数: %r" % (ctx, value))


def _as_bool(value: Any, ctx: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise PresetFormatError("%s 不是布尔: %r" % (ctx, value))


def validate_channel_data(data: Any, ctx: str) -> Dict[str, Any]:
    """校验单通道数据（11 个必备键；两张点表长度 = 18），返回归一化副本。

    11 个字段全部随预设下发，协议层无兜底：
    friction/breakout_force/negative_stop/positive_stop/force_offset/pos_pts/force_pts
    scale_factor/spring_force/damping_num/damping_den(int)。
    damping_den 是阻尼分母，不可为 0（决策 6）。
    """
    if not isinstance(data, dict):
        raise PresetFormatError("%s 通道数据必须是映射" % ctx)
    missing = [k for k in CHANNEL_DATA_KEYS if k not in data]
    if missing:
        raise PresetFormatError("%s 通道数据缺少键: %s" % (ctx, missing))
    out: Dict[str, Any] = {
        "friction": _as_float(data["friction"], ctx + ".friction"),
        "breakout_force": _as_int(data["breakout_force"], ctx + ".breakout_force"),
        "negative_stop": _as_float(data["negative_stop"], ctx + ".negative_stop"),
        "positive_stop": _as_float(data["positive_stop"], ctx + ".positive_stop"),
        "scale_factor": _as_int(data["scale_factor"], ctx + ".scale_factor"),
        "spring_force": _as_int(data["spring_force"], ctx + ".spring_force"),
        "damping_num": _as_int(data["damping_num"], ctx + ".damping_num"),
        "damping_den": _as_int(data["damping_den"], ctx + ".damping_den"),
        "force_offset": _as_int(data["force_offset"], ctx + ".force_offset"),
    }
    if out["damping_den"] == 0:
        raise PresetFormatError("%s.damping_den 不可为 0（阻尼分母）" % ctx)
    for key in ("pos_pts", "force_pts"):
        arr = data[key]
        if not isinstance(arr, list) or len(arr) != POINT_COUNT:
            raise PresetFormatError("%s.%s 必须是 %d 个元素的列表"
                                    % (ctx, key, POINT_COUNT))
        out[key] = [_as_float(v, "%s.%s[%d]" % (ctx, key, i))
                    for i, v in enumerate(arr)]
    return out


def _parse_channels(raw: Any, pid: str) -> Dict[int, Dict[str, Any]]:
    if not isinstance(raw, dict) or not raw:
        raise PresetFormatError("预设 %r 的 channels 必须是非空映射" % pid)
    channels: Dict[int, Dict[str, Any]] = {}
    for ck, vals in raw.items():
        try:
            ch = int(ck)
        except (TypeError, ValueError):
            raise PresetFormatError("预设 %r 的通道号非法: %r" % (pid, ck))
        if ch not in PRESET_CHANNEL_KEYS:
            raise PresetFormatError(
                "预设 %r 只能包含通道 %s（0=俯仰 1=滚转）"
                % (pid, list(PRESET_CHANNEL_KEYS)))
        channels[ch] = validate_channel_data(vals, "预设 %r 通道 %d" % (pid, ch))
    if set(channels) != set(PRESET_CHANNEL_KEYS):
        raise PresetFormatError("预设 %r 必须同时包含通道 %s"
                                % (pid, list(PRESET_CHANNEL_KEYS)))
    return channels


def _normalize_item(item: Any, index: int) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise PresetFormatError("第 %d 条预设不是映射" % index)
    pid = item.get("id")
    if not pid or not isinstance(pid, str):
        raise PresetFormatError("第 %d 条预设缺少合法的 id" % index)
    preset: Dict[str, Any] = {"id": pid}
    if item.get("builtin"):
        preset["builtin"] = True
    for key in _TEXT_KEYS:
        if item.get(key):
            preset[key] = str(item[key])
    preset["channels"] = _parse_channels(item.get("channels"), pid)
    return preset


def parse_presets(text: str) -> List[Dict[str, Any]]:
    """把 presets.yaml 全文解析为预设列表。"""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PresetFormatError("YAML 语法错误: %s" % exc)
    if data is None:
        return []
    if not isinstance(data, dict):
        raise PresetFormatError("顶层必须是映射，包含 presets 键")
    raw = data.get("presets")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PresetFormatError("presets 必须是列表")

    presets: List[Dict[str, Any]] = []
    seen = set()
    for index, item in enumerate(raw, start=1):
        preset = _normalize_item(item, index)
        if preset["id"] in seen:
            raise PresetFormatError("预设 id 重复: %s" % preset["id"])
        seen.add(preset["id"])
        presets.append(preset)
    return presets


class _PresetDumper(yaml.SafeDumper):
    """SafeDumper：纯数值列表压成 flow 行，容器结构保持 block 展开。"""


def _represent_compact_list(dumper, data):
    """仅把「全为数值」的列表渲染成 flow 一行（其余列表保持 block 展开）。

    presets.yaml 中全数值列表只有 pos_pts/force_pts 两张 18 点表；
    顶层 presets / channels 等容器均含 dict 元素，不会误判。
    """
    plain_numbers = bool(data) and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data,
                                     flow_style=plain_numbers)


_PresetDumper.add_representer(list, _represent_compact_list)


def _fold_18pt_lines(text: str) -> str:
    """把 pos_pts/force_pts 的 flow 行折成两行：正半 9 个 + 负半 9 个（决策 23）。

    YAML flow 序列允许在逗号后换行，折行仅是排版，解析结果不变。
    """
    out = []
    for line in text.split("\n"):
        m = re.match(r"^(\s*)(pos_pts|force_pts): \[(.*)\]$", line)
        if not m:
            out.append(line)
            continue
        indent, key, inner = m.group(1), m.group(2), m.group(3).strip()
        items = [s.strip() for s in inner.split(",")]
        if len(items) != POINT_COUNT:  # 非 18 点表不折（防御）
            out.append(line)
            continue
        cont = indent + "  "
        out.append("%s%s: [%s," % (indent, key, ", ".join(items[:9])))
        out.append("%s%s]" % (cont, ", ".join(items[9:])))
    return "\n".join(out)


def render_presets(presets: List[Dict[str, Any]]) -> str:
    """渲染为 yaml 全文（与 parse_presets 往返一致；文件头注释保留）。

    - 每条预设独立深拷贝后再 dump：共享引用会触发 YAML 锚点/别名
      （别名会导致手改一条预设连带改所有同名引用）。
    - 18 点表（pos_pts/force_pts）压成 flow 并按「正半 9 + 负半 9」折行，
      文件好读好改（决策 23）。
    """
    import copy
    copied = [copy.deepcopy(p) for p in presets]
    body = yaml.dump({"presets": copied}, Dumper=_PresetDumper,
                     allow_unicode=True, sort_keys=False, width=10000)
    return _HEADER + "\n" + _fold_18pt_lines(body)


def is_builtin(preset: Dict[str, Any]) -> bool:
    """出厂预设不可删除、下载不回写文件（决策 17）。"""
    return bool(preset.get("builtin"))


# ============================================================
# 文件 IO（原子写；恢复由打包启动层负责）
# ============================================================

def save_presets(path: Path, presets: List[Dict[str, Any]]) -> None:
    """全量原子重写：先写 *.tmp 再 os.replace（决策 7）。"""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(render_presets(presets), encoding="utf-8")
    os.replace(str(tmp), str(path))


def load_presets(path: Path,
                 events: Optional[List[Tuple[str, str]]] = None
                 ) -> List[Dict[str, Any]]:
    """加载预设库，返回预设列表。

    缺失/损坏直接抛错（恢复由打包启动层负责，决策 16）。
    事件约定：events.append((level, message))，level ∈ {"WARN"}（仅空库告警）。
    """
    path = Path(path)
    log = events.append if events is not None else (lambda item: None)

    if not path.exists():
        raise PresetFormatError("presets.yaml 不存在"
                                "（打包版重启可从内置模板自动恢复，决策 16）")
    presets = parse_presets(path.read_text(encoding="utf-8"))
    if not presets:
        log(("WARN", "presets.yaml 无任何预设状态"))
    return presets
