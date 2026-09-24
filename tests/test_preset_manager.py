# -*- coding: utf-8 -*-
"""preset_manager 冒烟测试：树加载、编辑信号、新建/删除（不弹窗路径）。"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from core import config_loader  # noqa: E402
from core.backend import BackendService  # noqa: E402
from ui.preset_manager import PresetManagerPage  # noqa: E402

# QApplication 由 tests/__init__.py 统一创建
_APP = QApplication.instance()
assert _APP is not None, "tests/__init__.py 应先创建 offscreen QApplication"
_CFG = Path(__file__).resolve().parent.parent / "config"


class TestPresetManagerPage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bcls_preset_"))
        self.presets_path = self.tmp / "presets.yaml"
        shutil.copyfile(_CFG / "presets.yaml", self.presets_path)
        self.bundle = config_loader.load_all()
        self.backend = BackendService(self.bundle, self.presets_path, udp_enabled=False)
        self.backend.start()
        self.page = PresetManagerPage(self.backend)
        self.page.show()
        QApplication.instance().processEvents()

    def tearDown(self):
        self.backend.stop()
        self.page.close()
        self.page = None
        shutil.rmtree(self.tmp, ignore_errors=True)
        QApplication.instance().processEvents()

    def test_refresh_list_populates_tree(self):
        tree = self.page._tree
        self.assertGreaterEqual(tree.topLevelItemCount(), 1)
        # State 组至少有一个子节点
        state_group = tree.topLevelItem(0)
        self.assertGreaterEqual(state_group.childCount(), 1)
        # 每个顶层节点下都能按 id 查到 item
        for p in self.backend.get_presets():
            self.assertIn(p["id"], self.page._item_by_id)

    def test_select_id_sets_current_item(self):
        preset = self._first_preset()
        if preset is None:
            self.skipTest("没有预设")
        self.page.select_id(preset["id"])
        QApplication.instance().processEvents()
        self.assertEqual(self.page._current_id(), preset["id"])
        self.assertTrue(self.page._btn_edit.isEnabled())
        self.assertTrue(self.page._btn_dl.isEnabled())

    def test_edit_request_loads_preset(self):
        preset = self._first_preset()
        if preset is None:
            self.skipTest("没有预设")
        received = []
        self.page.edit_requested.connect(lambda pid: received.append(pid))

        self.page.select_id(preset["id"])
        self.page._on_edit()
        QApplication.instance().processEvents()

        self.assertEqual(received, [preset["id"]])
        self.assertEqual(self.backend.get_editing_preset_id(), preset["id"])

    def test_new_creates_user_preset_without_switching_to_editor(self):
        received = []
        self.page.edit_requested.connect(lambda pid: received.append(pid))
        before = {p["id"] for p in self.backend.get_presets()}

        self.page._on_new()
        QApplication.instance().processEvents()

        after = {p["id"] for p in self.backend.get_presets()}
        new_id = (after - before).pop()
        self.assertTrue(new_id.startswith("user_"))
        self.assertEqual(received, [])
        self.assertEqual(self.page._current_id(), new_id)

    def test_telemetry_updates_status_labels(self):
        self.backend.telemetry_received.emit({
            0: {"Position": 1.23, "LoadCellForce": 4.56},
            1: {"Position": -0.5, "LoadCellForce": 0.12},
        })
        QApplication.instance().processEvents()
        self.assertEqual(self.page._status_labels[0][0].text(), "1.23")
        self.assertEqual(self.page._status_labels[0][1].text(), "4.56")

    def _first_preset(self):
        presets = self.backend.get_presets()
        return presets[0] if presets else None


if __name__ == "__main__":
    unittest.main()
