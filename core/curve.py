# -*- coding: utf-8 -*-
"""curve —— 18 点幅值表 → 真实坐标绘图折线（决策 21）。

协议/配置语义（决策 21，用户确认 2026-09-09）：
    pos_pts / force_pts 各 18 点，均按**正绝对值**存（报文与 lineedit 原样显示）：
      前 9 点 = 正方向：位置 0→+max，力 0→+Fmax；
      后 9 点 = 负方向：|位置| 0→max，力幅 0→Fmax（两半各自从中位出发、升序）。
    只有绘图需要把负半还原成带符号坐标。

`signed_curve` 规则：
    负半 9 点位置、力**取负并反转** → x 从 -max 单调升到 0、y 从 -Fmax 升到 -F0；
    再拼接正半（x 0→+max，y +F0→+Fmax）。
    两半首点都在中位 pos≈0（力 +F0 / -F0）→ 相邻即连成原点启动力竖线，
    整条折线从 (-max,-Fmax) 连续走到 (+max,+Fmax)，无横跨假线。

纯函数、零 Qt、零 IO。
"""

from core.preset_store import POINT_COUNT

__all__ = ["signed_curve"]


def signed_curve(pos_pts, force_pts):
    """幅值 18 点 → 带符号绘图坐标 (xs, ys)，点数不变（含中点两点的竖连）。

    pos_pts/force_pts 各 18 个非负幅值（先正半 9 点、后负半 9 点）。
    返回的 xs 单调非降（-max → 0 → +max），负半力已取负进入第三象限。
    """
    half = POINT_COUNT // 2
    xs = [-v for v in reversed(pos_pts[half:])] + list(pos_pts[:half])
    ys = [-v for v in reversed(force_pts[half:])] + list(force_pts[:half])
    return xs, ys
