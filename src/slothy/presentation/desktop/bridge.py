"""网页只获得一个受限请求入口，Presentation 不读取 Core 实体。"""

from slothy.application.api.workspace_api import WorkspaceAPI


class DesktopBridge:
    def __init__(self, api: WorkspaceAPI):
        self._api = api

    def request(self, method, payload):
        return self._api.request(method, payload)
