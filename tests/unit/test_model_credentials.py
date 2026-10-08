"""凭据存储只使用假密钥；验证加密、归属隔离和损坏保护。"""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from slothy.infrastructure.llm.providers.catalog import endpoint_url, validate_binding
from slothy.infrastructure.llm.providers.credentials import CredentialStorageError, ProviderCredentials
from slothy.infrastructure.llm.providers.compatible_provider import client_factory


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "credentials.dpapi"
        self.store = ProviderCredentials(self.path)

    def test_credential_scope_and_replacement_are_independent(self):
        self.store.put("alice", "qwen", "china", "fake-china-key")
        self.store.put("alice", "qwen", "international", "fake-international-key")
        self.assertIsNone(self.store.get("bob", "qwen", "china"))
        self.assertEqual(self.store.get("alice", "qwen", "china"), "fake-china-key")
        self.store.put("alice", "qwen", "china", "fake-replacement-key")
        self.store.delete("alice", "qwen", "china")
        self.assertFalse(self.store.has("alice", "qwen", "china"))
        self.assertEqual(self.store.get("alice", "qwen", "international"), "fake-international-key")

    def test_windows_encrypts_and_restarts_or_other_platform_keeps_no_plaintext_file(self):
        secret = "fake-test-key-never-use-for-real-accounts"
        self.store.put("alice", "deepseek", "standard", secret)
        restarted = ProviderCredentials(self.path)
        if os.name == "nt":
            self.assertEqual(self.store.storage_kind, "windows_dpapi")
            self.assertNotIn(secret.encode(), self.path.read_bytes())
            self.assertEqual(restarted.get("alice", "deepseek", "standard"), secret)
        else:
            self.assertEqual(self.store.storage_kind, "session")
            self.assertFalse(self.path.exists())
            self.assertIsNone(restarted.get("alice", "deepseek", "standard"))

    def test_corrupt_file_is_not_silently_overwritten(self):
        self.store.storage_kind = "windows_dpapi"
        self.path.write_bytes(b"corrupted encrypted file")
        self.assertFalse(self.store.has("alice", "deepseek", "standard"))
        with self.assertRaises(CredentialStorageError):
            self.store.put("alice", "deepseek", "standard", "new-fake-key")
        self.assertEqual(self.path.read_bytes(), b"corrupted encrypted file")

    def test_official_endpoints_cannot_be_replaced_by_request_urls(self):
        valid = {"provider_id": "deepseek", "endpoint_id": "standard", "model": "deepseek-flash"}
        self.assertEqual(endpoint_url(valid), "https://api.deepseek.com")
        for value in ({**valid, "base_url": "https://attacker.invalid"},
                      {**valid, "endpoint_id": "https://attacker.invalid"},
                      {**valid, "model": "embedding-v3"}, {**valid, "model": "model?key=secret"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_binding(value)

    def test_sdk_never_follows_redirects_with_credentials(self):
        with patch("slothy.infrastructure.llm.providers.compatible_provider.OpenAI") as sdk:
            client_factory(api_key="fake", base_url="https://api.deepseek.com")
            transport = sdk.call_args.kwargs["http_client"]
            self.addCleanup(transport.close)
            self.assertFalse(transport.follow_redirects)
