# -*- coding: utf-8 -*-
"""main —— 程序入口：加载配置 → 建 BackendService → 建 MainWindow → exec。

用法（项目根 pyqt_refactor/）：
    python main.py                 # 正常启动（UDP 按 config/protocol.yaml）
    python main.py --no-udp        # 不启动 UDP（界面布局调试）
    python main.py --target-ip x.x.x.x   # 临时换控制器 IP（仅本次运行）

运行中改 IP/端口（立即生效并写回 protocol.yaml 持久化）：
    菜单栏「设置 → 网络绑定…」（决策 25，原版 C++ 同款入口）

配合 --selfcheck 可跑协议自检（等价 python -m core.selfcheck）。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PyQt5.QtWidgets import QApplication  # noqa: E402

from core import config_loader  # noqa: E402
from core.backend import BackendService  # noqa: E402


def _apply_qss(app: QApplication) -> None:
    qss = ROOT / "assets" / "style.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = config_loader.build_arg_parser()
    args = parser.parse_args(argv)

    bundle = config_loader.load_all(config_dir=args.config_dir)
    config_loader.apply_cli_overrides(bundle, args)

    if args.selfcheck:
        from core import selfcheck
        return selfcheck.main()

    presets_path = bundle.config_dir / "presets.yaml"

    app = QApplication(sys.argv[:1])
    _apply_qss(app)

    backend = BackendService(bundle, presets_path,
                             udp_enabled=not args.no_udp)
    backend.start()

    from ui.main_window import MainWindow
    win = MainWindow(backend)
    win.show()

    code = app.exec_()
    backend.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
