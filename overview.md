# BCLS Joystick PyQt 重构 — UI 其余部分完成

## 完成内容

1. **主窗口双层布局** (`ui/main_window.py`)
   - 顶部浅蓝渐变标题栏（与原版 C++ 一致）：返回预设管理按钮、标题、网络连接按钮（左侧指示灯）、作为主机按钮（左侧指示灯）。
   - 中间 `QStackedWidget`：预设管理页（首页）↔ 两通道编辑页。
   - 底部灰框控制模式按钮组，固定只操作俯仰通道（axis=1）。

2. **预设管理页** (`ui/preset_manager.py`)
   - 左侧 `QTreeWidget` 按 State/User 分组显示预设。
   - 右侧固定 260px 操作面板：新建/编辑/删除/下载按钮 + 实时状态面板。

3. **通道编辑容器** (`ui/editor_page.py`)
   - `QTabWidget` 两 tab：俯仰 / 滚转。
   - 切 tab 时自动刷新当前通道显示。

4. **单通道编辑页** (`ui/channel_page.py`)
   - 左侧上组「参数设置」：9 个参数 lineedit 两列布局（比例因子 / 弹簧力 / 阻尼分子/分母 / 摩擦力 / 负限位 / 启动力 / 正限位 / 力偏置），加宽对齐。
   - 左侧下组「力感参数」：18 点 QLineEdit 网格（正负半区各 9 行）。
   - 右侧：pyqtgraph 标定曲线（18 点折线+圆点）+ 实时遥测轨迹 + 清轨迹/自适应/存图/标定曲线开关。
   - 脏标记驱动蓝字：`setProperty("dirty", True)` + 样式刷新。

5. **样式表** (`assets/style.qss`)
   - 全局字体放大到 12pt。
   - 顶部标题栏改为浅蓝渐变背景（原版风格）。
   - 网络连接 / 作为主机改为带文字按钮 + 左侧指示灯样式。
   - 返回按钮、QTabWidget、预设管理右侧面板、点表表头样式。

6. **后端完善** (`core/backend.py`)
   - 新增只读访问器 `send_fields()` / `field_unit()` / `get_editing_preset_id()`。
   - 修复校零脉冲 `QTimer.singleShot` 残留崩溃：改为 per-channel `QTimer`，`stop()` 时统一停止。

7. **测试**
   - 重写 `tests/test_main_window.py`（9 用例，适配新版按钮 + 指示灯布局）。
   - 新增 `tests/test_editor_page.py`（5 用例）、`tests/test_preset_manager.py`（6 用例）。
   - `tests/__init__.py` 统一创建 offscreen `QApplication`。

## 关键决策

- 前后端分离：UI 只通过 `BackendService` 信号/槽交互，不碰 socket/struct/文件 IO。
- 18 点表用 `QLineEdit` 网格仿原版 C++，不用 `QTableWidget`。
- 18 点按**正绝对值**存储/传输/显示（决策 21，先正半 9 后负半 9）；绘图经 `core/curve.signed_curve` 把负半取负反转还原成带符号坐标，曲线从 (-max,-Fmax) 连续到 (+max,+Fmax)、中点竖连为启动力台阶，无横跨假线。
- 控制模式按钮组固定只服务俯仰；后端 API 仍保留 `channel` 参数以便后续扩展。

## 运行方式

```bash
cd pyqt_refactor
python main.py

# 无 UDP 调试用
python main.py --no-udp

# 测试
python -m unittest discover -s tests -t .
```

## 验证结果

- `python -m unittest discover -s tests -t .`：**104 用例全绿**（2026-09-09 删脚蹬 + 18 点绝对值语义 + 菜单栏网络设置后回归）。
- `python -m core.selfcheck`：send=182B / recv=16B / 往返一致 / 预设解析全通过。
- offscreen 冒烟截图：`docs/screenshots/page0_presets.png`、`docs/screenshots/page1_editor.png`。
- 顶部菜单栏「设置→网络绑定…」：运行中改本机/控制器 IP 与端口，立即生效并写回 protocol.yaml（决策 25）。

## 已知限制

- offscreen 平台截图中文字不渲染，属平台限制；实际 Windows 桌面运行正常。
