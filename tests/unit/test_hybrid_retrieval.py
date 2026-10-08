"""检索路由、去重、时间衰减、权限过滤和重排回退。"""

from dataclasses import replace
from datetime import datetime, timezone
import unittest

from slothy.core.context import (HybridRetriever, MemoryDocument, MemoryScope,
                                 RetrievalConfig, SearchHit, ContextError)


SCOPE = MemoryScope("owner", "session", "task")
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def hit(identity, text=None, *, owner="owner", created="2026-10-05T00:00:00+00:00", score=1.0, entities=None):
    return SearchHit(MemoryDocument(identity, owner, text or identity, created, entities=entities or {}), score)


class Channel:
    def __init__(self, hits=None, error=None):
        self.hits, self.error, self.calls = hits or [], error, []

    def search(self, query, scope, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.hits


class Rerank:
    def __init__(self, output=None, error=None):
        self.output, self.error = output, error

    def rerank(self, query, documents, **kwargs):
        if self.error:
            raise self.error
        return self.output


class HybridRetrievalTests(unittest.TestCase):
    def test_channel_timeouts_weights_and_failure_fallback(self):
        vector = Channel(error=TimeoutError("private"))
        bm25 = Channel([hit("order")])
        router = HybridRetriever(vector=vector, bm25=bm25, config=RetrievalConfig(), clock=lambda: NOW)
        result = router.search("order", SCOPE)
        self.assertEqual(result[0]["id"], "order")
        self.assertEqual(router.last_report["channels"]["vector"], "timeout")
        self.assertEqual(vector.calls[0]["timeout_seconds"], 3.0)
        self.assertEqual(bm25.calls[0]["limit"], 20)

    def test_deduplication_and_scope_entity_filter_before_prompt(self):
        vector = Channel([hit("a", "same evidence", entities={"order": "A"}), hit("foreign", owner="other")])
        bm25 = Channel([hit("duplicate", "same   evidence", entities={"order": "A"}), hit("unrelated", entities={"order": "B"})])
        router = HybridRetriever(vector=vector, bm25=bm25, clock=lambda: NOW)
        result = router.search("A", SCOPE, entities={"order": "A"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "a")

    def test_recency_can_break_equal_relevance_scores(self):
        channel = Channel([hit("old", created="2025-01-01T00:00:00+00:00"), hit("new")])
        router = HybridRetriever(bm25=channel, clock=lambda: NOW)
        self.assertEqual(router.search("task", SCOPE)[0]["id"], "new")

    def test_reranker_controls_order_and_bad_output_falls_back(self):
        channel = Channel([hit("first"), hit("second", score=0.5)])
        for rerank, expected in ((Rerank([(0, .1), (1, .9)]), "second"),
                                 (Rerank([(0, .9), (0, .1)]), "first"),
                                 (Rerank(error=TimeoutError()), "first"),
                                 (Rerank(error=RuntimeError("private")), "first")):
            router = HybridRetriever(bm25=channel, reranker=rerank, clock=lambda: NOW)
            self.assertEqual(router.search("task", SCOPE)[0]["id"], expected)
            self.assertNotIn("private", str(router.last_report))

    def test_all_channels_failed_returns_explicit_empty_report(self):
        router = HybridRetriever(vector=Channel(error=RuntimeError()), bm25=Channel(error=TimeoutError()))
        self.assertEqual(router.search("query", SCOPE), [])
        self.assertEqual(router.last_report["selected_count"], 0)

    def test_topk_threshold_and_query_config_validation(self):
        cfg = replace(RetrievalConfig(), top_k=3, min_score=0.2)
        router = HybridRetriever(bm25=Channel([hit(str(i)) for i in range(8)]), config=cfg)
        self.assertEqual(len(router.search("query", SCOPE)), 3)
        for query, top in (("", None), ("q" * (cfg.query_chars + 1), None), ("q", 4), ("q", True)):
            with self.assertRaises(ContextError):
                router.search(query, SCOPE, top_k=top)
        with self.assertRaises(ValueError):
            RetrievalConfig(top_k=21)


if __name__ == "__main__":
    unittest.main()
