"""完成历史的写入边界；仓储与 embedding 均使用纯 Python 测试替身。"""

from types import SimpleNamespace
import unittest

from slothy.application.services import MemoryService
from slothy.core.context import ContextError


class MemoryServiceTests(unittest.TestCase):
    def test_unfinished_states_do_not_embed_or_write_input(self):
        for status in ("idle", "running", "thinking", "waiting_tool", "executing_tool",
                       "suspended", "waiting_approval", "failed", "cancelled"):
            with self.subTest(status=status):
                touched = []
                repository = SimpleNamespace(upsert_many=lambda value: touched.append("write"))
                embedding = SimpleNamespace(model="test-embedding", embed=lambda *args, **kwargs: touched.append("embed"))
                service = MemoryService(repository, embedding=embedding)
                run = SimpleNamespace(status=status, run_id="run", output="尚未完成的回答")
                with self.assertRaises(ContextError):
                    service.remember_completed_run(run, "当前输入", actor_id="owner")
                self.assertEqual(touched, [])

    def test_embedding_failure_still_commits_complete_question_and_answer_together(self):
        batches = []
        def failed_embedding(*args, **kwargs):
            raise TimeoutError("no remote call in test")
        service = MemoryService(SimpleNamespace(upsert_many=batches.append),
            embedding=SimpleNamespace(model="test-embedding", embed=failed_embedding))
        run = SimpleNamespace(status="completed", run_id="run", output="最终回答")
        service.remember_completed_run(run, "已完成任务的原输入", actor_id="owner")
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 2)
        self.assertEqual({d.entities["role"] for d in batches[0]}, {"user", "assistant"})
        self.assertTrue(all(d.owner_id == "owner" and not d.vector for d in batches[0]))

    def test_manual_memory_cannot_claim_completed_run_source(self):
        touched = []
        service = MemoryService(SimpleNamespace(upsert=touched.append))
        for document_id, source in (("manual", "completed_run"), ("run:fake:000000", "memory")):
            with self.assertRaises(ContextError):
                service.remember(document_id, "当前输入", actor_id="owner", source=source)
        self.assertEqual(touched, [])

    def test_completed_question_and_answer_use_one_embedding_batch(self):
        calls, batches = [], []
        def embed(texts, **kwargs):
            calls.append(texts)
            return [[1.0, 0.5] for text in texts]
        service = MemoryService(SimpleNamespace(upsert_many=batches.append),
            embedding=SimpleNamespace(model="test-embedding", embed=embed))
        service.remember_completed_run(SimpleNamespace(status="completed", run_id="run", output="最终回答"),
                                       "原始问题", actor_id="owner")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 2)
        self.assertTrue(all(d.vector == (1.0, 0.5) and d.embedding_model == "test-embedding" for d in batches[0]))


if __name__ == "__main__":
    unittest.main()
