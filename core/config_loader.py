# -*- coding: utf-8 -*-
"""config_loader —— 加载 protocol.yaml + 命令行覆盖。

职责（ARCHITECTURE §6）：
    1. 加载 config/protocol.yaml（网络 4 项 / 结构体 / 包定义 / 通道标识）；
       缺失/损坏直接报 ConfigError，不做自动重建（决策 12 修订）。
    2. 两层覆盖：YAML 默认值 → 命令行参数（--target-ip 等）。
    3. 校验：network / channel_ids。

纯函数、零 Qt。所有 send 包字段值（含原 send_defaults 6 个固定字段）现由
预设库 presets.yaml 提供（决策：预设=所有 UDP 发送参数，只有点击才发送）。
"""

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml


class ConfigError(Exception):
    """配置缺失 / 结构非法。"""


def default_config_dir() -> Path:
    """<项目根>/config（项目根 = 本文件上级目录）。"""
    return Path(__file__).resolve().parent.parent / "config"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError("%s 不存在（该文件不做自动重建，请从备份恢复）" % path.name)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError("%s 解析失败: %s" % (path.name, exc))
    if not isinstance(data, dict):
        raise ConfigError("%s 顶层不是映射" % path.name)
    return data


# ============================================================
# 校验
# ============================================================

def _coerce_network(protocol: dict) -> None:
    net = protocol.get("network")
    if not isinstance(net, dict):
        raise ConfigError("protocol.yaml 缺少 network 段")
    for key in ("local_port", "target_port"):
        try:
            net[key] = int(net[key])
        except (KeyError, TypeError, ValueError):
            raise ConfigError("network.%s 不是合法整数: %r" % (key, net.get(key)))


def _validate_channel_ids(protocol: dict) -> None:
    ids = protocol.get("channel_ids")
    if not isinstance(ids, list) or len(ids) != 2:
        raise ConfigError("protocol.yaml 缺少 channel_ids 或不是 2 项")
    axes = []
    for ch in ids:
        missing = [k for k in ("index", "name", "axis") if k not in ch]
        if missing:
            raise ConfigError("channel_ids %r 缺少键: %s" % (ch.get("index"), missing))
        axes.append(ch["axis"])
    if len(set(axes)) != len(axes):
        raise ConfigError("channel_ids axis 值不唯一: %s" % axes)


@dataclass
class ConfigBundle:
    """一次加载得到的全部配置。"""
    protocol: dict
    config_dir: Path

    def channels(self) -> List[dict]:
        """通道标识列表（固定 2 项：index/name/axis）。"""
        return self.protocol["channel_ids"]

    def channel_by_index(self, index: int) -> dict:
        for ch in self.channels():
            if ch["index"] == index:
                return ch
        raise KeyError("通道不存在: %r" % index)


def load_all(config_dir: Optional[Path] = None) -> ConfigBundle:
    """加载协议配置（校验 + 端口 int 化）。"""
    cfg_dir = Path(config_dir) if config_dir else default_config_dir()
    protocol = _load_yaml(cfg_dir / "protocol.yaml")
    _coerce_network(protocol)
    _validate_channel_ids(protocol)
    return ConfigBundle(protocol=protocol, config_dir=cfg_dir)


# ============================================================
# 命令行覆盖（第二层，优先级最高）
# ============================================================

# --flag → protocol.yaml 中的字段路径
CLI_FIELD_MAP = {
    "target_ip":   ("network", "target_ip"),
    "local_ip":    ("network", "local_ip"),
    "local_port":  ("network", "local_port"),
    "target_port": ("network", "target_port"),
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BCLS Joystick 上位机 (PyQt 重构)")
    parser.add_argument("--target-ip", help="覆盖控制器 IP")
    parser.add_argument("--target-port", type=int, help="覆盖控制器收包端口（默认 9300）")
    parser.add_argument("--local-ip", help="覆盖本机绑定 IP")
    parser.add_argument("--local-port", type=int, help="覆盖本机端口（默认 9200）")
    parser.add_argument("--config-dir", help="配置目录（默认 <项目根>/config）")
    parser.add_argument("--selfcheck", action="store_true",
                        help="运行协议/配置自检后退出")
    parser.add_argument("--no-udp", action="store_true",
                        help="不启动 UDP（界面调试用）")
    return parser


def apply_cli_overrides(bundle: ConfigBundle, args: argparse.Namespace) -> List[str]:
    """把命令行参数写到 bundle.protocol 对应字段，返回日志行。"""
    applied = []
    for flag, path in CLI_FIELD_MAP.items():
        value = getattr(args, flag, None)
        if value is None:
            continue
        node = bundle.protocol
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        applied.append("命令行覆盖 %s = %r" % (".".join(path), value))
    return applied


# ============================================================
# 网络设置持久化（菜单「设置→网络绑定…」写回 protocol.yaml）
# ============================================================

#: network 段可持久化键（顺序即文件行序）
NETWORK_KEYS = ("target_ip", "target_port", "local_ip", "local_port")

#: network 子键行：`  target_ip:   "127.0.0.1"   # 控制器 IP`
_NET_LINE_RE = re.compile(
    r"^(  (%s):)(\s*)(.*?)(\s*)(#.*)?(\r?\n)?$"
    % "|".join(re.escape(k) for k in NETWORK_KEYS),
    re.MULTILINE)


def update_network_yaml(text: str, values: Dict[str, object]) -> str:
    """行级替换 protocol.yaml 的 network 段 4 值，**保留全部注释**。

    - 只匹配 2 空格缩进的顶层 network 子键行（协议结构体在别处，不误伤）；
    - 原值带双引号（IP 习惯写法）→ 新值同样带引号；端口纯数字不带引号；
    - 值仍从第 17 列起（与文件原对齐风格一致），行内 `#` 注释原样保留；
    - 该键不在 values 中 → 保持原样。
    """
    def _sub(m: "re.Match") -> str:
        head, key, _ws, old_val, _sp, comment, nl = m.groups()
        if key in values:
            quoted = old_val.startswith('"') and old_val.endswith('"')
            val = '"%s"' % values[key] if quoted else str(values[key])
        else:
            val = old_val
        pad = " " * max(1, 16 - len(head))
        tail = ("  " + comment) if comment else ""
        return "%s%s%s%s%s" % (head, pad, val, tail, nl or "")

    new_text, n = _NET_LINE_RE.subn(_sub, text)
    if n == 0:
        raise ConfigError("protocol.yaml 未找到 network 段（期望 4 键行）")
    return new_text


def persist_network_file(path: Path, values: Dict[str, object]) -> str:
    """把 network 4 值原子写回 protocol.yaml，返回新文本。

    写前先 safe_load + 端口 int 校验，杜绝把损坏的 YAML 落盘。
    """
    p = Path(path)
    new_text = update_network_yaml(p.read_text(encoding="utf-8"), values)
    try:
        data = yaml.safe_load(new_text)
    except Exception as exc:
        raise ConfigError("写回校验失败（不落盘）: %s" % exc)
    _coerce_network(data)          # 校验 network 段仍在且端口合法
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, p)
    return new_text
