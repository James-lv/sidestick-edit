# BCLS Joystick PyQt 重构 — 过程记录（PROCESS）

> **本文件用途**：记录项目推进过程中的需求讨论、已定决策、原版 C++ 关键对照信息和实施进度。
> **下次继续干之前先读这个文件**，再看同目录 `ARCHITECTURE.md`（设计权威）和 `../config/`（配置权威：protocol.yaml / channels.yaml / presets.yaml）。
> 最后更新：2026-09-09

---

## 1. 项目是什么

把上级目录的 Qt C++ 上位机（`BCLS_JoystickV0.9.8/*.cpp`，Qt5 + QCustomPlot）重构为 Python/PyQt5 版本：

- **原版功能**：三通道（俯仰/滚转/脚蹬）操纵力模拟上位机。配置力-位移曲线参数 → 组 188B UDP 参数包发给控制器；收控制器 24B 周期回传（位置+力）画实时曲线。
- **重构目标**：按 `ARCHITECTURE.md` 的分层架构（UI 硬编码 / BackendService / core 纯函数 / UDP 单 socket）。配置只留会改的：`protocol.yaml`（UDP 结构+网络+通道标识+固定值）、`presets.yaml`（预设库：每条 = 3 通道 × 18 点+参数，报文原值直配，**曲线不计算**——决策 18）。
- **参考项目**：同组 `BCLS_CZ_UI_Python_MoogStyle` 的 BackendService 模式（只借鉴约定，不照搬）。

### 文件对照（原 C++ → 重构）

| 原 C++ 文件 | 内容 | 重构落点 |
|---|---|---|
| `CommunicationPackets.h` | 187B/24B 结构体（**协议权威**）、controlParams 三通道常量 | `config/protocol.yaml`（axis/forceoffset 进 channel_ids 段） |
| `generic.cpp/.h` | 力-位移曲线算法 + 18 点拟合表提取 | ❌ 不再重构（决策 18：曲线不计算，18 点直配） |
| `mainwindow.cpp` | UDP 收发、按钮逻辑、QSettings 持久化 | `core/backend.py` + `network/udp_manager.py` |
| `channel_plot_controller.cpp` | 实时曲线、游标、环形缓冲 | `ui/plot_controller.py`（换 pyqtgraph） |
| `newwindow` | IP/端口绑定弹窗 | `ui/ip_bind_dialog.py` |
| `dem/` 图片资源 | logo、LED 灯、bluesky 图标 | ✅ 已拷入 `assets/` |

### 关键数值（联调速查）

- 端口：本机 9200（**单 socket 收发共用**）/ 控制器收包 9300；看门狗 **5s** 无数据判断链
- 182B 包（新顺序/字段名，C++ 需同步）：`host_mode(bool)+axis(int8)+zero_calib(bool)+control_mode(int8)` 4B → `pos_pts[18]+force_pts[18]`(float×36) 144B → `scale_factor(int16)` 2B → `friction(float)+breakout_force(int32)+spring_force(int32)+damping_num(int32)+damping_den(int32)+negative_stop(float)+positive_stop(float)+force_offset(int32)` 32B（host 为新增主机标志位）
- 限位/18 点/参数全部直接存**报文原值**，无换算（决策 18；参考系数 deg→脉冲 ×108.695652 仅手工换算时用）
- axis 字段：俯仰=1 / 滚转=2 / 脚蹬=3（protocol.yaml channel_ids 索引 0/1/2）
- force_offset 初值：240 / 290 / 35（俯仰/滚转/脚蹬），**有死区时归零**
- 控制模式仅俯仰有效：底部灰框固定 axis=1 下发；后端 `set_control_mode(ch, mode)` 仍保留 `ch` 参数，UI 侧固定传俯仰 index 0

---

## 2. 当前进度（2026-09-09）

| 事项 | 状态 |
|---|---|
| 通读原 C++ 全部核心代码 | ✅ 完成 |
| 配置审查 + 修订定稿 | ✅ 完成（修订项见 §3） |
| ARCHITECTURE.md 与讨论结论同步 | ✅ 完成 |
| 需求修订（2026-09-08）：预设库改 CRUD + YAML 存储（presets.yaml）；**删除 ui.yaml**（界面硬编码）；内层 lineedit **蓝字脏标记** + 「下载」显式下发 | ✅ 完成 |
| 配置体系修订（2026-09-08，决策 13–16）：network 瘦身为 4 项、报文键改 send/recv、structs 拍平对齐 C++、defaults/curve_sources/curve 移入 channels.yaml、出厂自恢复仅 presets.yaml、打包 datas 模板机制 | ✅ 完成 |
| 阶段 0：requirements.txt / 拷 `dem/` 图标到 assets/ / style.qss 骨架（含蓝字脏样式） | ✅ 完成（2026-09-08） |
| 阶段 1：core/config_loader.py + packets.py + preset_store.py + `python -m core.selfcheck` | ✅ 完成（2026-09-08，自检全绿；偏移表与 C++ struct 逐字段核对一致） |
| 单元测试 tests/（config_loader / packets / preset_store / selfcheck 集成） | ✅ 完成（2026-09-08，53 用例） |
| 配置模型重构（2026-09-08，决策 18）：**曲线不计算**，预设直配 18 点+参数；channels.yaml 删除（axis/forceoffset 并入 protocol.yaml）；内层 lineedit 只留 4 个报文字段；标定曲线 = 18 点折线+圆点 | ✅ 完成 |
| 预设分级补充（2026-09-08，决策 19）：预设只含俯仰+滚转（出厂 6 状态），脚蹬固定一份独立数据不随预设变化 | ✅ 完成 |
| 协议字段精修（2026-09-09）：删除 decimals；send_defaults 删除；重命名为 pos_pts/force_pts + 新顺序；合并 shaker/backdrive 为 control_mode(int8) | ✅ 完成 |
| 主窗口骨架（2026-09-09）：`ui/main_window.py` + `main.py` 入口；底部灰框固定贴底；控制模式仅俯仰 axis=1 | ✅ 完成（测试 31 用例 + 新主窗口冒烟 2 用例） |
| ~~阶段 2：generic_curve.py + 单测~~ | ❌ 取消（决策 18） |

环境实测：Windows 11 + Python 3.8.10（PyQt5 / pyqtgraph / numpy / pyyaml 均可导入）。注意代码须兼容 3.8 语法。

`pyqt_refactor/` 现有：`config/{protocol.yaml, presets.yaml}` + `docs/` + `assets/`（图标 + style.qss）+ `core/{__init__, backend, config_loader, format, packets, preset_store, selfcheck}.py` + `network/udp_manager.py` + `ui/{main_window.py, editor_page.py, channel_page.py, preset_manager.py, widgets/control_mode_box.py}` + `main.py` + `tests/`（10 个测试文件，93 用例）。

测试运行：

```bash
# 推荐（指定 top-level 为项目根目录，确保 tests 包正确加载）
python -m unittest discover -s tests -t .

# 中文输出不乱码
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -t .
```

---

## 3. 已定决策清单（2026-09-07 与需求人逐条确认）

1. ~~**拟合表正负方向顺序**~~：❌ 废弃（决策 18：18 点直接配置，无提取算法；现占位数据仍按 0–8 正 / 9–17 负排列）。
2. **Breakout / forceoffset 按字段名取值**：`Breakout = round(BreakoutLevel)`，`forceoffset = 通道力偏移（有死区归零）`。原版 C++ 把 p7 输入框（自动填了力偏移 240/290/35）当 Breakout 发送、p8 才发 forceoffset，**判定为原版笔误**，不照抄。
3. ~~**空行程快捷按钮**~~：❌ 废弃（决策 18：空行程 CableDeadband 是纯计算参数、不进报文，曲线不计算后无意义，随内层面板精简删除）。
4. ~~**抖杆 + 反驱按钮都保留**~~：❌ 废弃（2026-09-09 修订：合并为单字节 `control_mode` 控制模式字段，0=OFF/1=抖杆/2=脉冲/3=倍脉冲/4=扫频/5=正弦/6=阶跃；底部灰框放置六个模式按钮，同按钮再次点击 → OFF，不同按钮直接切换，非主机模式禁用）。
5. ~~**18 点拟合表只读 + 自动计算**~~：❌ 废弃（决策 18：表格改为**可编辑**的直接数据源，随预设存储与下发，无任何推导）。
6. **tanhuang / zuni1 / zuni2 / scaling / showbili 暂无界面入口**：按 `channels.yaml` 的 `send_fixed` 段固定值下发（scaling=100, tanhuang=0, zuni1=0, zuni2=1, showbili=1.0, rwa_nihe=true）。⚠️ zuni2 是阻尼分母、scaling/showbili 是缩放系数，**不可初始化为 0**。
7. **上层只做 Joystick 预设管理页**（landing page）——**2026-09-08 修订：预设库可增删改，不再只读**：
   - 界面按钮：**新建 / 编辑 / 删除 / 下载**。
   - **下载** = 把该预设计算后的完整参数（12 参数 × 3 通道）加载到内层 lineedit 显示（黑色），**同时** UDP 下发三通道到控制器；之后可进内层微调。
   - **新建 / 编辑** = 弹窗修改预设条目本身（label / category / description / scale / override，id 唯一；新建从 initial_parameters 基准预填）；**删除** = 确认后删条目。增删改全量**原子重写** `config/presets.yaml`。（交互方式后被决策 17 细化：Edit 改为加载到内层微调，不再弹窗改条目）
   - **存储格式用 YAML**（`config/presets.yaml`，2026-09-08 二次修订：先改 txt、当日又改回 YAML）：结构化、pyyaml 直接解析、免自写解析器；预设段已从 channels.yaml 移出。注意界面增删改是全量重写，会冲掉条目间的手工注释（文件头注释保留）。
   - ~~计算规则 override/scale~~：❌ 被决策 18 取代——预设直接存每通道完整数据（18 点+参数，报文原值），出厂与用户条目结构一致，无叠加计算。
8. **前后端分离 = 后端函数接口 + 前端调用**：`BackendService` 的公开槽就是后端 API（`send_parameters / set_packet_field / zero / set_control_mode / load_preset / download_preset / create_preset / update_preset / delete_preset`，详见 ARCHITECTURE §5.2），前端只调用；后端用 Qt 信号推事件（遥测/连断链/回灌含脏标记/控制模式/日志）；UI 不持有业务状态、不碰 socket/struct/numpy；`core/` 是零 Qt 纯函数库。
9. **原版行为的有意修复**（重构与原版不同，是故意的）：
   - 接收 socket 绑 `local_ip`（原版错绑到目标 IP）；
   - shark/control 改为每通道独立状态（原版三通道共享一个实例）；
   - 曲线方向推导无状态化（原版 `m_lastPosition/m_direction` 跨调用，结果不可复现）。
10. **内层参数蓝字脏标记 + 「下载」显式下发**（2026-09-08 新增）：
    - 内层可编辑数值框（参数设置：比例因子 / 弹簧力 / 阻尼分子 / 阻尼分母 / 摩擦力 / 负限位 / 启动力 / 正限位 / 力偏置）：修改后文字变**蓝色** = 已改未下发；点内层「**下载**」按钮 → 提交 + 下发 182B → 恢复**黑色** = 已下发。操作员始终知道下发的是什么。
    - 依据：原 C++ 本来就是"改输入框不发、点按钮才发"（mainwindow.cpp 所有按钮 → `setparm` → `send_udp`），本决策只是给该行为加视觉标记。
    - **双状态模型**：后端每通道维护 `editing_params`（界面显示）与 `sent_params`（已下发，**组包只从它取数**）；`dirty = 两者不等`，由 `state_changed(…, dirty)` 回灌驱动颜色。
    - 快捷按钮（左右1deg/0.5deg）只写字段值并标蓝，**不再立即发送**（原版立即发，有意变更）。
    - 校零 / 激振 / 使能 / 反驱为控制类指令，点击即发，不受脏标记影响。
    - 拟合表 + 理论曲线只反映**已下发**参数：点「下载」时重算刷新，输入过程不刷新。
    - **内层改动不持久化**（用户确认"改的不保存到配置文件"）：取消 runtime/channel_params.yaml；重启后编辑态 = channels.yaml 的 initial_parameters，全部黑色。
    - 未连链时点「下载」：照常提交并直接下发，UDP 无连接对端不在顶多丢包；链路状态由指示灯独立表达。
11. **删除 ui.yaml，界面硬编码**（2026-09-08 确认）：用户明确以后不需要通过配置改界面，界面结构 / 布局 / 按钮文案直接写在 `ui/*.py` 模块内；原 ui.yaml 的数值收编为模块常量（清单见 ARCHITECTURE §6.4）。保留的配置 = protocol.yaml + channels.yaml + presets.yaml。
12. ~~**配置自恢复（内置出厂表）**~~：❌ 被决策 16 取代——代码层**不做任何恢复**，所有配置文件（protocol.yaml / presets.yaml）缺失/损坏启动时明确报错；唯一恢复机制 = 打包层的 `_MEIPASS` datas 模板逐文件补齐（2026-09-08 与用户再确认）。
13. **网络配置瘦身**（2026-09-08 确认）：protocol.yaml 的 network 段只留 **4 项**（target_ip / target_port / local_ip / local_port，纯值、无环境变量包装）；删除 reserved 端口提示、rx_buffer、socket_timeout、合帧开关、**retry / send_last_frame_on_stop（CZ 周期连发遗留概念，本项目发送是事件驱动单发）**；看门狗 5s/0.5s、只留最新帧等行为常量硬编码在 `network/udp_manager.py`。覆盖层减为两层：YAML → 命令行。
14. **单 socket 收发共用 + 端口命名对齐原版**（2026-09-08 确认）：本机只开**一个** UDP socket，绑定 `local_port`，收周期回传与发参数包共用（原 C++ 是两个 socket：读口绑 9200、发口不绑定随机源端口，重构简化为单 socket）；`remote_port` 更名 `target_port`（对齐原 C++ 的 Target_port）。澄清：原版注释的 `PORT1/PORT2` 叫法弃用，配置里两类报文直接叫 `recv`（周期回传）/ `send`（参数下发）；整个 188B 单包发出、axis=1/2/3 选通道，无独立报文头。
15. **defaults / curve_sources 移出 protocol.yaml，归入 channels.yaml**（2026-09-08 确认）：protocol.yaml 只剩 network / structs 两段（纯 UDP 结构与网络）；send 包固定字段 → channels.yaml `send_fixed` 段，工艺参数→报文字段换算（deg→脉冲 ×108.695652、Breakout 四舍五入）→ channels.yaml `curve_sources` 段，曲线约定（sign_convention / enable_cable_stiffness）→ channels.yaml `curve` 段；组包统一走 `packets.build_send_values(...)`。（其中 curve_sources / curve 两段又被决策 18 删除——无换算、无曲线约定；send_fixed 移入 protocol.yaml 的 send_defaults 段，因 channels.yaml 已删）（**send_defaults 段已于 2026-09-09 删除**：6 固定字段改随 presets.yaml 每通道 12 字段下发，协议层不再有默认值兜底——见 ARCHITECTURE §7 相关段落）
16. **打包部署的配置模板机制**（2026-09-08 采纳用户既有方案）：PyInstaller spec `datas` 把 `config/` 打进 exe（运行时解压到 `sys._MEIPASS`，只读、每次全新，相当于出厂模板）；启动时**逐文件**检查可写目录（exe 旁）：缺哪个补哪个（比整目录 copytree 粒度细），损坏 → `*.bad` 留档后补模板。开发环境（未打包）无此层：presets.yaml 走内置出厂表，两份主 YAML 缺失报错。实现放 main.py 启动段，阶段 5 打包时落地。
17. **出厂/用户预设分级**（2026-09-08 确认，细化决策 7 的交互）：
    - 12 条出厂预设带 `builtin: true`：**不可删除**；上层 Edit = 加载到内层编辑器微调（标蓝、不发送），内层「下载」只发 UDP **不回写文件**——出厂定义恒定。
    - 上层「新建」= 免弹窗直接生成一份默认参数的用户新预设（id 自动 `user_+时间戳`、label「新建预设N」、category=User），**可编辑可删除**。
    - 用户新建预设按**通道快照**存数据（结构后被决策 18 调整为完整 18 点+参数）；内层「下载」= 提交 + 发送 + **把当前通道数据写回该预设快照**（全量原子重写 presets.yaml）。
    - 上层「下载」= 加载预设 + 三通道发送，不写文件；「删除」仅用户预设可用（出厂项按钮禁用，后端 delete_preset 遇 builtin 拒绝）。
18. **预设直配 18 点，曲线不计算**（2026-09-08 确认，2026-09-09 UI 改 9 参数）：
    - 18 个点（Position[18] + LoadCellForce[18]）与 9 个参数（比例因子 / 弹簧力 / 阻尼分子 / 阻尼分母 / 摩擦力 / 负限位 / 启动力 / 正限位 / 力偏置）**直接作为数据**存进预设并原样下发，不做任何曲线拟合/提取计算。
    - 每条预设 = 3 通道 × 完整数据（报文原值）；channels.yaml 删除，axis/forceoffset 并入 protocol.yaml 的 channel_ids 段。原 send_defaults 的 6 固定字段（scaling/tanhuang/zuni1/zuni2/showbili/rwa_nihe）不再单独成段，随每通道 11 字段存于 presets.yaml。
    - 内层面板分两组：上组「参数设置」两列 9 参数（阻尼分子/分母同格）+ 下组「力感参数」18 点表格；空行程/力梯度等纯计算参数删除。
    - 标定曲线绘制 = 18 点折线 + 圆圈标记，无理论曲线。
    - ⚠️ 出厂预设当前为**占位数据**（线性坡），联调前替换为真实标准数据。
19. **预设 = 俯仰+滚转两通道，脚蹬固定**（2026-09-08 确认）：
    - 每条预设（状态）只含**俯仰(0) + 滚转(1)** 两个通道的 18 点+参数；出厂 6 个状态 state_1..state_6（占位数据）。
    - **脚蹬不随状态变化**：presets.yaml 顶层独立 `pedal:` 段存一份固定数据；切换/下载任何预设都不改变脚蹬，外层下载只发俯仰+滚转两通道。
    - 脚蹬仅在脚蹬页自己点「下载/校零」时按 pedal 数据（或本次会话微调值）下发；微调不持久化（同决策 10）。
    - 启动基线与「新建」复制源 = 状态1（俯仰/滚转）+ pedal 段（脚蹬）。
20. **删除脚蹬通道，系统收敛为两通道**（2026-09-09，撤销决策 19 的 pedal「半挂」设计）：
    - **脚蹬整体移除**：不再有脚蹬 tab、脚蹬数据与 axis=3。控制器固件同步改为**周期回传 2 通道 16B**（每通道 8B × 2）。
    - presets.yaml：删除顶层 `pedal:` 段，`presets:` 提升为顶层键；`preset_store` 的 load/parse/render/save 全部**去 pedal 参数**（单值返回预设列表）。
    - protocol.yaml：channel_ids 剩 2 项（俯仰 axis=1 forceoffset=240 / 滚转 axis=2 forceoffset=290）；backend 初始化、组包、周期帧解析全部由 `channel_ids` 驱动，无任何硬编码 3 通道。
    - UI 无需逻辑改动（tab/Status 面板本就由 channels() 驱动），仅同步 docstring/注释；tests 改为 2 tab / 16B / axis=1/2。
    - 架构文档同步：ARCHITECTURE.md 现状描述、overview.md、style.qss 注释。
21. **18 点统一为正绝对值存储 + 绘图按半取负还原**（2026-09-09，用户确认；修正决策 18 重建脚本把负半存成「-max→0 带符号位置 + 力降序」的偏差）：
    - **存储/报文/lineedit 语义**：pos_pts / force_pts 各 18 点一律**正绝对值**——前 9 点正方向（位置 0→+max、力 0→+Fmax），后 9 点负方向（|位置| 0→max、力幅 0→Fmax），两半各自从中位出发、段内升序；正负力幅可不对称（按 docs/配置.txt 逐字，如滚转负半最大 17 vs 正半 28.91）。协议注释「先发正方向9点，再发负方向9点，均为绝对值」本就如此，本轮把 presets.yaml 7×2 通道的 18 点按配置.txt 重排回全正（旧文件负半带 -18.5 等负号，已清零）。
    - **绘图还原**：新建 `core/curve.py::signed_curve`——负半 9 点位置/力**取负并反转**（x 从 -max 单调升到 0、进入第三象限），拼接正半（0→+max）；两半首点都在中位 pos≈0（力 +F0 / -F0）→ 相邻两点即连成原点**启动力竖线**。整条折线从 (-max,-Fmax) 连续走到 (+max,+Fmax)，**不再有 18.5↔-18.5 横跨假线**。`ui/channel_page._update_calib` 改用该函数（纯函数零 Qt，可单测）。
    - 传输与 lineedit 不动（本来就按绝对值直显/直发）；新增 tests/test_curve.py 5 用例（单调性/第三象限/中点竖连/滚转不对称/入参不改写）。
    - 验证：**96 用例全绿**；selfcheck send=182B / recv=16B / 预设往返一致。
22. **新建预设默认模板改为 模式6 综合力感**（2026-09-09，用户要求）：上层「新建」的复制源从 模式1 改为 **state_6**（模式6 综合力感——摩擦、启动力、非线性梯度与硬限制组合，7 个出厂模式中要素最全的默认曲线）。
    - backend.py：常量拆分为 `STARTUP_PRESET_ID="state_1"`（启动基线，不变）与新增 `NEW_PRESET_SOURCE_ID="state_6"`（新建复制源）；`create_preset` 改查后者并更新 docstring/错误消息。
    - 同步注释：preset_store.py / preset_manager.py / ARCHITECTURE.md（§5 API 表 create_preset 签名 `(data:dict)`→`()` 一并更正 + §7 预设页行为）。
    - 测试：test_backend 新增断言「新建条目 channels 深等于 state_6 channels」；test_backend **15 用例全绿**。
23. **presets.yaml 18 点表改「9+9 flow 折行」排版，便于手改**（2026-09-09，用户要求）：原 block 风格每值一行 → 全文件 723 行难读难改。
    - `render_presets` 改用自定义 `_PresetDumper`（纯数值列表压成 flow 行，容器保持 block 展开）+ `_fold_18pt_lines` 把 `pos_pts`/`force_pts` 折成**两行：正半 9 个一行、负半 9 个一行**（YAML flow 逗号后换行合法，解析结果不变）。
    - 文件头 `_HEADER` 补排版说明；`config/presets.yaml` 已重写：**723 行 → 249 行**，每通道点表 4 行（正位/负位/正力/负力）。
    - 验证：7 预设 render→parse 逐一相等（roundtrip）；test_preset_store **20 用例全绿**。
24. **标定曲线随编辑态 18 点即刷（所见即所得），不等下载**（2026-09-09，用户要求）：原曲线固定画「已下发态 sent」，单点编辑只改 editing、无信号回灌，必须下载后才变。
    - channel_page 三处改为按编辑态画曲线：`refresh()` 传 `editing`；`_on_points_changed` 信号本携带编辑态 18 点 → 直接画入参；`_submit_point` 单点提交后本地取 `get_editing` 立即重绘。
    - 蓝字语义不变（仍对比已下发态）；下载后 editing==sent，曲线与控制器一致。
    - ARCHITECTURE.md §5.3 信号表 / §5.4 / §7 数据源描述同步（"已下发态"→"编辑态，曲线即刷"）。
25. **补回原版「设置→网络绑定…」菜单栏，运行时改 IP/端口并持久化**（2026-09-09，用户问"原版有菜单栏设置能绑 IP 为啥没有"后确认补回）：
    - 背景：重构早期把网络归为启动配置（protocol.yaml network 段 + `--target-ip` 命令行），UI 顶栏只有「网络连接」指示灯（纯展示），**丢了原版 C++ 运行时改网口的能力**。
    - `config_loader` 新增 `update_network_yaml`/`persist_network_file`：**行级替换** network 段 4 值（保留注释/引号风格/第 17 列对齐），写前 safe_load + 端口校验，不落盘坏 YAML；原子写（.tmp + os.replace）。
    - `udp_manager` 新增 `reconfig`（停旧线程→换址→重启绑定，先 emit link False 复位灯）与 `probe_bind` 静态试绑（同步探测占用，不占端口）。
    - `backend.apply_network(values)→(ok,msg)`：local 变更才试绑（未变时当前 socket 正占端口）→ reconfig 立即生效 → 内存 bundle 与磁盘 protocol.yaml 同步；`--no-udp` 下拒绝。
    - UI：QMainWindow 菜单栏「设置→网络绑定…」→ `ui/network_dialog.py`（本机绑定/控制器两组 4 字段，IPv4+端口校验，失败 QMessageBox 保留对话框）；qss 补 QMenuBar/QMenu/QDialog 蓝系样式；main_window 布局注释加菜单栏行。
    - 验证：config_loader 4 用例 + udp probe 2 用例 + backend 集成 2 用例（真 UDP 回环：改 target 后新端口收到 182B、旧端口不再收、磁盘重载值正确、占用端口被拒）新增全过；**104 用例全绿**（96+8）；selfcheck 全通过。

---

## 4. 实施计划（五阶段，未动工）

| 阶段 | 内容 | 验收标准 | 状态 |
|---|---|---|---|
| 0 | 配置定稿（protocol.yaml / presets.yaml，ui.yaml 已删）+ `requirements.txt`（PyQt5/pyqtgraph/numpy/pyyaml）+ 拷 `dem/` 图标到 `assets/` + 建 `style.qss` | 配置与本文档决策一致 | ✅ |
| 1 | `core/config_loader.py` + `core/packets.py` + `core/preset_store.py` | `--selfcheck` 输出逐字段偏移表，断言 send=182B / recv=16B；预设读写往返一致 | ✅（2026-09-08 自检全绿；09-09 随脚蹬删除改为 16B） |
| 2 | `core/generic_curve.py` + 单测（零 Qt） | 回滞环宽度=2×摩擦；与 C++ 公式黄金值逐点一致；18 点表等价 `ExtractKeyPoints` | ❌ 取消（决策 18：曲线不计算） |
| 3 | `network/udp_manager.py` + `core/backend.py`（信号槽、两帧脉冲、无条件发送、双状态脏标记、预设 CRUD、控制模式 int8） | 无 UI 环回脚本验证连断链/无条件发送/脉冲/蓝字 dirty 推导 | ✅ |
| 4 | `ui/`：main_window（蓝条+双层页+灰框）+ preset_manager + editor_page + channel_page + style.qss + main.py | 界面全流程可走通，offscreen 冒烟截图验证布局；单元测试 93 用例全绿 | ✅（2026-09-09） |
| 5 | PyInstaller 打包（spec `datas` 带出厂 config 模板，启动逐文件补齐，决策 16）+ 联调 | 删 exe 旁 config 目录重启可恢复；**Wireshark 逐字节比对 182B（含 host/control_mode 位）**；真机验证校零脉冲/控制模式/看门狗灯 | ⬜ |

### 下一步（按顺序做）

1. 阶段 5：PyInstaller 打包 + 真机/Wireshark 联调
2. 联调前：替换 `config/presets.yaml` 占位数据为真实标准数据

---

## 5. 待确认/联调时注意

- **控制模式**改为单字节 int8（0=OFF/1=抖杆/2=脉冲/3=倍脉冲/4=扫频/5=正弦/6=阶跃），C++ 控制器侧需同步；UI 目前只从俯仰(axis=1)下发，甲方若要求滚转也启用模式，改 `ui/main_window.py` 中 `_pitch_index` 绑定即可，后端 API 已保留 ch 参数（决策 2026-09-09）
- **Breakout 语义**已按字段名实现，Wireshark 联调时验证控制器接受（决策 2）
- **presets.yaml 出厂数据**：state_1..state_7 的 18 点/参数已由 `docs/配置.txt` 真实数据重建（2026-09-09）；脚蹬已整体删除，无 pedal 数据
- **启动基线**：内层编辑态初始 = default 出厂预设数据（全黑）；首次下发前控制器实际状态未知，联调时注意
- **force_offset 是否需要界面可编辑**：当前为通道常量（protocol.yaml channel_ids），如需「有死区归零」等运行时调整再加
- 环境：Windows 11，已确认 PyQt5 5.15.11 在 Python 3.8.10 与 3.13.12 均可导入
