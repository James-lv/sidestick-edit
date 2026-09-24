# BCLS Joystick — PyQt 重构架构

> **文档定位**：本文是**架构设计文件**，只规定分层、边界、通信契约与配置规范，**不含任何实现代码**。
> 原 C++ 项目位于上级目录，协议结构以 `CommunicationPackets.h` 为权威来源。
> 配置文件：`../config/protocol.yaml`（协议/网络/通道标识权威）、`../config/presets.yaml`（预设库：每通道 18 点+参数直配）。
> **界面无配置文件**（2026-09-08 确认）：界面结构与文案硬编码在 `ui/` 各模块内，本文 §7 只描述其行为规格。
> **曲线不计算**（决策 18）：18 个点就是数据，从预设/界面直配、原样下发；原曲线引擎（generic_curve）取消。

---

## 1. 目标与约束

| 目标 | 说明 |
|---|---|
| 前后端分离 | 业务逻辑（协议 / 数据模型）与界面渲染解耦，UI 不持有任何业务状态 |
| 协议/参数/预设外置 | IP、端口、报文字段、通道标识、工况预设全部外置（2 份 YAML） |
| 界面硬编码 | 布局 / 分组 / 按钮文案直接写在 `ui/*.py`（用户确认：永不通过配置改界面）；协议字段的 `zh/unit` 元数据留在 protocol.yaml 供界面引用。**显示精度不在配置里配**——统一由 `core/format.py:format_value` 决定（整值显整数、否则 2 位，小量保护 4 位） |
| 可单测 | `core/` 零 Qt 依赖，协议与数据可脱离界面单独跑测试 / CLI |

设计参照同组内已落地的 `BCLS_CZ_UI_Python_MoogStyle`（MoogStyle 版），取其成熟约定，但**不照搬全套**——Joystick 协议体量（单包 188B）远小于 CZ（892/1456/680 三包），过度设计反而是负担。

---

## 2. 技术选型

| 维度 | 选型 | 理由 |
|---|---|---|
| Qt 绑定 | **PyQt5** | 生态成熟、资料多 |
| 绘图 | **pyqtgraph** | OpenGL 加速，实时刷新无压力；标定曲线 = 18 点折线 + 圆点标记（`symbol='o'`） |
| 配置 | **YAML ×2**（协议 / 预设库） | 结构化、可注释、pyyaml 直接解析；`preset_store.py` 负责校验 / 原子写 |
| 算法 | **numpy** | 点表 / 数组处理（无曲线引擎，决策 18） |

---

## 3. 目录结构（目标形态）

```
pyqt_refactor/
├── config/                  # 配置层（协议 / 预设外置；界面不配置）
│   ├── protocol.yaml        # UDP 报文结构 + 网络 4 项 + 通道标识 + send 固定值（协议权威）
│   └── presets.yaml         # 预设库：每条 = 3 通道 ×（18 点 + 参数，报文原值）
├── core/                    # 业务逻辑层 —— 零 Qt 依赖
│   ├── config_loader.py     # 加载 protocol.yaml + 命令行覆盖
│   ├── packets.py           # 按 protocol.yaml 动态生成 struct 格式串 + send 值组装
│   ├── preset_store.py      # presets.yaml 读写（原子写/校验）
│   └── backend.py           # BackendService(QObject) —— 唯一后端入口
├── network/                 # 通信层
│   └── udp_manager.py       # 单 socket 收发 + 看门狗（连接指示，不门控发送）
├── ui/                      # 界面层 —— 硬编码，只渲染 + 上报意图
│   ├── main_window.py       # 装配 + 信号连接 + 状态栏
│   ├── preset_manager.py    # 上层预设页（新建 / 编辑 / 删除 / 下载）
│   ├── channel_tab.py       # 通道编辑页（参数 lineedit + 可编辑 18 点表 + 蓝字 + 「下载」）
│   ├── plot_controller.py   # pyqtgraph 封装 + 环形缓冲 + 动态游标
│   └── ip_bind_dialog.py    # IP 配置弹窗
├── assets/
│   └── style.qss            # 视觉样式（含蓝字脏标记样式，Python 只设 objectName / 动态属性）
└── main.py                  # 入口：加载配置 → 建 backend → 建 UI → exec
```

> generic_curve.py（曲线引擎）与 channels.yaml（工艺参数）已随决策 18 取消。

---

## 4. 分层与边界

```
        ┌─────────────────────────────────────────────┐
        │  ui/  (主线程，硬编码)                        │
        │   channel_tab · preset_manager · plot 等     │
        │   只渲染状态 + 调用 backend 的 slot 发命令     │
        └───────────────┬─────────────────┬───────────┘
                        │ Qt 信号(被动)    │ Qt 槽(主动命令)
                        ▼                  ▼
        ┌─────────────────────────────────────────────┐
        │  core/backend.py  BackendService(QObject)    │  ← 唯一后端边界
        │   编辑态/已下发态 · 预设 CRUD · 编排组包      │
        └───────┬───────────────────────────┬─────────┘
                │ 组包/预设                   │ 调度
                ▼                           ▼
        ┌──────────────────┐      ┌────────────────────┐
        │ core/packets     │      │ network/udp_manager │  (worker 线程)
        │ core/preset_store│      │  收包→emit 信号     │
        └──────────────────┘      │  发包(无条件直发)   │
                                  └────────────────────┘
```

**铁律**
- UI 层**绝不**直接碰 socket、struct、numpy、配置/预设文件 IO；只通过 `backend` 暴露的**信号**与**槽**。
- `core/`（config_loader / packets / preset_store）**零 Qt 依赖**，可 `python -m unittest` 直接测。
- 唯一线程边界：UDP 收包在 worker 线程，经 backend 的 Qt 信号跨线程投递到主线程 UI；UI 调 backend 槽也走 Qt 事件队列。

---

## 5. 前后端通信模型：BackendService(QObject) + Qt 信号

参照 CZ 的 `BackendService` 模式——后端继承 `QObject`，用 Qt 信号直连 UI，少一层抽象。

**接口形态（前后端分离的唯一边界）**：
- **后端 = 功能函数接口**：`BackendService` 的公开槽/方法就是后端 API（§5.2），前端只做"调用"，如 `backend.send_parameters(0)`、`backend.download_preset("breakout_light")`；UI 不持有任何业务状态，不碰 socket / struct / numpy / 文件 IO。
- **后端 → 前端 = 事件回调**：后端通过 Qt 信号（§5.1）把遥测、连断链、数据回灌（含脏标记）等事件推给界面，UI 只负责渲染。
- **跨线程安全**：前端调用的槽经 Qt 事件队列投递到后端所在线程执行（队列连接），前端不会被 UDP / 组包阻塞。
- **更底层的纯函数库**：`core/`（config_loader / packets / preset_store）是无 Qt 依赖的纯函数，BackendService 编排它们；单测和 CLI 直接调这一层，不经过 Qt。

### 5.1 后端 → UI（信号，被动）

| 信号 | 签名 | 触发时机 |
|---|---|---|
| `telemetry_received` | `(channels: dict[int, dict])` | 每收到一帧周期包 |
| `link_state_changed` | `(connected: bool, info: str)` | 看门狗判定连/断链 |
| `params_ack` | `(channel: int, ok: bool)` | 参数下发得到回执 / 超时 |
| `state_changed` | `(channel: int, field: str, value, dirty: bool)` | 某通道某字段在编辑态被改写（回灌 UI）；`dirty=True` 表示与已下发态不一致 → 界面显示**蓝字** |
| `points_changed` | `(channel: int, position[18], force[18], dirty: bool)` | 18 点表数据回灌（**编辑态**）；`dirty` 任一点与已下发态不同 → 表格蓝字；标定曲线按其即刷（决策 #24） |
| `control_mode_changed` | `(channel: int, mode: int, dirty: bool)` | 控制模式切换回灌；dirty 恒为 False（模式属于运行时标志，不写入预设） |
| `preset_list_changed` | `()` | presets.yaml 被增删改（UI 刷新预设列表） |
| `log_message` | `(level: str, text: str)` | 任意日志 |
| `error_occurred` | `(where: str, message: str)` | 异常（含 UDP 发送失败等） |

### 5.2 UI → 后端（槽，主动命令）

| 槽 | 签名 | 行为 |
|---|---|---|
| `send_parameters` | `(channel: int)` | **内层「下载」按钮**：编辑态提交为已下发态 → 直接发 182B（无条件，无差异也发）。若当前编辑的是**用户新建预设** → 同时把该通道完整数据（18 点+参数）回写 presets.yaml（出厂预设不回写，决策 17） |
| `set_packet_field` | `(channel: int, field: str, value)` | 编辑态提交（lineedit 输入完成 / 表格单元格改动 / 快捷按钮），**不下发**；回灌 `state_changed(dirty=…)` |
| `zero` | `(channel: int)` | 置校零脉冲：置位→发→清两帧（防控制器 latch）；点击即发 |
| `set_control_mode` | `(channel: int, mode: int)` | **控制模式**：0=OFF 1=抖杆 2=脉冲 3=倍脉冲 4=扫频 5=正弦 6=阶跃，点击即发，回灌 `control_mode_changed(ch, mode, dirty)`；非主机禁用。`channel` 参数保留以兼容未来扩展，**UI 固定传俯仰通道**（axis=1） |
| `load_preset` | `(channel: int, preset_id: str)` | 加载预设到**编辑态**（不发，标蓝），并记住当前编辑的预设 id（供内层「下载」判断是否回写）；内层「标准919数据·设置」按钮即此动作（`preset="state_1"`，状态1） |
| `download_preset` | `(preset_id: str)` | **外层「下载」按钮**：加载预设的俯仰+滚转数据 → 提交 + 两通道下发 + 回灌（黑色）；**不写预设文件**（决策 17） |
| `create_preset` | `()` | **新建**：免弹窗复制 模式6 综合力感 数据生成用户新预设（id 自动 `user_+时间戳`，决策 17/22）→ 原子重写 presets.yaml → 广播 `preset_list_changed` |
| `update_preset` | `(preset_id: str, data: dict)` | 修改预设条目 → 同上 |
| `delete_preset` | `(preset_id: str)` | 删除**用户新建**预设（UI 先弹确认；`builtin` 出厂预设后端拒绝，决策 17）→ 原子重写 presets.yaml → 广播 `preset_list_changed` |

**只读查询（UI 启动渲染用，不持有配置）**：

| 方法 | 签名 | 用途 |
|---|---|---|
| `channels` | `()` | 返回 `protocol.yaml` 的 `channel_ids` 列表（俯仰/滚转） |
| `send_fields` | `()` | 返回 send 结构体字段元数据 `[{name, type, count, unit, zh}]`，UI 渲染参数标签与单位 |
| `field_unit` | `(name, default="")` | 查某字段 unit（如 `friction→N`） |
| `get_presets` | `()` | 返回当前 presets 列表 |
| `get_editing_preset_id` | `()` | 当前编辑态关联的预设 id |
| `get_editing` / `get_sent` | `(channel: int)` | 取某通道编辑态 / 已下发态完整数据（调试用） |
| `is_host` | `()` | 当前「作为主机」状态 |

### 5.3 后端内部必须实现的三个机制（来自 CZ 的踩坑经验）

1. **无条件发送**：UDP 无连接，`_build_and_send` 始终直接 `sendto`；对端不在顶多丢包，不缓存、不门控。看门狗仅用于 UI 连接指示灯（连接/断开），不参与发送决策。
2. **参数脉冲**：校零 / 保存 / 恢复 / 写入类命令，采用「置位帧 → 发送 → 清零帧」两帧序列，避免控制器锁存（latch）。
3. **无条件下发**：`send_parameters` / `download_preset` 每次都直接发包，不做 diff 变化检测（与"无条件发送"一致，调试场景反复下载均需真实发出）。

### 5.4 编辑态 / 已下发态 与 蓝字脏标记（2026-09-08 确认）

后端每通道维护两份数据（9 个参数 + 18 点表），**颜色语义由此唯一推导**：

| 状态 | 含义 | 更新时机 |
|---|---|---|
| `editing_data` 编辑态 | 界面 lineedit + 18 点表显示的值 | 启动 = 状态1 数据（俯仰/滚转），基线全黑；输入完成 / 表格改动 / `load_preset` 时更新 |
| `sent_data` 已下发态 | 控制器当前生效值 | 「下载 / 预设下载」提交时 = 编辑态；**组包只从它取数**（校零脉冲、激振等所有 182B 均如此） |

- **蓝字规则**：单字段 `dirty = editing[field] != sent[field]`，经 `state_changed` / `points_changed` 回灌；UI：**dirty → 蓝色，一致 → 默认黑色**。目的：操作员始终知道"哪些改了没发、下发的是什么"。
- **范围**：9 个参数 lineedit（比例因子 / 弹簧力 / 阻尼分子 / 阻尼分母 / 摩擦力 / 负限位 / 启动力 / 正限位 / 力偏置，全是报文字段）+ 18 点表格（位置/力各格）。
- **控制类指令不受影响**：校零 / 激振 / 使能 / 反驱点击即发，无脏标记概念。
- **表格蓝字反映 vs 已下发态差异、标定曲线反映编辑态**：18 点单元格提交即回灌 `points_changed`，曲线按编辑态即刷（决策 #24，所见即所得）；下载后编辑态=已下发态，曲线与控制器一致。
- **不持久化**（用户确认"内层改的不保存到配置文件"）：编辑态不落盘；重启后编辑态 = default 出厂预设数据，全部黑色。
- **未连链时点「下载」**：照常提交并直接下发（UDP 无连接，对端不在顶多丢包）；连接状态由指示灯独立表达，两种信号不混用。

---

## 6. 配置与常量

### 6.1 protocol.yaml —— 协议与网络单一真相源

| 管什么 | 改了会不会碰协议 |
|---|---|
| 报文字段定义（structs）、包定义（packets）、网络 4 项（IP/端口）、**通道标识（channel_ids）** | **会**——协议与网络唯一真相源 |

- **network 段只有 4 项**（target_ip / target_port / local_ip / local_port，纯值无包装）。
- **channel_ids**：2 通道的报文标识常量（index / name / axis=1/2 / forceoffset），随通道固定，不随预设变。
- **send 包 6 个固定字段已移出协议层**（决策：预设=所有 UDP 发送参数，只有点击才发送）。scaling / tanhuang / zuni1 / zuni2 / showbili / rwa_nihe 现作为每通道 12 字段之一存于 `presets.yaml`（与 6 可变字段同通道），由预设提供、随 Download 下发；协议层不再有默认值兜底。⚠️ zuni2 是阻尼分母，不可为 0（决策 6，校验在 `preset_store.validate_channel_data`）。
- **单 socket 收发共用**（2026-09-08 确认）：本机只开一个 UDP socket 绑定 `local_port`，收周期回传与发参数包都走它；`target_ip:target_port` 是控制器端。两类报文键名：`recv`（周期回传帧）/ `send`（参数包）。
- **加载覆盖两层**（低→高）：YAML 默认值 → 命令行参数（`python main.py --target-ip 1.2.3.4`）。
- **运行时改网口（第三层，决策 25）**：窗口菜单栏「设置→网络绑定…」编辑 4 值 → `backend.apply_network` **立即重建 socket 生效**（本地先试绑、占用即拒），并**行级原子写回 protocol.yaml**（保留注释，重启仍生效）；等效于把命令行覆盖结果固化到磁盘。实现：`udp_manager.reconfig/probe_bind` + `config_loader.update_network_yaml/persist_network_file` + `ui/network_dialog.py`。

**UDP 行为常量硬编码在 `network/udp_manager.py`**（2026-09-08 确认不配置）：
- 看门狗：5.0s 无数据判断断链，0.5s 检查一次；
- 接收：`readyRead` 事件驱动，只保留最新帧（丢弃积压）；
- 发送：事件驱动单发（点下载/校零才发），`writeDatagram` 失败记 `error_occurred`，**无重试**。

**关键字段约定**：
- `packets.<包>.layout` 引用的结构体字段顺序 = **字节顺序权威**；字段增删 / 调序必须与控制器 C++ `struct` 同步，工具侧提供「实际字节数 vs 期望字节数」自检。
- send 包对应 C++ 同名结构体 `UDP_UI_Send_To_Controller_Parameter`：**不是分开发送、没有额外报文头**——整个 182B 一次发出，`axis = 1/2` 选通道，两通道共用。
- 字段自带 `{name, type, count, unit, zh}` 元数据：界面渲染时引用 `zh/unit`；`zh` 为空 = 内部字段（如 axis）。**显示精度不在此配置**——由 `core/format.py:format_value` 统一处理（整值→整数，非整值→2 位，小量<0.01→4 位保护）。
- 字段**不含 min/max**：参数合法范围由控制器 C++ 侧裁决。
- 曲线换算（curve_sources / curve 约定）已随决策 18 删除——数据即报文原值。

### 6.2 channels.yaml —— 已删除（决策 18）

原 12 工艺参数 / key_positions / 换算表全部作废：18 点与参数直接作为数据存进 presets.yaml 并由界面编辑。axis / forceoffset（通道标识常量）并入 protocol.yaml 的 channel_ids；原 send_defaults 的 6 固定字段现随预设下发（presets.yaml 每通道 12 字段，不再有协议层默认值）。

### 6.3 presets.yaml —— 预设库（出厂保护 + 用户可写，决策 17/18）

**每条预设（状态）= 俯仰(0) + 滚转(1) 两通道 × 完整数据（报文原值，无换算）**；脚蹬通道已整体移除（2026-09-09：协议、UI、测试全部同步为两通道，周期回传 16B）。pyyaml 直接解析，校验在 `core/preset_store.py`：

```yaml
presets:
  # ① 出厂模式：builtin: true —— 不可删除、下载不回写
  - id: state_1
    label: 模式1 摩擦力
    category: State
    builtin: true
    channels:
      0:                        # 俯仰
        friction: 4.0
        breakout_force: 2       # int，报文原值
        negative_stop: -2010.0  # 脉冲
        positive_stop: 2010.0
        scale_factor: 100
        spring_force: 200
        damping_num: 1
        damping_den: 10         # 阻尼分母，不可为 0（决策 6）
        force_offset: 905
        pos_pts:      [0.0, 2.0, ..., 18.5, 0.0, 2.0, ..., 18.5]  # 18 点（决策 21：正半 9 + 负半 9，均正绝对值，报文原值）
        force_pts:    [1.58, 3.5, ..., 31.81, ...]                # 18 点（同前：两半均为力幅值，正负可不对称，如滚转）
      1: {…}                    # 滚转（同上结构）

  # ② 用户新建：同样结构（id 自动 user_+时间戳，category: User）
```

7 个出厂模式（state_1..state_7）的点数据来自 `docs/配置.txt` 的真实标准数据。

**渲染排版（决策 23）**：`pos_pts`/`force_pts` 在文件中以 flow 书写并**按「正半 9 + 负半 9」折成两行**（正半 9 个一行、负半 9 个一行），与 UI 点表/报文逐位对应、可直接手改；YAML flow 序列换行合法，解析结果仍是 18 元素列表。

**交互语义**（决策 17）：

| 操作 | 出厂预设（builtin） | 用户新建 |
|---|---|---|
| 删除 | ❌ 禁用（后端拒绝） | ✅ 确认后写文件 |
| 上层 Edit | 加载到内层编辑器（标蓝不发送） | 同左 |
| 内层微调→下载 | 只发 UDP，不写文件 | 发 UDP + 当前通道完整数据回写文件 |
| 上层下载 | 加载 + 俯仰/滚转两通道发送，不写文件 | 同左 |

写文件动作 = **全量原子重写** presets.yaml（文件头注释保留，条目间手工注释会被冲掉），广播 `preset_list_changed`；UI 不直接碰文件。

### 6.4 配置恢复（仅打包层，决策 16）

代码层**不做**任何自动恢复：protocol.yaml / presets.yaml 缺失或损坏 → 启动明确报错。
唯一恢复机制 = PyInstaller 打包层：spec `datas` 把 `config/` 打进 exe（`sys._MEIPASS` 只读模板）；启动**逐文件**检查可写目录，缺/坏（先 `.bad` 留档）即从模板补齐。开发环境（未打包）无此层。实现放 main.py 启动段，阶段 5 落地。

### 6.5 UI 模块常量（硬编码）

| 模块 | 常量 |
|---|---|
| `main_window.py` | 窗口 1440×860；标题「BCLS 操纵上位机」；自上而下：**顶部蓝条**（返回预设 / 标题 / 连接灯 / 作为主机）+ **QStackedWidget 双层页面**（预设管理页↔编辑页）+ **底部灰框控制模式按钮组**；灰框只服务俯仰（axis=1） |
| `preset_manager.py` | 启动首页；左 `QTreeWidget` 按 category 分组（State→User），右固定 260px 按钮列（新建/编辑/删除/下载）+ 实时状态面板（两通道 Angle/Force） |
| `editor_page.py` | 两通道 `QTabWidget`（俯仰/滚转），每个 tab 内嵌 `ChannelPage`；切 tab 时刷新当前通道 |
| `channel_page.py` | 左右分栏：左侧力感参数 4 个 lineedit（friction / breakout_force / negative_stop / positive_stop）+ 18 点 QLineEdit 网格（位置/力，正负半区各 9 行）；右侧 pyqtgraph 标定曲线 + 实时遥测轨迹 + 操作按钮（清轨迹/自适应/存图/标定曲线开关） |
| `widgets/control_mode_box.py` | 底部灰框：6 个 checkable 按钮（抖杆/脉冲/倍脉冲/扫频/正弦/阶跃），同按钮再点 OFF，不同按钮直接切换 |
| `style.qss` | 蓝条 `#2f5d8a`、返回按钮透明白字、蓝字脏标记 `QLineEdit[dirty="true"] { color: #1565d8; font-weight: bold; }`、QTabWidget 与灰框样式 |

---

## 7. 界面行为规格（硬编码实现，本文只定行为）

### 7.1 通道编辑页（俯仰 / 滚转）

- 左侧参数面板（分组见 §6.5）+ 右侧曲线区；顶部两通道切换。
- 数值框统一规则：输入完成（editingFinished）→ `set_packet_field`；颜色由 `state_changed(dirty)` 回灌驱动（§5.4）。
- **18 点表格可编辑**：单元格改动 → `set_packet_field(Position[i] / LoadCellForce[i])`；渲染数据源 `points_changed`（编辑态），dirty 行/格蓝字；标定曲线随编辑态即刷（决策 #24）。
- 「校限」按钮 = 校零脉冲复用（同原 C++）。

### 7.2 预设管理页（Joystick，启动首页）

- 左列表（分组显示，User 分组为用户新建）+ 右按钮列（新建 / 编辑 / 删除 / 下载）+ 右下 Status 面板（两通道 Angle/Force 实时值，数据源 `telemetry_received`）。
- **新建**：免弹窗复制 模式6 综合力感 数据生成用户新预设（决策 17/22）；**编辑 / 双击**：加载到内层编辑器微调（记住编辑中的预设 id）；**删除**：确认框（出厂预设禁用）；**下载**：加载 + 两通道发送（不写文件）。
- 内层微调 → 内层「下载」：提交 + 发送；若编辑中的是**用户新建预设**，同时把当前通道完整数据回写 presets.yaml（出厂预设不回写）。

### 7.3 状态栏与主机模式（2026-09-09 修正）

- 左：连接指示灯（`link_state_changed` 驱动，绿"已连接" / 红"未连接"）；右：「作为主机」开关（默认开，后端 `_host` 默认 True）。
- **主机模式只影响「控制模式」按钮组的使能，不影响 UDP 参数包的正常发送**。关闭主机模式时，`set_control_mode` 直接返回（不发、不改状态）；其余参数编辑、内层/外层 Download、预设 CRUD、校零均不受影响。
- **主机标志位随 182B 参数包下发**：`protocol.yaml` 的 send 结构体 `host_mode(bool)` 字段，`build_send_values` 读取后端 `_host` 写入。C++ 控制器侧需同步字段顺序/大小。
- **控制模式字段**：原独立的 shaker/backdrive bool 已合并为单字节 `control_mode(int8)`，取值 0=OFF..6=阶跃。**控制模式按钮组（灰框）固定在主窗口最底部，且只服务俯仰通道**（axis=1，channel index 0）：点击任意模式按钮 → `backend.set_control_mode(pitch_index, mode)`，不随当前通道切换而改变。行为：同按钮再次点击 → OFF；不同按钮直接切换，不发 OFF。
- 后端仍保留 per-channel `set_control_mode(ch, mode)` API（`ch` 参数保留），以防后续甲方要求滚转也启用模式；UI 侧目前固定传俯仰。

| 模式 | 控制模式按钮组 | 参数编辑 | 内层/外层 Download | 预设新建/编辑/删除 |
|---|---|---|---|---|
| 主机（on） | ✅ 可用 | ✅ | ✅ | ✅ |
| 非主机（off） | ❌ 禁用 | ✅ | ✅ | ✅ |

### 7.4 主窗口双层布局（2026-09-09 确认）

```
┌────────────────────────────────────────────────────────────┐
│ [蓝条] ←返回预设管理 │ 标题 │ [指示灯][已连接] │ 作为主机 ☑ │
├────────────────────────────────────────────────────────────┤
│  QStackedWidget                                             │
│    页0 PresetManagerPage（启动首页）                         │
│    页1 EditorPage（俯仰/滚转 两 tab）                   │
├────────────────────────────────────────────────────────────┤
│ [灰框] 抖杆 脉冲 倍脉冲 扫频 正弦 阶跃（只操作俯仰 axis=1）   │
└────────────────────────────────────────────────────────────┘
```

- **启动默认在预设管理页**；Edit/双击/新建后切到编辑页。
- **返回按钮**在编辑页可见，点击切回预设管理页。
- **蓝条网络状态**：`link_state_changed` 驱动指示灯与文字；断开时灯灰，连接时灯绿。
- **灰框永远绑定俯仰通道**，不随当前 tab 改变；只有俯仰有抖杆需求。

---

## 8. UDP 报文契约

| 包 | 方向 | 大小 | 结构 |
|---|---|---|---|
| `send` | UI → 控制器 | **182 B** | 单通道参数包，`axis` 字段指定通道（1/2） |
| `recv` | 控制器 → UI | **16 B** | 2 通道 × 8 B（Position `float` + LoadCellForce `float`） |

`send` 包 = **单一结构体**（对应 C++ `UDP_UI_Send_To_Controller_Parameter`，`#pragma pack(push, 1)` 小端）整体一次发出——没有独立报文头，`axis` 字段 = 通道号 1/2，两通道共用同一结构。字节构成：

```
host_mode(bool) + axis(int8) + zero_calib(bool) + control_mode(int8)        =   4 B
pos_pts[18](float) + force_pts[18](float)                                   = 144 B
scale_factor(int16)                                                         =   2 B
friction(float) + breakout_force(int32) + spring_force(int32)
    + damping_num(int32) + damping_den(int32)
    + negative_stop(float) + positive_stop(float) + force_offset(int32)     =  32 B
                                                                  合计 = 182 B
```

> `struct` 格式串**禁止手写**，由 `packets.py` 按字段 `type` 在运行时生成；类型映射：`int8→b, int16→h, int32→i, float→f, bool→?`，字节序 `<`。

---

## 9. 标定曲线绘制约定（决策 18 + 决策 21）

- **标准曲线 = 18 个点折线相连**（polyline），每个点用**圆圈标记**（pyqtgraph `symbol='o'`）。
- 数据源：当前通道的**已下发态** 18 点；随 `points_changed` 推送刷新。
- **18 点语义（决策 21，2026-09-09）**：存储/报文/lineedit 全部为**正绝对值**——前 9 点正方向（位置 0→+max、力 0→+Fmax）、后 9 点负方向（|位置| 0→max、力幅 0→Fmax），两半各自从中位出发升序；正负力幅可不对称（配置.txt 原样）。
- **绘图还原（决策 21）**：`core/curve.signed_curve` 把负半 9 点位置/力**取负并反转**（进入第三象限、x 从 -max 单调升到 0），再拼接正半（0→+max）；两半首点都在中位 pos≈0（力 +F0 / -F0）→ 相邻即连成原点**启动力竖线**。整条折线从 (-max,-Fmax) 连续走到 (+max,+Fmax)，**无 18.5↔-18.5 横跨假线**。
- 不再做任何曲线拟合 / 理论曲线计算（原 Generic 模型、ExtractKeyPoints、回滞环等概念随决策 18 废弃）。

---

## 10. 关键设计决策（对照 CZ 取舍）

| 决策 | 来源 | 说明 |
|---|---|---|
| 参数不定义最大最小值 | 本次决策 | 范围合法性由控制器 C++ 侧裁决，UI 配置不含 min/max |
| 无条件发送（无门控） | CZ 经验修正 | UDP 无连接，`sendto` 不阻塞；看门狗仅作连接指示 |
| 参数脉冲两帧 | CZ | 校零 / 保存 / 恢复 / 写入防 latch |
| 无条件下发 | CZ + 本次 | 下载每次都直接发包，不做 diff 变化检测（调试场景反复下载均需真实发出） |
| **预设库 CRUD + YAML 存储** | **修订（2026-09-08）** | 界面 新建/编辑/删除/下载；存储 `config/presets.yaml` |
| **出厂/用户预设分级** | **新增（2026-09-08，决策 17）** | `builtin` 出厂项不可删、下载不回写文件；用户新建项可删、内层下载回写通道数据 |
| **预设直配 18 点，曲线不计算** | **新增（2026-09-08，决策 18）** | 每条预设 = 2 通道 ×（18 点+参数，报文原值）；generic_curve / channels.yaml / 换算表全部取消；标定曲线 = 18 点折线+圆点 |
| **内层蓝字脏标记 + 显式「下载」下发** | **新增（2026-09-08）** | 双状态模型（编辑态/已下发态），改=蓝、下载=黑；表格与 lineedit 同规则 |
| **内层改动不持久化** | **新增（2026-09-08）** | 重启编辑态 = default 出厂预设数据，全黑 |
| **移除 ui.yaml，界面硬编码** | **修订（2026-09-08）** | 界面永不通过配置修改，数值收编为 `ui/` 模块常量（§6.5） |
| **配置恢复仅打包层（`_MEIPASS` datas）** | **修订（2026-09-08，决策 16）** | 代码层无自动恢复，配置缺失/损坏明确报错；打包后启动逐文件从 exe 内置模板补齐 |
| Breakout / forceoffset 按字段名取值 | 本次决策（2026-09） | 原版 C++ p7/p8 显示与发送字段错位视为笔误，不照抄；forceoffset 为通道常量（protocol.yaml channel_ids） |
| 样式进 `style.qss` | CZ | Python 只设 objectName / 动态属性（含蓝字脏标记） |
| 不配置通道数 / 通道类型 | 本次决策 | 固定 2 通道（俯仰/滚转）由 channel_ids 推导（决策 20 删脚蹬） |
| 权限门控 / i18n | **不采纳** | Joystick 无中英切换概念（主机模式开关保留，见 §7.3） |

> 已废弃：决策 1（正负方向顺序约定）、决策 3（空行程快捷按钮）、决策 5（18 点表只读自动计算）、"预设在基准上叠加（scale/override）"——均被决策 18 取代（详见 PROCESS.md）。

---

## 11. 实现阶段建议（里程碑，非代码）

1. ✅ `core/config_loader` + `packets` + `preset_store` 自检 → 182B / 16B 字节对齐 + 预设读写往返一致（已完成，56 用例）。
2. `core/backend` + `network/udp_manager` → 离屏跑通收发 + 看门狗 + 双状态/脏标记/预设 CRUD。
3. `ui/*`（硬编码）→ 先 `main.py --no-udp` 看界面，再 Wireshark 比对 182B 下发包字节序（唯一未验证环节）。
4. 联调前：presets.yaml 出厂 18 点数据已替换为 `docs/配置.txt` 真实标准数据（state_1..state_7）；PyInstaller 打包（datas 模板 + 启动补齐，决策 16）。

> **联调前必做**：用 Wireshark 比对一次 182B 下发包的字节序，确认与控制器 C++ `struct` 完全一致（含新增 `host` 位）。
