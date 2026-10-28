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

from core import config_loader, packets  # noqa: E402
from core.backend import BackendService  # noqa: E402
from core.curve import signed_curve  # noqa: E402
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
        self.assertEqual(len(self.win._mode_box._time_inputs), 6)
        for mode in self.win._mode_box._buttons:
            self.assertIsNotNone(self.win._mode_box._amp_inputs[mode])
            self.assertIsNotNone(self.win._mode_box._freq_inputs[mode])
            self.assertEqual(self.win._mode_box._time_inputs[mode].text(), "")
        self.assertTrue(self.win._mode_box.isEnabled())

        self.backend.set_host_mode(True)
        QApplication.instance().processEvents()
        self.assertTrue(self.win._mode_box.isEnabled())

    def test_mode_buttons_show_absolute_amplitude_frequency_and_tooltips(self):
        box = self.win._mode_box
        expected = {
            1: ("100.0", "10.0"),
            2: ("0.5", "0.5"),
            3: ("0.5", "0"),
            4: ("0.5", "0.5–5.0"),
            5: ("0.5", "1.0"),
            6: ("0.5", "0"),
        }
        for mode, (amplitude, frequency) in expected.items():
            self.assertEqual(box._amp_inputs[mode].text(), amplitude)
            self.assertEqual(box._freq_inputs[mode].text(), frequency)
            self.assertTrue(box._buttons[mode].toolTip())

        self.assertIn("无固定重复频率", box._buttons[3].toolTip())

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
        self.assertTrue(self.win._preset_name.isVisible())
        self.assertEqual(self.win._preset_name.text(),
                 "当前模式：%s" % preset.get("label", preset["id"]))
        # 编辑页已加载该预设（三通道）
        self.assertEqual(self.backend.get_editing_preset_id(), preset["id"])

    def test_back_button_returns_to_presets(self):
        self.test_edit_request_switches_to_editor()
        self.win._editor_page.channel_pages()[0]._back_btn.click()
        QApplication.instance().processEvents()

        self.assertEqual(self.win._stack.currentIndex(), MainWindow.PAGE_PRESETS)
        self.assertFalse(self.win._preset_name.isVisible())

    def test_test_button_opens_test_page(self):
        self.win._preset_page._on_test()
        QApplication.instance().processEvents()

        self.assertEqual(self.win._stack.currentIndex(), MainWindow.PAGE_TEST)

    def test_view_menu_hides_and_restores_preset_channel_tabs(self):
        tabs = self.win._editor_page._tabs
        pitch = self._channel_index_for_axis(1)
        roll = self._channel_index_for_axis(2)
        yaw = self._channel_index_for_axis(3)
        pitch_tab = next(
            index for index, page in enumerate(self.win._editor_page._pages)
            if page._ch == pitch
        )
        roll_tab = next(
            index for index, page in enumerate(self.win._editor_page._pages)
            if page._ch == roll
        )
        yaw_tab = next(
            index for index, page in enumerate(self.win._editor_page._pages)
            if page._ch == yaw
        )
        pitch_action = self.win._channel_visibility_actions[("preset", 1)]
        roll_action = self.win._channel_visibility_actions[("preset", 2)]
        yaw_action = self.win._channel_visibility_actions[("preset", 3)]

        self.assertTrue(pitch_action.isChecked())
        tabs.setCurrentIndex(pitch_tab)
        pitch_action.setChecked(False)
        self.assertFalse(tabs.tabBar().isTabVisible(pitch_tab))
        self.assertEqual(tabs.currentIndex(), roll_tab)

        roll_action.setChecked(False)
        yaw_action.setChecked(False)
        self.assertTrue(tabs.isHidden())
        self.assertFalse(tabs.tabBar().isTabVisible(roll_tab))
        self.assertFalse(tabs.tabBar().isTabVisible(yaw_tab))
        pitch_action.setChecked(True)
        self.assertFalse(tabs.isHidden())
        self.assertTrue(tabs.tabBar().isTabVisible(pitch_tab))

    def test_view_menu_hides_and_restores_test_channel_pages(self):
        buttons = self.win._test_channel_buttons
        pitch_action = self.win._channel_visibility_actions[("test", 1)]
        roll_action = self.win._channel_visibility_actions[("test", 2)]
        yaw_action = self.win._channel_visibility_actions[("test", 3)]

        pitch_action.setChecked(False)
        self.assertTrue(buttons["俯仰"].isHidden())
        self.assertEqual(self.win._test_channel, self._channel_index_for_axis(2))

        roll_action.setChecked(False)
        self.assertEqual(self.win._test_channel, self._channel_index_for_axis(3))
        yaw_action.setChecked(False)
        self.assertIsNone(self.win._test_channel)
        self.assertTrue(self.win._test_channel_row.isHidden())
        self.assertTrue(self.win._test_plot_panel.isHidden())
        self.assertFalse(self.win._mode_box.isEnabled())

        yaw_action.setChecked(True)
        self.assertFalse(buttons["偏航"].isHidden())
        self.assertFalse(self.win._test_plot_panel.isHidden())
        self.assertEqual(self.win._test_channel, self._channel_index_for_axis(3))
        self.assertTrue(self.win._mode_box.isEnabled())

    def test_test_channel_buttons_switch_channel_and_show_yaw_curve(self):
        buttons = self.win._test_channel_buttons
        self.assertEqual(list(buttons), ["俯仰", "滚转", "偏航"])
        self.assertTrue(buttons["俯仰"].isChecked())
        self.assertTrue(buttons["偏航"].isEnabled())

        roll = next(ch["index"] for ch in self.bundle.channels()
                    if ch["axis"] == 2)
        buttons["滚转"].click()
        QApplication.instance().processEvents()
        self.assertEqual(self.win._test_channel, roll)
        self.assertTrue(buttons["滚转"].isChecked())
        self.assertEqual(
            self.win._test_plot_pages.currentIndex(),
            self.win._test_plot_page_indexes[roll],
        )
        self.assertEqual(self.win._mode_box.get_mode(),
                         self.backend.get_control_mode(roll))

        self.win._mode_box._buttons[2].click()
        QApplication.instance().processEvents()
        self.assertEqual(self.backend.get_control_mode(roll), 2)
        self.assertEqual(self.backend.get_control_mode(self.win._pitch_index), 0)

        buttons["偏航"].click()
        QApplication.instance().processEvents()
        yaw = next(ch["index"] for ch in self.bundle.channels()
                   if ch["axis"] == 3)
        self.assertTrue(buttons["偏航"].isChecked())
        self.assertEqual(self.win._test_channel, yaw)
        self.assertTrue(self.win._mode_box.isEnabled())
        self.assertEqual(
            self.win._test_plot_pages.currentIndex(),
            self.win._test_plot_page_indexes[yaw],
        )
        yaw_page = self.win._test_plot_pages.widget(
            self.win._test_plot_page_indexes[yaw])
        self.assertFalse(yaw_page._show_calib.isHidden())
        expected_curve = signed_curve(
            self.backend.get_editing(yaw)["pos_pts"],
            self.backend.get_editing(yaw)["force_pts"],
        )
        actual_curve = yaw_page._calib.getData()
        self.assertEqual(list(actual_curve[0]), expected_curve[0])
        self.assertEqual(list(actual_curve[1]), expected_curve[1])

        self.win._mode_box._buttons[2].click()
        self.assertEqual(self.backend.get_control_mode(yaw), 2)
        values = packets.unpack_packet(
            packets.build_packet_spec(self.bundle.protocol, "send"),
            self.backend._tx_log[-1])
        self.assertEqual(values["axis"], 3)

        buttons["俯仰"].click()
        self.assertTrue(self.win._mode_box.isEnabled())
        self.assertEqual(self.win._mode_box.get_mode(), 0)
        buttons["滚转"].click()
        self.assertEqual(self.win._mode_box.get_mode(), 2)

    def test_test_page_bottom_gray_margin_is_compact(self):
        self.assertEqual(self.win._test_page.layout().contentsMargins().bottom(), 10)

    def test_test_channel_buttons_are_aligned_to_bottom_of_mode_panel(self):
        self.win._stack.setCurrentIndex(MainWindow.PAGE_TEST)
        QApplication.instance().processEvents()

        panel = self.win._test_channel_row.parentWidget()
        row_bottom = (
            self.win._test_channel_row.y() + self.win._test_channel_row.height()
        )
        self.assertGreaterEqual(row_bottom, panel.height() - 16)

    # ------------------------------------------------------------------
    # 开环测试模式
    # ------------------------------------------------------------------
    def test_mode_box_targets_selected_channel(self):
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

    def _channel_index_for_axis(self, axis):
        return next(
            channel["index"] for channel in self.bundle.channels()
            if channel["axis"] == axis
        )


if __name__ == "__main__":
    unittest.main()
