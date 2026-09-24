# -*- coding: utf-8 -*-
"""selfcheck —— 阶段 1 自检入口（PROCESS §4 验收标准）。

用法（项目根目录）：
    python -m core.selfcheck

检查项：
    1. 配置加载（protocol.yaml：网络/通道标识/固定值）
    2. send 参数包逐字段偏移表 + 断言 182B；recv 周期帧单通道 8B × 2 = 16B
    3. 182B 组包/解包往返一致（用 模式1 预设的通道数据实组包）
    4. presets.yaml 解析/渲染往返一致
    5. 报错路径：配置文件缺失/损坏 → 明确报错（恢复由打包启动层负责，决策 16）
"""

import math
import shutil
import sys
import tempfile
from pathlib import Path

try:
    from core import config_loader, packets, preset_store
except ImportError:  # 允许直接以脚本方式运行：python core/selfcheck.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import config_loader, packets, preset_store


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("  [%s] %s%s" % (status, name, (" - " + detail) if detail else ""))
    if not condition:
        _failures.append(name)


def print_offset_table(spec):
    print("  %-22s %-16s %-12s %6s %6s" % ("Group", "Field", "Type", "Offset", "Bytes"))
    print("  " + "-" * 66)
    last_group = None
    for group, name, type_desc, offset, size, _count in packets.offset_table(spec):
        if group != last_group:
            print("  -- %s" % group)
            last_group = group
        print("  %-22s %-16s %-12s %6d %6d" % ("", name, type_desc, offset, size))
    print("  " + "-" * 66)
    print("  total = %d bytes" % spec.size)


def main() -> int:
    global _failures
    _failures = []
    print("=" * 70)
    print("BCLS Joystick 自检 (python -m core.selfcheck)")
    print("=" * 70)

    # ---------- 1. 配置加载 ----------
    print("\n[1] 配置加载")
    bundle = config_loader.load_all()
    check("通道标识 = 2", len(bundle.channels()) == 2,
          "实际 %d" % len(bundle.channels()))
    check("network 端口", bundle.protocol["network"]["local_port"] == 9200
          and bundle.protocol["network"]["target_port"] == 9300)

    # ---------- 2. send 偏移表 ----------
    print("\n[2] send 参数包字段偏移表（期望 182B）")
    spec2 = packets.build_packet_spec(bundle.protocol, "send")
    print_offset_table(spec2)
    check("send = 182 B", spec2.size == 182, "实际 %d" % spec2.size)

    print("\n[3] recv 周期帧（期望单通道 8B × 2 = 16B）")
    spec1 = packets.build_packet_spec(bundle.protocol, "recv")
    print("  单通道块 = %d B, 字段: %s"
          % (spec1.size, ", ".join(f.name for f in spec1.fields)))
    check("recv 单通道块 = 8 B", spec1.size == 8, "实际 %d" % spec1.size)
    sample_frame = b"".join([packets.pack_packet(spec1, {"Position": 1.5, "LoadCellForce": -2.25})
                             for _ in range(2)])
    check("周期帧 = 16 B", len(sample_frame) == 16, "实际 %d" % len(sample_frame))
    frames = packets.parse_recv_frame(spec1, sample_frame, 2)
    check("周期帧解析", all(f["Position"] == 1.5 and f["LoadCellForce"] == -2.25
                            for f in frames))

    # ---------- 4. 用 default 预设实组包 + 往返 ----------
    print("\n[4] send 组包/解包往返（模式1 · 俯仰通道）")
    presets = preset_store.load_presets(bundle.config_dir / "presets.yaml")
    check("出厂预设 7 条", len(presets) == 7, "实际 %d" % len(presets))
    by_id = {p["id"]: p for p in presets}
    ch0 = by_id["state_1"]["channels"][0]
    ch_id = bundle.channel_by_index(0)
    values = packets.build_send_values(ch0,
                                       ch_id["axis"],
                                       flags={"zero_calib": False, "control_mode": 0})
    packet = packets.pack_packet(spec2, values)
    check("组包字节数", len(packet) == 182, "实际 %d" % len(packet))
    decoded = packets.unpack_packet(spec2, packet)

    def _same(a, b):
        # 报文是 float32，float64 源值比较用容差；int/bool 精确比较
        if isinstance(a, list):
            return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
        if isinstance(a, float):
            return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
        return a == b

    mismatch = [k for k in values if not _same(values[k], decoded[k])]
    check("往返一致（float32 容差）", not mismatch, "不一致字段: %s" % mismatch)
    check("点表 18 点", len(ch0["pos_pts"]) == 18 and len(ch0["force_pts"]) == 18)

    # ---------- 5. 预设库 ----------
    print("\n[5] presets.yaml 解析 / 渲染往返")
    roundtrip = preset_store.parse_presets(preset_store.render_presets(presets))
    check("渲染→解析往返一致", roundtrip == presets)

    # ---------- 6. 报错路径（临时目录，不碰真实 config） ----------
    print("\n[6] 报错路径（临时目录，不碰真实 config）")
    tmp = Path(tempfile.mkdtemp(prefix="bcls_selfcheck_"))
    try:
        raised = False
        try:
            preset_store.load_presets(tmp / "presets.yaml")
        except preset_store.PresetFormatError:
            raised = True
        check("presets.yaml 缺失 → 明确报错（恢复由打包启动层负责）", raised)
        (tmp / "presets.yaml").write_text("a: [1", encoding="utf-8")
        raised = False
        try:
            preset_store.load_presets(tmp / "presets.yaml")
        except preset_store.PresetFormatError:
            raised = True
        check("presets.yaml 损坏 → 明确报错", raised)
        (tmp / "protocol.yaml").write_text("network: {}", encoding="utf-8")
        raised = False
        try:
            config_loader.load_all(config_dir=tmp)
        except config_loader.ConfigError:
            raised = True
        check("主 YAML 缺失/非法 → 明确报错", raised)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 汇总 ----------
    print("\n" + "=" * 70)
    if _failures:
        print("自检未通过：%d 项 → %s" % (len(_failures), "; ".join(_failures)))
        return 1
    print("自检全部通过（send=182B / recv=16B / 往返一致 / 预设）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
