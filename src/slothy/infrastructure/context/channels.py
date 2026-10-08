"""SQLite 检索通道：向量余弦、BM25 和实体记录查询。"""

from collections import Counter
from math import log, sqrt
from time import monotonic

from slothy.core.context import SearchHit
from .lexical import terms


class SQLiteRetrievalChannel:
    def __init__(self, kind, store, config, embedding=None):
        if kind not in {"vector", "bm25", "entity"}:
            raise ValueError("未知检索通道")
        self.kind, self.store, self.config, self.embedding = kind, store, config, embedding

    def search(self, query, scope, *, limit, entities, timeout_seconds):
        started = monotonic()
        if self.kind == "bm25" and getattr(self.store, "fts_available", False):
            return self.store.lexical_search(query, scope, entities=entities, limit=limit,
                                             timeout_seconds=timeout_seconds)
        docs = self.store.documents(scope, entities=entities, limit=self.config.scan_limit,
                                    timeout_seconds=timeout_seconds)

        def remaining():
            left = timeout_seconds - (monotonic() - started)
            if left <= 0:
                raise TimeoutError("本地检索超时")
            return left

        remaining()
        if self.kind == "vector":
            if self.embedding is None:
                return []
            vectors = self.embedding.embed([query], timeout_seconds=remaining())
            vector = vectors[0]
            norm = sqrt(sum(v * v for v in vector))
            hits = []
            for doc in docs:
                remaining()
                if doc.embedding_model != self.embedding.model or len(doc.vector) != len(vector) or not norm:
                    continue
                other_norm = sqrt(sum(v * v for v in doc.vector))
                score = sum(a * b for a, b in zip(vector, doc.vector)) / (norm * other_norm) if other_norm else 0
                if score > 0:
                    hits.append(SearchHit(doc, score))
        elif self.kind == "entity":
            query_terms = set(terms(query))
            hits = []
            for doc in docs:
                remaining()
                matches = len(entities) if entities else sum(1 for value in doc.entities.values()
                                                            if value.lower() in query_terms or value in query)
                if matches:
                    hits.append(SearchHit(doc, float(matches)))
        else:
            query_terms = set(terms(query))
            counts, lengths, frequency = [], [], Counter()
            for doc in docs:
                remaining()
                counter = Counter(terms(doc.text))
                counts.append(counter)
                lengths.append(sum(counter.values()))
                frequency.update(counter.keys())
            average = sum(lengths) / len(lengths) if lengths else 1
            hits = []
            for doc, counter, length in zip(docs, counts, lengths):
                remaining()
                score = 0.0
                for word in query_terms:
                    tf = counter.get(word, 0)
                    df = frequency.get(word, 0)
                    idf = log(1 + (len(docs) - df + 0.5) / (df + 0.5))
                    denominator = tf + self.config.bm25_k1 * (1 - self.config.bm25_b + self.config.bm25_b * length / (average or 1))
                    score += idf * tf * (self.config.bm25_k1 + 1) / denominator if denominator else 0
                if score > 0:
                    hits.append(SearchHit(doc, score))
        hits.sort(key=lambda hit: (-hit.score, hit.document.id))
        return hits[:limit]
