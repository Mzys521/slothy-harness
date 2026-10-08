"""原生目录选择器；只由用户界面调用，不注册为模型工具。"""

from threading import Lock


class DesktopDirectoryPicker:
    def __init__(self):
        self.window = None
        self._lock = Lock()

    def attach(self, window):
        self.window = window

    def choose(self):
        if self.window is None or not self._lock.acquire(blocking=False):
            raise ValueError("folder_picker_unavailable")
        try:
            import webview
            selected = self.window.create_file_dialog(webview.FileDialog.FOLDER)
            return str(selected[0]) if selected else None
        finally:
            self._lock.release()
