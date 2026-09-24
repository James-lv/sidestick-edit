# -*- coding: utf-8 -*-
"""main_window 完整冒烟测试：蓝条 + 双层页面 + 灰框 + 前后端分离。

使用 offscreen 平台，无需真实显示器；所有 UI 交互只通过 backend 公开 API 验证。"""

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
from ui.main_window import MainWindow  # noqa: E402

# QApplication 由 tests/__init__.py 统一创建
_APP = QApplication.instance()
assert _APP is not None, "tests/__init__.py 应先创建 offscreen QApplication"
_CFG = Path(__file__).resolve().parent.parent / "config"


class TestMainWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bcls_main_window_"))
        self.presets_path = self.tmp / "presets.yaml"
        shutil.copyfile(_CFG / "presets.yaml", self.presets_path)
        self.bundle = config_loader.load_all()
        self.backend = BackendService(self.bundle, self.presets_path, udp_enabled=False)
        self.backend.start()
        self.win = MainWindow(self.backend)
        self.win.show()
        QApplication.instance().processEvents()

    def tearDown(self):
        self.backend.stop()
        self.win.close()
        self.win = None
        shutil.rmtree(self.tmp, ignore_errors=True)
        QApplication.instance().processEvents()

    # ------------------------------------------------------------------
    # 基本装配
    # ------------------------------------------------------------------
    def test_pitch_index_is_axis_1(self):
        pitch = next(c for c in self.bundle.channels() if c["axis"] == 1)
        self.assertEqual(self.win._pitch_index, pitch["index"])

    def test_initial_page_is_presets_and_back_hidden(self):
        self.assertEqual(self.win._stack.currentIndex(), MainWindow.PAGE_PRESETS)
        self.assertFalse(self.win._editor_page.channel_pages()[0]._back_btn.isVisible())

    def test_top_bar_has_link_led_only(self):
        self.assertIsNotNone(self.win._link_led)
        self.assertIsNotNone(self.win._link_text)
        self.assertEqual(self.win._link_text.text(), "网络连接")
        self.assertFalse(hasattr(self.win, "_host_btn"))

    # ------------------------------------------------------------------
    # 蓝条交互
    # ------------------------------------------------------------------
    def test_test_page_has_mode_buttons_in_columns(self):
        self.assertIsNotNone(self.win._mode_box)
        self.assertEqual(len(self.win._mode_box._buttons), 6)
        self.assertEqual(len(self.win._mode_box._amp_inputs), 6)
        self.assertEqual(len(self.win._mode_box._freq_inputs), 6)
        for mode in self.win._mode_box._buttons:
            self.assertIsNotNone(self.win._mode_box._amp_inputs[mode])
            self.assertIsNotNone(self.win._mode_box._freq_inputs[mode])
        self.assertTrue(self.win._mode_box.isEnabled())

        self.backend.set_host_mode(True)
        QApplication.instance().processEvents()
        self.assertTrue(self.win._mode_box.isEnabled())

    def test_link_changed_updates_label_and_led(self):
        self.backend.link_state_changed.emit(True, "已连接")
        QApplication.instance().processEvents()
        self.assertEqual(self.win._link_text.toolTip(), "已连接")

        self.backend.link_state_changed.emit(False, "未连接")
        QApplication.instance().processEvents()
        self.assertEqual(self.win._link_text.toolTip(), "未连接")

    # ------------------------------------------------------------------
    # 双层页面切换
    # ------------------------------------------------------------------
    def test_edit_request_switches_to_editor(self):
        # 选一个非出厂预设
        preset = self._first_preset()
        self.assertIsNotNone(preset, "测试数据需要至少一个预设")
        self.win._preset_page.select_id(preset["id"])
        self.win._preset_page._on_edit()
        QApplication.instance().processEvents()

        self.assertEqual(self.win._stack.currentIndex(), MainWindow.PAGE_EDITOR)
        self.assertTrue(self.win._editor_page.channel_pages()[0]._back_btn.isVisible())
        # 编辑页已加载该预设（俯仰/滚转两通道）
        self.assertEqual(self.backend.get_editing_preset_id(), preset["id"])

    def test_back_button_returns_to_presets(self):
        self.test_edit_request_switches_to_editor()
        self.win._editor_page.channel_pages()[0]._back_btn.click()
        QApplication.instance().processEvents()

        self.assertEqual(self.win._stack.currentIndex(), MainWindow.PAGE_PRESETS)

    def test_test_button_opens_test_page(self):
        self.win._preset_page._on_test()
        QApplication.instance().processEvents()

        self.assertEqual(self.win._stack.currentIndex(), MainWindow.PAGE_TEST)

    # ------------------------------------------------------------------
    # 底部灰框（俯仰专用）
    # ------------------------------------------------------------------
    def test_mode_box_fixed_to_pitch(self):
        box = self.win._mode_box
        self.assertEqual(box.get_mode(), 0)
        self.assertTrue(box.isEnabled())

        box._buttons[1].click()
        QApplication.instance().processEvents()
        self.assertEqual(self.backend.get_control_mode(self.win._pitch_index), 1)
        self.assertEqual(box.get_mode(), 1)

        # 直接切到另一模式，不发 0
        box._buttons[5].click()
        QApplication.instance().processEvents()
        self.assertEqual(self.backend.get_control_mode(self.win._pitch_index), 5)
        self.assertEqual(box.get_mode(), 5)

        # 再次点击同一按钮 → OFF
        box._buttons[5].click()
        QApplication.instance().processEvents()
        self.assertEqual(self.backend.get_control_mode(self.win._pitch_index), 0)
        self.assertEqual(box.get_mode(), 0)

    def test_mode_box_is_always_available_in_test_page(self):
        box = self.win._mode_box
        self.assertTrue(box.isEnabled())
        self.backend.set_host_mode(False)
        QApplication.instance().processEvents()
        self.assertTrue(box.isEnabled())

        n = len(self.backend._tx_log)
        box._buttons[1].click()
        QApplication.instance().processEvents()
        self.assertEqual(len(self.backend._tx_log), n + 1)
        self.assertEqual(self.backend.get_control_mode(self.win._pitch_index), 1)

    # ------------------------------------------------------------------
    def _first_preset(self):
        presets = self.backend.get_presets()
        return presets[0] if presets else None


if __name__ == "__main__":
    unittest.main()
