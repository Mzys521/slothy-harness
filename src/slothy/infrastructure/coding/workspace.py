"""Coding 工具的文件系统边界；模型只能指定工作目录内的相对路径。"""

from hashlib import sha256
import os
from pathlib import Path, PureWindowsPath
import stat
import tempfile


MAX_FILE_BYTES = 1024 * 1024
SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".slothy", "dist", "build"})
PRIVATE_DIRS = frozenset({".git", ".slothy", ".ssh", ".aws", ".codex", ".agents"})


class CodingError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def protected(parts):
    for part in parts:
        name = part.casefold()
        if name in PRIVATE_DIRS or (name.startswith(".env") and name != ".env.example"):
            return True
        if name in {"id_rsa", "id_ed25519", "credentials", "credentials.json"} or name.endswith((".pem", ".key", ".pfx", ".p12")):
            return True
    return False


def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def canonical_root(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise CodingError("invalid_workspace")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute() or protected(path.parts):
        raise CodingError("invalid_workspace")
    # 检查原路径中的 junction/symlink，不能先 resolve 再隐去它们。
    for parent in (*reversed(path.parents), path):
        try:
            if linked(parent.lstat()):
                raise CodingError("linked_path")
        except OSError:
            raise CodingError("workspace_unavailable") from None
    root = path.resolve(strict=True)
    if not root.is_dir() or root == Path(root.anchor):
        raise CodingError("invalid_workspace")
    info = root.stat()
    return str(root), [info.st_dev, info.st_ino]


class ScopedWorkspace:
    def __init__(self, root, identity):
        self.root = Path(root)
        self.identity = tuple(identity)

    def path(self, relative, *, directory=False, missing=False):
        if not isinstance(relative, str) or len(relative) > 512 or "\x00" in relative:
            raise CodingError("invalid_path")
        text = relative.replace("\\", "/")
        parts = text.split("/")
        if text.startswith("/") or PureWindowsPath(relative).drive or ":" in text or any(p == ".." for p in parts):
            raise CodingError("path_outside_workspace")
        parts = [p for p in parts if p not in {"", "."}]
        if any(p.endswith((".", " ")) or PureWindowsPath(p).is_reserved() for p in parts):
            raise CodingError("invalid_path")
        if protected(parts):
            raise CodingError("protected_path")
        try:
            root_info = self.root.lstat()
            if linked(root_info) or (root_info.st_dev, root_info.st_ino) != self.identity:
                raise CodingError("workspace_changed")
            current = self.root
            for part in parts:
                current = current / part
                if not current.exists() and not current.is_symlink():
                    if missing:
                        continue
                    raise CodingError("path_not_found")
                info = current.lstat()
                if linked(info) or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1):
                    raise CodingError("linked_path")
            if not missing and (current.is_dir() != directory):
                raise CodingError("not_a_directory" if directory else "not_a_file")
            resolved = current.resolve()
            if not resolved.is_relative_to(self.root):
                raise CodingError("path_outside_workspace")
            if protected(resolved.relative_to(self.root).parts):
                raise CodingError("protected_path")
            return current
        except OSError:
            raise CodingError("path_unavailable") from None

    def read(self, relative):
        path = self.path(relative)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise CodingError("file_too_large")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino) or opened.st_nlink > 1:
                raise CodingError("file_changed")
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise CodingError("file_too_large")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            raise CodingError("not_utf8_text") from None
        if "\x00" in text:
            raise CodingError("not_utf8_text")
        return text, sha256(raw).hexdigest(), raw.startswith(b"\xef\xbb\xbf")

    def write(self, relative, text, expected_sha256):
        target = self.path(relative, missing=True)
        existed, bom = target.exists(), False
        if existed:
            _, digest, bom = self.read(relative)
            if expected_sha256 != digest:
                raise CodingError("file_changed")
        elif expected_sha256 is not None:
            raise CodingError("file_changed")
        raw = (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise CodingError("file_too_large")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path(relative, missing=True)
        fd, temporary = tempfile.mkstemp(prefix=".slothy-edit-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self.path(relative, missing=True)
            if existed:
                _, digest, _ = self.read(relative)
                if digest != expected_sha256:
                    raise CodingError("file_changed")
                os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
                os.replace(temporary, target)
            else:
                # link 的目标创建具有排他性；不会覆盖并发创建的文件。
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    raise CodingError("file_changed") from None
            return {"path": relative, "sha256": sha256(raw).hexdigest(), "bytes": len(raw), "created": not existed}
        finally:
            Path(temporary).unlink(missing_ok=True)

    def walk(self, relative=".", *, recursive=True, scan_limit=10000):
        start = self.path(relative, directory=True)
        pending, scanned = [start], 0
        while pending:
            folder = pending.pop()
            self.path(folder.relative_to(self.root).as_posix(), directory=True)
            # 不对无限大的目录 materialize/sort，扫描数量始终有上限。
            with os.scandir(folder) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > scan_limit:
                        raise CodingError("scan_limit_reached")
                    rel = Path(entry.path).relative_to(self.root).as_posix()
                    if protected(Path(rel).parts) or entry.name.casefold() in SKIP_DIRS:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if linked(info) or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        yield rel, "directory"
                        if recursive:
                            pending.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        yield rel, "file"
