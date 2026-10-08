"""模型设置 UI 的真实本地宿主；仅外部模型 HTTP 被替换为离线 SDK 传输。"""

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from test_model_settings import ModelAPITransport
from slothy.desktop import assemble_desktop
from slothy.presentation.desktop.server import create_server


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        (project / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
        transport = ModelAPITransport()
        bridge = assemble_desktop(data_dir=root / "desktop", remote=False, model_client_factory=transport.factory)
        bridge._api._service.status["test_model_project"] = str(project)
        server = create_server(bridge, frontend="frontend/dist", port=8767)
        print("Model UI fixture: http://127.0.0.1:8767 (offline provider HTTP, no real keys)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
