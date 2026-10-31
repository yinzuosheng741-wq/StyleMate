"""Portable exact vector search for personal corpora, using only the standard library.

The small collection interface matches the operations used by HybridRetriever.
This backend avoids native HNSW CPU/runtime failures; it does not implement ANN.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from threading import RLock


class PortableVectorClient:
    def __init__(self, path: str | Path | None = None):
        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self.lock = RLock()
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS collections (name TEXT PRIMARY KEY, dimension INTEGER, space TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS vectors (
                collection TEXT NOT NULL, id TEXT NOT NULL, document TEXT NOT NULL,
                metadata TEXT NOT NULL, vector TEXT NOT NULL, PRIMARY KEY(collection, id));
        """)
        self.connection.commit()

    def get_or_create_collection(self, name, metadata=None):
        space = (metadata or {}).get("hnsw:space", "cosine")
        if space not in {"cosine", "l2"}:
            raise ValueError("unsupported_vector_metric")
        with self.lock, self.connection:
            self.connection.execute("INSERT OR IGNORE INTO collections VALUES (?,NULL,?)", (name, space))
        return self.get_collection(name)

    def get_collection(self, name):
        with self.lock:
            row = self.connection.execute("SELECT space FROM collections WHERE name=?", (name,)).fetchone()
        if row is None:
            raise ValueError("collection_not_found")
        return PortableCollection(self, name, row[0])

    def list_collections(self):
        with self.lock:
            names = self.connection.execute("SELECT name FROM collections ORDER BY name").fetchall()
        return [self.get_collection(name[0]) for name in names]


class PortableCollection:
    def __init__(self, client, name, space):
        self.client, self.name, self.space = client, name, space

    def count(self):
        with self.client.lock:
            return self.client.connection.execute("SELECT count(*) FROM vectors WHERE collection=?", (self.name,)).fetchone()[0]

    def upsert(self, *, ids, embeddings, documents, metadatas=None):
        metadatas = metadatas if metadatas is not None else [{} for _ in ids]
        if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)) or len(set(ids)) != len(ids):
            raise ValueError("invalid_vector_batch")
        vectors = [_vector(value) for value in embeddings]
        if not vectors:
            return
        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise ValueError("vector_dimension_mismatch")
        with self.client.lock, self.client.connection:
            existing = self.client.connection.execute("SELECT dimension FROM collections WHERE name=?", (self.name,)).fetchone()[0]
            if existing is not None and existing != dimension:
                raise ValueError("vector_dimension_mismatch")
            self.client.connection.execute("UPDATE collections SET dimension=? WHERE name=?", (dimension, self.name))
            self.client.connection.executemany(
                "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?,?)",
                [(self.name, key, doc, json.dumps(meta), json.dumps(vec))
                 for key, doc, meta, vec in zip(ids, documents, metadatas, vectors)],
            )

    def _rows(self, where=None, ids=None):
        with self.client.lock:
            rows = self.client.connection.execute(
                "SELECT id,document,metadata,vector FROM vectors WHERE collection=? ORDER BY id", (self.name,)
            ).fetchall()
        decoded = [(key, doc, json.loads(meta), json.loads(vector)) for key, doc, meta, vector in rows]
        return [row for row in decoded if (ids is None or row[0] in ids)
                and _metadata_matches(row[2], where or {})]

    def get(self, *, where=None, ids=None, include=None):
        rows = self._rows(where, ids)
        return {"ids": [r[0] for r in rows], "documents": [r[1] for r in rows],
                "metadatas": [r[2] for r in rows], "embeddings": [r[3] for r in rows]}

    def delete(self, *, ids=None, where=None):
        if ids is None and where is None:
            raise ValueError("delete_filter_required")
        rows = self._rows(where, ids)
        with self.client.lock, self.client.connection:
            self.client.connection.executemany("DELETE FROM vectors WHERE collection=? AND id=?",
                                               [(self.name, row[0]) for row in rows])

    def query(self, *, query_embeddings, n_results, where=None, include=None):
        rows = self._rows(where)
        output = {"ids": [], "documents": [], "metadatas": [], "distances": []}
        for raw in query_embeddings:
            vector = _vector(raw)
            if any(len(vector) != len(row[3]) for row in rows):
                raise ValueError("vector_dimension_mismatch")
            ranked = sorted([(_distance(vector, row[3], self.space), row) for row in rows],
                            key=lambda item: (item[0], item[1][0]))[:max(0, n_results)]
            output["ids"].append([row[0] for _, row in ranked])
            output["documents"].append([row[1] for _, row in ranked])
            output["metadatas"].append([row[2] for _, row in ranked])
            output["distances"].append([distance for distance, _ in ranked])
        return output


def _metadata_matches(metadata, where):
    """Subset of Chroma predicates used by our scoped retrieval, before top-k."""
    if not isinstance(where, dict):
        raise ValueError("unsupported_vector_filter")
    for key, value in where.items():
        if key == "$and":
            if not isinstance(value, list) or not value:
                raise ValueError("unsupported_vector_filter")
            if not all(_metadata_matches(metadata, child) for child in value):
                return False
        elif key.startswith("$"):
            raise ValueError("unsupported_vector_filter")
        elif isinstance(value, dict):
            if set(value) != {"$in"} or not isinstance(value["$in"], list):
                raise ValueError("unsupported_vector_filter")
            if metadata.get(key) not in value["$in"]:
                return False
        elif metadata.get(key) != value:
            return False
    return True


def _vector(values):
    vector = [float(value) for value in values]
    if not vector or any(not math.isfinite(value) for value in vector):
        raise ValueError("invalid_vector")
    return vector


def _distance(a, b, space):
    if space == "l2":
        return sum((x - y) ** 2 for x, y in zip(a, b))
    denominator = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return 1.0 - sum(x * y for x, y in zip(a, b)) / denominator if denominator else 1.0
