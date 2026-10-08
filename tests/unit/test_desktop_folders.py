"""原生目录选择适配器的取消、串行和异常恢复契约。"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from slothy.infrastructure.desktop.folders import DesktopDirectoryPicker


class DesktopDirectoryPickerTests(unittest.TestCase):
    def setUp(self):
        self.picker = DesktopDirectoryPicker()
        webview = SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=20))
        mocked = patch.dict("sys.modules", {"webview": webview})
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_native_folder_selection_and_cancel(self):
        window = Mock()
        window.create_file_dialog.side_effect = [(r"E:\projects\example",), None]
        self.picker.attach(window)
        self.assertEqual(self.picker.choose(), r"E:\projects\example")
        self.assertIsNone(self.picker.choose())
        window.create_file_dialog.assert_called_with(20)

    def test_selection_cannot_be_opened_concurrently(self):
        def select(_):
            with self.assertRaises(ValueError):
                self.picker.choose()
            return ("project",)
        self.picker.attach(SimpleNamespace(create_file_dialog=select))
        self.assertEqual(self.picker.choose(), "project")

    def test_unattached_and_failed_dialog_do_not_lock_future_selection(self):
        with self.assertRaises(ValueError):
            self.picker.choose()
        window = Mock()
        window.create_file_dialog.side_effect = [RuntimeError("native failure"), ("project",)]
        self.picker.attach(window)
        with self.assertRaises(RuntimeError):
            self.picker.choose()
        self.assertEqual(self.picker.choose(), "project")


if __name__ == "__main__":
    unittest.main()
