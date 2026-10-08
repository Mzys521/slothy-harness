"""项目目录与公开仓库元数据；仅在用户配置项目时读取，不执行命令。"""

from configparser import ConfigParser, Error as ConfigError
from pathlib import Path
import re
from urllib.parse import urlsplit

from .workspace import canonical_root, linked


def _repository(root):
    folder = Path(root) / ".git"
    config = folder / "config"
    try:
        if not folder.is_dir() or linked(folder.lstat()) or linked(config.lstat()):
            return None
        info = config.stat()
        if info.st_nlink != 1 or info.st_size > 32768:
            return None
        parser = ConfigParser(interpolation=None)
        parser.read_string(config.read_text(encoding="utf-8"))
        remote = parser.get('remote "origin"', "url", fallback="")
        if remote.startswith("git@"):
            match = re.fullmatch(r"git@([^:]+):(.+)", remote)
            if not match:
                return None
            host, path = match.groups()
        else:
            parsed = urlsplit(remote)
            if parsed.scheme not in {"https", "ssh"}:
                return None
            host, path = parsed.hostname, parsed.path.strip("/")
        if host not in {"github.com", "gitlab.com", "bitbucket.org"}:
            return None
        path = path.removesuffix(".git")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", path):
            return None
        # 用户名、密码、查询串与认证信息不进入 DTO。
        return {"label": path, "url": f"https://{host}/{path}"}
    except (OSError, ValueError, ConfigError):
        return None


def inspect_directory(value):
    root, identity = canonical_root(value)
    return {"workspace_root": root, "root_identity": identity, "repository": _repository(root)}
