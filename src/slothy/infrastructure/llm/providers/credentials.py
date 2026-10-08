"""本机凭据：Windows DPAPI 加密落盘；其他平台仅保留在本次进程内。"""

import ctypes
from ctypes import wintypes
from json import dumps, loads
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4


class CredentialStorageError(Exception):
    pass


def _dpapi(data, *, protect):
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise CredentialStorageError("凭据加密存储不可用。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class ProviderCredentials:
    HEADER = b"Slothy-DPAPI-v1\x00"

    def __init__(self, path):
        self.path = Path(path)
        self.storage_kind = "windows_dpapi" if os.name == "nt" else "session"
        self._session = {}
        self._lock = RLock()

    @staticmethod
    def _id(actor_id, provider_id, endpoint_id):
        return dumps([actor_id, provider_id, endpoint_id], separators=(",", ":"))

    def _read(self):
        if self.storage_kind == "session":
            return dict(self._session)
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_bytes()
            if len(raw) > 65536 or not raw.startswith(self.HEADER):
                raise ValueError()
            value = loads(_dpapi(raw[len(self.HEADER):], protect=False))
            if not isinstance(value, dict) or len(value) > 32 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
                raise ValueError()
            return value
        except Exception:
            raise CredentialStorageError("凭据文件无法解密，请恢复本机凭据文件后重试。") from None

    def _write(self, value):
        if self.storage_kind == "session":
            self._session = dict(value)
            return
        temporary = self.path.with_name(self.path.name + "." + uuid4().hex + ".tmp")
        try:
            raw = self.HEADER + _dpapi(dumps(value, ensure_ascii=False).encode("utf-8"), protect=True)
            if len(raw) > 65536:
                raise ValueError()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(raw)
            temporary.replace(self.path)
        except Exception:
            raise CredentialStorageError("凭据保存失败，请检查本机存储。") from None
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, actor_id, provider_id, endpoint_id):
        with self._lock:
            return self._read().get(self._id(actor_id, provider_id, endpoint_id))

    def has(self, actor_id, provider_id, endpoint_id):
        try:
            return bool(self.get(actor_id, provider_id, endpoint_id))
        except CredentialStorageError:
            return False

    def put(self, actor_id, provider_id, endpoint_id, value):
        with self._lock:
            items = self._read()
            items[self._id(actor_id, provider_id, endpoint_id)] = value
            self._write(items)

    def delete(self, actor_id, provider_id, endpoint_id):
        with self._lock:
            items = self._read()
            items.pop(self._id(actor_id, provider_id, endpoint_id), None)
            self._write(items)
