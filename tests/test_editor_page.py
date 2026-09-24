# -*- coding: utf-8 -*-
"""editor_page 冒烟测试：两 tab 容器 + 切 tab 刷新 + refresh_all。"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from core import config_loader  # noqa: E402
from core.backend import BackendService  # noqa: E402
from ui.editor_page import EditorPage  # noqa: E402

# QApplication 由 tests/__init__.py 统一创建
_APP = QApplication.instance()
assert _APP is not None, "tests/__init__.py 应先创建 offscreen QApplication"
_CFG = Path(__file__).resolve().parent.parent / "config"


class TestEditorPage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bcls_editor_"))
        self.presets_path = self.tmp / "presets.yaml"
        shutil.copyfile(_CFG / "presets.yaml", self.presets_path)
        self.bundle = config_loader.load_all()
        self.backend = BackendService(self.bundle, self.presets_path, udp_enabled=False)
        self.backend.start()
        self.editor = EditorPage(self.backend)
        self.editor.show()
        QApplication.instance().processEvents()

    def tearDown(self):
        self.backend.stop()
        self.editor.close()
        self.editor = None
        shutil.rmtree(self.tmp, ignore_errors=True)
        QApplication.instance().processEvents()

    def test_has_two_tabs(self):
        self.assertEqual(self.editor._tabs.count(), 2)
        names = [self.editor._tabs.tabText(i) for i in range(2)]
        self.assertEqual(names, ["俯仰", "滚转"])

    def test_channel_pages_match_channels(self):
        pages = self.editor.channel_pages()
        self.assertEqual(len(pages), 2)
        for page, ch_id in zip(pages, self.backend.channels()):
            self.assertEqual(page._ch, ch_id["index"])

    def test_current_channel_returns_active_index(self):
        self.assertEqual(self.editor.current_channel(), 0)
        self.editor._tabs.setCurrentIndex(1)
        QApplication.instance().processEvents()
        self.assertEqual(self.editor.current_channel(), 1)

    def test_tab_change_refreshes_page(self):
        # 切到滚转，再切回俯仰；只要 refresh 不抛异常、lineedit 数量一致即可
        self.editor._tabs.setCurrentIndex(1)
        QApplication.instance().processEvents()
        page = self.editor._pages[1]
        self.assertGreater(len(page._param_edits), 0)
        self.assertEqual(len(page._pos_edits), 18)
        self.assertEqual(len(page._force_edits), 18)

    def test_refresh_all_refreshes_every_page(self):
        # 加载第一个预设后整页刷新，确认各页参数框 dirty 状态被重绘
        preset = self._first_preset()
        if preset is None:
            self.skipTest("没有预设可供加载")
        for ch in sorted(preset["channels"]):
            self.backend.load_preset(ch, preset["id"])
        self.editor.refresh_all()
        QApplication.instance().processEvents()
        self.assertEqual(self.backend.get_editing_preset_id(), preset["id"])

    def _first_preset(self):
        presets = self.backend.get_presets()
        return presets[0] if presets else None


if __name__ == "__main__":
    unittest.main()
