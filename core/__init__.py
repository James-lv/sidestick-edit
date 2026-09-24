"""core —— 业务逻辑层（零 Qt 依赖，可 unittest 直测）。

模块：
    config_loader  加载 protocol.yaml / channels.yaml + 命令行覆盖
    packets        按 protocol.yaml 运行时生成 struct 格式串（禁手写）
    generic_curve  力-位移曲线引擎（numpy 向量化）         —— 阶段 2
    preset_store   presets.yaml 读写（原子写）+ final 计算 + 出厂预设表
    backend        BackendService(QObject)                 —— 阶段 3（唯一带 Qt 的入口，不在本层依赖）
"""
