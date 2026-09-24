# -*- coding: utf-8 -*-
"""数值显示格式化：替代 protocol.yaml 里 per-field 的 decimals 配置。

统一规则（用户决策）：
- 整值（含 1.0 / -0.0 这类浮点整值）→ 显示为整数，如 "240" / "0"
- 非整值 → 保留最多 max_decimals 位（默认 2），如 "5.50"

注意：固定 2 位会把绝对值 < 0.005 的小量吞成 "0.00"（如 showbili=0.001）。
若该量级参数需要保留有效数字，改 small_threshold / small_decimals 或整体放宽 max_decimals。
"""

SMALL_THRESHOLD = 0.01   # |v| < 此值且非 0 → 视为"小量"，用 more_decimals 位
SMALL_DECIMALS = 4


def format_value(value, max_decimals: int = 2) -> str:
    """把数值格式化为显示字符串。value 可为 int / float / 可转 float 的标量。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)

    # -0.0 → "0"：避免显示成 "-0"
    if f == 0:
        return "0"

    # 整值浮点（1.0 / 240.0）→ 整数显示
    if f.is_integer():
        return str(int(f))

    # 小量保护：避免被 2 位四舍五入吞成 0.00
    if abs(f) < SMALL_THRESHOLD:
        return f"{f:.{SMALL_DECIMALS}f}"

    return f"{f:.{max_decimals}f}"
