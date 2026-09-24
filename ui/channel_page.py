# -*- coding: utf-8 -*-
"""channel_page —— 单通道编辑页（俯仰 / 滚转 tab 的内容）。

布局（样式风格对齐原版 C++ mainwindow，控件类型用户确认）：
    ┌────────────── 左：参数设置 + 力感参数 ────────────┬──────── 右：曲线区 ────────┐
    │  [参数设置] 比例因子/弹簧力/阻尼(分子/分母)/摩擦力/ │   ☑标定曲线  [清轨迹][自适应][存图] │
    │            负限位/正限位/启动力/力偏置  lineedit   │   ┌────────────────────────┐ │
    │  [力感参数] 正方向 1..9 │ 负方向 10..18            │   │ 标定曲线(18点折线+圆点)  │ │
    │   每格：点号 + 位置 + 力 两列 QLineEdit 网格       │   │ + 实时遥测轨迹(力-位)    │ │
    │  [下载参数]                                           │   └────────────────────────┘ │
    └───────────────────────────────────────────────────┴────────────────────────────┘

前后端分离：
    - 渲染数据源 = backend.get_editing / get_sent（只读视图），不复制业务状态。
    - 输入完成 → backend.set_packet_field / zero / send_parameters（槽）。
    - 回灌：backend.state_changed(4 参数) / points_changed(18 点) / telemetry_received。
    - 蓝字 dirty = 编辑态 ≠ 已下发态（逐字段/逐格比对），只影响颜色。
"""

from PyQt5.QtCore import QTimer, Qt, pyqtSlot
from PyQt5.QtWidgets import (QCheckBox, QFileDialog, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from core.backend import PARAM_FIELDS
from core.curve import signed_curve
from core.format import format_value
from core.preset_store import POINT_COUNT

try:
    import pyqtgraph as pg
except Exception:                       # pragma: no cover - 环境缺 pyqtgraph 时降级
    pg = None

#: 遥测轨迹环形上限
_LIVE_MAX = 4000
#: 遥测刷屏周期（ms）——UDP 帧只进缓冲，QTimer 按此频率批量 setData（决策 #27）
_FLUSH_MS = 50
#: 曲线配色（对齐原版 C++ channel_plot_controller.cpp）
_COLOR_CALIB = (48, 163, 152, 150)    # 标定/理论曲线：青绿半透明
_COLOR_CALIB_PEN = (48, 163, 152)     # 标定曲线圆点描边：青绿
_COLOR_LIVE = (40, 110, 255)          # 实时力-位移轨迹：蓝
_COLOR_LEAD = (255, 0, 0)             # 当前点标记：红圈
#: 遥测去抖阈值（位置/力的浮点抖动不视为"变化"，避免误加点）
_TELEMETRY_EPS = 1e-4


class ChannelPage(QWidget):
    """单个通道的编辑页。"""

    def __init__(self, backend, ch, name, parent=None, back_callback=None):
        super().__init__(parent)
        self._backend = backend
        self._ch = ch
        self._channel_name = name
        self._back_callback = back_callback or (lambda: None)

        meta = {f["name"]: f for f in backend.send_fields()}
        self._param_units = {f: meta[f].get("unit", "") for f in PARAM_FIELDS}
        self._param_types = {f: meta[f].get("type", "float") for f in PARAM_FIELDS}

        self._build_ui(meta)
        self._wire()
        self.refresh()

    # ------------------------------------------------------------
    # UI 组装
    # ------------------------------------------------------------
    def _build_ui(self, meta):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- 左：参数 + 18 点表 -------------------------------------
        left = QWidget(self)
        self._left_widget = left
        left.setMaximumWidth(560)
        left.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)

        lv.addWidget(self._build_param_group(meta))
        lv.addWidget(self._build_point_group(meta), 1)
        lv.addWidget(self._build_action_row())

        root.addWidget(left, 0)

        # ---- 右：曲线区 ---------------------------------------------
        plot_panel = self._build_plot_panel(meta)
        self._plot_widget = plot_panel
        plot_panel.setMinimumWidth(420)
        root.addWidget(plot_panel, 1)

    def _build_param_group(self, meta):
        box = QGroupBox("参数设置", self)
        outer = QHBoxLayout(box)
        outer.setContentsMargins(10, 14, 10, 10)
        outer.setSpacing(12)

        self._param_edits = {}
        self._param_shown = {}

        # 左右两半与下方 18 点表的两半边界对齐；每行内部 label + stretch + edit + unit，
        # edit 固定宽度，不撑得过宽，整体行右边界对齐。
        left = self._build_param_half(meta, (
            "scale_factor",
            (("damping_num", "damping_den"), "阻尼"),
            "negative_stop",
            "breakout_force",
        ))
        right = self._build_param_half(meta, (
            "spring_force",
            "friction",
            "positive_stop",
            "force_offset",
        ))
        outer.addWidget(left)
        outer.addWidget(right)
        return box

    def _build_param_half(self, meta, items):
        """返回一个半区 widget，内部垂直排列若干行。"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        for item in items:
            if isinstance(item, tuple):
                self._add_damping_line(v, meta, item[1])
            else:
                self._add_param_line(v, meta, item)
        v.addStretch(1)
        return w

    def _add_param_line(self, layout, meta, name):
        zh = meta[name].get("zh") or name
        unit = meta[name].get("unit", "")
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)

        label = QLabel("%s：" % zh)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setObjectName("ParamLabel")
        label.setFixedWidth(100)

        edit = QLineEdit()
        edit.setObjectName("param_%s" % name)
        edit.setAlignment(Qt.AlignCenter)
        edit.setFixedWidth(100)
        edit.editingFinished.connect(lambda n=name: self._submit_param(n))

        unit_label = QLabel(unit)
        unit_label.setObjectName("UnitLabel")
        unit_label.setFixedWidth(40)

        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(edit)
        row.addWidget(unit_label)
        layout.addLayout(row)
        self._param_edits[name] = edit
        self._param_shown[name] = ""

    def _add_damping_line(self, layout, meta, caption):
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)

        label = QLabel("%s：" % caption)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setObjectName("ParamLabel")
        label.setFixedWidth(100)

        edits_box = QHBoxLayout()
        edits_box.setSpacing(8)
        edits_box.setContentsMargins(0, 0, 0, 0)
        for name in ("damping_num", "damping_den"):
            edit = QLineEdit()
            edit.setObjectName("param_%s" % name)
            edit.setAlignment(Qt.AlignCenter)
            edit.setFixedWidth(46)
            edit.editingFinished.connect(lambda n=name: self._submit_param(n))
            edits_box.addWidget(edit)
            self._param_edits[name] = edit
            self._param_shown[name] = ""
        edits_w = QWidget()
        edits_w.setLayout(edits_box)
        edits_w.setFixedWidth(100)

        unit_label = QLabel(" ")
        unit_label.setObjectName("UnitLabel")
        unit_label.setFixedWidth(40)

        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(edits_w)
        row.addWidget(unit_label)
        layout.addLayout(row)

    def _build_point_group(self, meta):
        box = QGroupBox("力感参数", self)
        outer = QHBoxLayout(box)
        outer.setContentsMargins(10, 14, 10, 10)
        outer.setSpacing(12)

        pos_unit = meta["pos_pts"].get("unit", "")
        force_unit = meta["force_pts"].get("unit", "")
        self._pos_edits = [None] * POINT_COUNT
        self._force_edits = [None] * POINT_COUNT

        # 正方向 1..9 / 负方向 10..18 两半并排（报文字节序约定）
        for half, caption in ((0, "正方向 1~9"), (1, "负方向 10~18")):
            half_w = QWidget(box)
            hv = QVBoxLayout(half_w)
            hv.setContentsMargins(0, 0, 0, 0)
            hv.setSpacing(2)
            cap = QLabel(caption, half_w)
            cap.setObjectName("HalfCaption")
            hv.addWidget(cap)

            g = QGridLayout()
            g.setHorizontalSpacing(4)
            g.setVerticalSpacing(6)
            head = QLabel("位置(%s)" % pos_unit)
            head.setObjectName("PointHeader")
            head.setFixedHeight(24)
            g.addWidget(head, 0, 1)
            head = QLabel("力(%s)" % force_unit)
            head.setObjectName("PointHeader")
            head.setFixedHeight(24)
            g.addWidget(head, 0, 2)

            for r in range(9):
                idx = r + half * 9
                num = QLabel(str(idx + 1))
                num.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                num.setObjectName("PointNo")
                num.setFixedWidth(20)
                num.setFixedHeight(26)
                g.addWidget(num, r + 1, 0)
                pe = self._new_point_edit(idx, "pos_pts")
                fe = self._new_point_edit(idx, "force_pts")
                pe.setFixedHeight(26)
                fe.setFixedHeight(26)
                self._pos_edits[idx] = pe
                self._force_edits[idx] = fe
                g.addWidget(pe, r + 1, 1)
                g.addWidget(fe, r + 1, 2)
            g.setColumnStretch(0, 0)
            g.setColumnStretch(1, 1)
            g.setColumnStretch(2, 1)
            hv.addLayout(g)
            hv.addStretch(1)
            outer.addWidget(half_w, 1)

        return box

    def _new_point_edit(self, idx, which):
        edit = QLineEdit(self)
        edit.setObjectName("%s_%d" % (which, idx + 1))
        edit.setAlignment(Qt.AlignCenter)
        edit.setFixedHeight(26)
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        edit.editingFinished.connect(
            lambda w=edit, i=idx, k=which: self._submit_point(i, k))
        return edit

    def _build_action_row(self):
        panel = QWidget(self)
        panel.setObjectName("ActionRowFrame")
        panel.setStyleSheet(
            "QWidget#ActionRowFrame {"
            "  background-color: #ffffff;"
            "  border: 1px solid #d8d8d8;"
            "  border-radius: 6px;"
            "}"
            "QPushButton {"
            "  min-height: 30px;"
            "  min-width: 80px;"
            "}"
        )
        row = QHBoxLayout(panel)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(12)

        back_btn = QPushButton("返回")
        back_btn.setObjectName("back_%d" % self._ch)
        back_btn.setMinimumWidth(80)
        back_btn.setMinimumHeight(30)
        back_btn.setStyleSheet(
            "QPushButton#back_%d {"
            "  background-color: #2f82f6;"
            "  color: white;"
            "  border: 1px solid #2a74d8;"
            "  border-radius: 4px;"
            "  font-weight: 600;"
            "}"
            "QPushButton#back_%d:hover {"
            "  background-color: #256fe0;"
            "}"
            "QPushButton#back_%d:pressed {"
            "  background-color: #1e5fc4;"
            "}"
            "}" % (self._ch, self._ch, self._ch)
        )
        back_btn.clicked.connect(self._back_callback)
        self._back_btn = back_btn
        row.addWidget(back_btn)
        row.addStretch(1)

        dl_btn = QPushButton("下载参数")
        dl_btn.setObjectName("download_%d" % self._ch)
        dl_btn.clicked.connect(lambda: self._backend.send_parameters(self._ch))
        row.addWidget(dl_btn)
        return panel

    def _build_plot_panel(self, meta):
        panel = QWidget(self)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(4)

        bar = QHBoxLayout()
        self._show_calib = QCheckBox("标定曲线", panel)
        self._show_calib.setChecked(True)
        self._live_pos_label = QLabel("位置: —", panel)
        self._live_force_label = QLabel("力: —", panel)
        self._live_pos_label.setObjectName("LivePosValue")
        self._live_force_label.setObjectName("LiveForceValue")
        zero_btn = QPushButton("校零")
        zero_btn.setObjectName("zero_%d" % self._ch)
        zero_btn.clicked.connect(lambda: self._backend.zero(self._ch))
        btn_clear = QPushButton("清轨迹")
        btn_fit = QPushButton("自适应")
        btn_save = QPushButton("存图")
        btn_clear.clicked.connect(self._clear_live)
        btn_fit.clicked.connect(lambda: self._plot.autoRange())
        btn_save.clicked.connect(self._save_png)
        bar.addWidget(self._show_calib)
        bar.addSpacing(18)        # 让实时位置/力值稍微往右偏移一点
        bar.addWidget(self._live_pos_label)
        bar.addWidget(self._live_force_label)
        bar.addStretch(1)          # 弹簧：标定曲线与右侧按钮之间弹开，按钮靠右
        for w in (zero_btn, btn_clear, btn_fit, btn_save):
            bar.addWidget(w)
        pv.addLayout(bar)

        if pg is None:                      # pragma: no cover
            pv.addWidget(QLabel("缺少 pyqtgraph，曲线区不可用"))
            return panel
        plot = pg.PlotWidget(panel)
        plot.setBackground("w")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setLabel("bottom", "位置", units=meta["pos_pts"].get("unit", ""))
        plot.setLabel("left", "力", units=meta["force_pts"].get("unit", ""))
        self._calib = pg.PlotDataItem(
            pen=pg.mkPen(_COLOR_CALIB, width=2),
            symbol="o", symbolSize=7, symbolBrush="w", symbolPen=pg.mkPen(_COLOR_CALIB_PEN, width=1.5))
        self._calib.setVisible(True)
        self._live = pg.PlotDataItem(
            pen=pg.mkPen(_COLOR_LIVE, width=2))
        # 当前点标记（红圈，跟随轨迹最新点）——原版 m_leadingMarker
        self._lead = pg.PlotDataItem(
            pen=pg.mkPen(_COLOR_LEAD, width=2),
            symbol="o", symbolSize=9, symbolBrush="w",
            symbolPen=pg.mkPen(_COLOR_LEAD, width=2))
        plot.addItem(self._calib)
        plot.addItem(self._live)
        plot.addItem(self._lead)
        self._plot = plot
        pv.addWidget(plot, 1)

        self._show_calib.toggled.connect(self._calib.setVisible)
        # 实时轨迹降频刷屏（决策 #27）：UDP 帧只 append，此处定时批量 setData
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(_FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush_live)
        self._flush_timer.start()
        return panel

    # ------------------------------------------------------------
    # 信号连接（只收本通道）
    # ------------------------------------------------------------
    def _wire(self):
        be = self._backend
        be.state_changed.connect(self._on_state_changed)
        be.points_changed.connect(self._on_points_changed)
        be.telemetry_received.connect(self._on_telemetry)
        self._lx, self._ly = [], []
        self._last_pt = None                # 去重：值未变化不追加（对齐原版）
        self._flushed = 0                   # 上次 flush 时已画点数

    # ------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------
    @staticmethod
    def _set_dirty(widget, dirty):
        widget.setProperty("dirty", bool(dirty))
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def refresh(self):
        """全量重绘：值（编辑态）+ 蓝字（逐项 vs 已下发态）+ 曲线（编辑态，所见即所得）。"""
        editing = self._backend.get_editing(self._ch)
        sent = self._backend.get_sent(self._ch)
        for name in PARAM_FIELDS:
            self._render_param(name, editing[name], editing[name] != sent[name])
        for i in range(POINT_COUNT):
            self._render_point(i, editing["pos_pts"][i],
                               editing["pos_pts"][i] != sent["pos_pts"][i],
                               editing["force_pts"][i],
                               editing["force_pts"][i] != sent["force_pts"][i])
        self._update_calib(editing)

    def _render_param(self, name, value, dirty):
        text = format_value(value)
        self._param_edits[name].setText(text)
        self._param_shown[name] = text
        self._set_dirty(self._param_edits[name], dirty)

    def _render_point(self, i, pval, p_dirty, fval, f_dirty):
        ptext, ftext = format_value(pval), format_value(fval)
        self._pos_edits[i].setText(ptext)
        self._force_edits[i].setText(ftext)
        self._set_dirty(self._pos_edits[i], p_dirty)
        self._set_dirty(self._force_edits[i], f_dirty)

    def fit_curve(self):
        """曲线自适应（进入编辑页时由上层调用，等同「自适应」按钮，决策 #26）。"""
        if pg is not None:
            self._plot.autoRange()

    def _update_calib(self, data):
        """标定曲线随编辑态数据即刷（决策 #24）：编辑 18 点立即见，不等下载。"""
        if pg is None:
            return
        # 存储/报文为幅值 18 点（决策 21）；绘图还原带符号坐标：负半取负入第三象限、
        # 两半首点（中位 ±启动力）相接 → 整条曲线收尾相连、无横跨假线。
        xs, ys = signed_curve(list(data["pos_pts"]), list(data["force_pts"]))
        self._calib.setData(xs, ys)

    # ------------------------------------------------------------
    # 提交（UI → backend）
    # ------------------------------------------------------------
    def _submit_param(self, name):
        edit = self._param_edits[name]
        text = edit.text().strip()
        if text == self._param_shown[name]:
            return
        try:
            value = int(text) if self._param_types.get(name) in ("int8", "int16", "int32") else float(text)
        except ValueError:
            edit.setText(self._param_shown[name])   # 非法输入 → 还原
            edit.selectAll()
            return
        self._backend.set_packet_field(self._ch, name, value)

    def _submit_point(self, i, which):
        edit = self._pos_edits[i] if which == "pos_pts" else self._force_edits[i]
        text = edit.text().strip()
        try:
            value = float(text)
        except ValueError:
            editing = self._backend.get_editing(self._ch)
            edit.setText(format_value(editing[which][i]))
            edit.selectAll()
            return
        self._backend.set_packet_field(self._ch, "%s[%d]" % (which, i), value)
        # 单元格无独立回灌信号 → 本地重算蓝字 + 曲线按编辑态即刷（决策 #24）
        editing = self._backend.get_editing(self._ch)
        sent = self._backend.get_sent(self._ch)
        self._set_dirty(edit, value != sent[which][i])
        self._update_calib(editing)

    # ------------------------------------------------------------
    # 后端回灌
    # ------------------------------------------------------------
    @pyqtSlot(int, str, object, bool)
    def _on_state_changed(self, ch, field, value, dirty):
        if ch != self._ch or field not in PARAM_FIELDS:
            return
        if self._param_edits[field].hasFocus():
            return                              # 编辑中不抢输入
        self._render_param(field, value, dirty)

    @pyqtSlot(int, list, list, bool)
    def _on_points_changed(self, ch, pos, force, dirty):
        if ch != self._ch:
            return
        sent = self._backend.get_sent(ch)
        for i in range(POINT_COUNT):
            self._render_point(i, pos[i], pos[i] != sent["pos_pts"][i],
                               force[i], force[i] != sent["force_pts"][i])
        # 信号携带编辑态 18 点 → 曲线即刷（决策 #24），下载后与已下发态一致
        self._update_calib({"pos_pts": pos, "force_pts": force})

    @pyqtSlot(dict)
    def _on_telemetry(self, channels):
        data = channels.get(self._ch)
        if data is None:
            if hasattr(self, "_live_pos_label"):
                self._live_pos_label.setText("位置: —")
            if hasattr(self, "_live_force_label"):
                self._live_force_label.setText("力: —")
            return

        if hasattr(self, "_live_pos_label"):
            self._live_pos_label.setText("位置: %s" % format_value(data.get("Position", 0)))
        if hasattr(self, "_live_force_label"):
            self._live_force_label.setText("力: %s" % format_value(data.get("LoadCellForce", 0)))

        if pg is None:
            return
        x = float(data["Position"])
        y = float(data["LoadCellForce"])
        # 变化才加点：阈值比较，避免浮点抖动（如 1.0000001 vs 1.0000002）被误判为变化
        if self._last_pt is not None:
            if (abs(x - self._last_pt[0]) < _TELEMETRY_EPS and
                    abs(y - self._last_pt[1]) < _TELEMETRY_EPS):
                return
        self._last_pt = (x, y)
        self._lx.append(x)
        self._ly.append(y)

    def _flush_live(self):
        """定时批量刷屏（决策 #27）：图形刷新频率与 UDP 帧率解耦，防卡顿。

        裁剪 + setData + 当前点标记更新都只在这里做（_FLUSH_MS 一次）。
        """
        if pg is None:
            return
        n = len(self._lx)
        if n == self._flushed:
            return                      # 无新数据不重绘
        if n > _LIVE_MAX:
            excess = n - _LIVE_MAX
            del self._lx[:excess]
            del self._ly[:excess]
            n = _LIVE_MAX
        if n:
            self._live.setData(self._lx, self._ly)
            self._lead.setData([self._lx[-1]], [self._ly[-1]])
        self._flushed = n

    def _clear_live(self):
        self._lx, self._ly = [], []
        self._last_pt = None
        self._flushed = 0
        if pg is not None:
            self._live.setData([], [])
            self._lead.setData([], [])

    def _save_png(self):
        ts = __import__("time").strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存曲线图", "bcls_ch%d_%s.png" % (self._ch, ts), "PNG (*.png)")
        if path and pg is not None:
            self._plot.grab().save(path)
