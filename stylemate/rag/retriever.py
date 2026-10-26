"""Offline-first hybrid retrieval with a deterministic no-key fallback."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from stylemate.domain.models import UserDocument
from stylemate.rag.models import KnowledgeRecord, RetrievalHit, UserDocumentChunk
from stylemate.rag.query_planning import knowledge_compatible, lexical_queries
from stylemate.rag.user_docs import chunk_user_document

logger = logging.getLogger(__name__)

RRF_K = 60
RECALL_MULTIPLIER = 3


@dataclass(frozen=True)
class _Candidate:
    key: str
    title: str
    content: str
    source_name: str
    source_url: str
    topic: str
    record_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    page_number: int | None = None
    section_title: str | None = None


class EmbeddingAdapter(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingUnavailableError(RuntimeError):
    """Stable boundary error; never exposes SDK details or credentials."""


class DashScopeEmbeddingAdapter:
    model = "text-embedding-v4"

    def __init__(self, request_timeout_seconds: float = 8.0):
        self.request_timeout_seconds = request_timeout_seconds

    def _embed(self, texts: list[str], text_type: str) -> list[list[float]]:
        import dashscope

        try:
            response = dashscope.TextEmbedding.call(
                model=self.model,
                input=texts,
                text_type=text_type,
                timeout=self.request_timeout_seconds,
            )
            if getattr(response, "status_code", None) != 200:
                raise EmbeddingUnavailableError("embedding service unavailable")
            output = getattr(response, "output", None)
            embeddings = getattr(output, "embeddings", None)
            if embeddings is None and isinstance(output, dict):
                embeddings = output.get("embeddings")
            vectors = [
                item.get("embedding") if isinstance(item, dict) else getattr(item, "embedding", None)
                for item in embeddings or []
            ]
            if len(vectors) != len(texts) or any(not vector for vector in vectors):
                raise EmbeddingUnavailableError("embedding service unavailable")
            return vectors
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError("embedding service unavailable") from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]


class OpenAICompatibleEmbeddingAdapter:
    """Small adapter for providers exposing the standard embeddings endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        request_timeout_seconds: float = 8.0,
        client=None,
    ):
        self.api_key = api_key.strip()
        self.base_url = base_url.strip()
        self.model_name = model_name.strip()
        self.model = f"openai-compatible:{self.model_name}"
        self.request_timeout_seconds = request_timeout_seconds
        self.client = client

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key or not self.base_url or not self.model_name:
            raise EmbeddingUnavailableError("embedding service unavailable")
        try:
            response = self._client().embeddings.create(
                model=self.model_name,
                input=texts,
                timeout=self.request_timeout_seconds,
            )
            items = sorted(
                getattr(response, "data", []) or [],
                key=lambda item: getattr(item, "index", 0),
            )
            vectors = [getattr(item, "embedding", None) for item in items]
            if len(vectors) != len(texts) or any(not vector for vector in vectors):
                raise EmbeddingUnavailableError("embedding service unavailable")
            return vectors
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError("embedding service unavailable") from exc

    def _client(self):
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.request_timeout_seconds,
                max_retries=0,
            )
        return self.client

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

def embedding_namespace(embedding: EmbeddingAdapter) -> str:
    identity = str(getattr(embedding, "model", type(embedding).__name__))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def builtin_collection_name(namespace: str) -> str:
    return f"builtin_knowledge_{namespace}"


def owner_collection_name(owner_id: str, namespace: str = "default") -> str:
    owner_hash = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:16]
    return f"user_{owner_hash}_{namespace}"


def user_vector_id(conversation_id: str, document_id: str, chunk_id: str = "") -> str:
    payload = f"{conversation_id}\x1f{document_id}\x1f{chunk_id}".encode("utf-8")
    return "doc_" + hashlib.sha256(payload).hexdigest()[:24]


def create_chroma_client(mode: str = "demo", path: str = "data/chroma"):
    """Select portable exact search on Windows, or opt into native Chroma."""
    if mode not in {"demo", "local"}:
        raise ValueError("mode must be demo or local")
    backend = os.getenv("STYLEMATE_VECTOR_BACKEND", "sqlite" if sys.platform == "win32" else "chroma")
    if backend == "sqlite":
        from stylemate.rag.portable_vectors import PortableVectorClient
        return PortableVectorClient(None if mode == "demo" else Path(path) / "portable-vectors.sqlite3")
    if backend != "chroma":
        raise ValueError("unknown_vector_backend")
    import chromadb

    if mode == "demo":
        return chromadb.EphemeralClient()
    if mode == "local":
        return chromadb.PersistentClient(path=path)
    raise ValueError("mode must be demo or local")

class HybridRetriever:
    def __init__(self, records: list[KnowledgeRecord], repository, embedding: EmbeddingAdapter | None, chroma_client, embedding_timeout_seconds: float = 8.0):
        # The canonical corpus retains drafts and project rules for audit. Only
        # source-reviewed facts participate in default factual retrieval.
        self.records = [record for record in records if record.is_published_evidence]
        self.repository = repository
        self.embedding = embedding
        self.chroma_client = chroma_client
        self.embedding_timeout_seconds = embedding_timeout_seconds
        self.embedding_namespace = (
            embedding_namespace(embedding) if embedding is not None else "none"
        )
        self._builtin_sync_signature: str | None = None
        self._builtin_sync_result = False
        self._user_sync_signatures: dict[tuple[str, str], tuple[str, bool]] = {}
        self._stats: Counter[str] = Counter()
        self.last_audit: dict[str, int | bool] = {}
        if self.embedding is not None:
            self.sync_builtin_index()

    def search(
        self,
        query: str,
        owner_id: str,
        conversation_id: str,
        top_k: int = 4,
        mode: Literal["bm25", "vector", "hybrid"] = "hybrid",
    ) -> list[RetrievalHit]:
        if top_k <= 0:
            return []
        if mode not in {"bm25", "vector", "hybrid"}:
            raise ValueError("mode must be bm25, vector, or hybrid")
        self._stats["search_requests"] += 1
        self._stats[f"search_mode_{mode}"] += 1
        documents = self.repository.list_documents(owner_id, conversation_id)
        # Recheck repository results before indexing candidates, including BM25.
        documents = [doc for doc in documents
                     if doc.owner_id == owner_id and doc.conversation_id == conversation_id]
        chunks = [
            chunk
            for document in documents
            for chunk in chunk_user_document(document)
        ]
        candidates = self._candidates(conversation_id, chunks)
        before_filter = len(candidates)
        candidates = [candidate for candidate in candidates if candidate.document_id or knowledge_compatible(
            query, title=candidate.title, content=candidate.content, topic=candidate.topic,
        )]
        candidate_map = {candidate.key: candidate for candidate in candidates}
        recall_limit = max(top_k, top_k * RECALL_MULTIPLIER)
        rankings: list[list[str]] = []
        lexical_count = 0
        vector_count = 0
        vector_failed = False
        if mode in {"bm25", "hybrid"}:
            lexical_rankings = [self._bm25_ranking(variant, candidates, recall_limit)
                                for variant in lexical_queries(query)]
            lexical_scores = reciprocal_rank_fusion(lexical_rankings)
            lexical = sorted(lexical_scores, key=lambda key: (-lexical_scores[key], key))[:recall_limit]
            rankings.append(lexical)
            lexical_count = len(lexical)

        if mode in {"vector", "hybrid"} and self.embedding is not None:
            try:
                semantic = self._semantic_ranking(query, owner_id, conversation_id, recall_limit)
                rankings.append(semantic)
                vector_count = len(semantic)
            except Exception:
                # BM25 remains available when embedding or Chroma is unavailable.
                vector_failed = True

        self.last_audit = {"lexical_candidates": lexical_count, "vector_candidates": vector_count,
                           "applicability_filtered": before_filter - len(candidates),
                           "vector_failed": vector_failed, "scope_applied": True, "selected": 0}

        rankings = [ranking for ranking in rankings if ranking]
        if not rankings:
            return []
        fused = reciprocal_rank_fusion(rankings)
        maximum_rrf_score = len(rankings) / (RRF_K + 1)
        ranked_keys = sorted(fused, key=lambda key: (-fused[key], key))
        hits: list[RetrievalHit] = []
        seen_user_documents: set[str] = set()
        for key in ranked_keys:
            candidate = candidate_map.get(key)
            if candidate is None:
                continue
            if candidate.document_id:
                if candidate.document_id in seen_user_documents:
                    continue
                seen_user_documents.add(candidate.document_id)
            title = candidate.title
            if candidate.page_number is not None:
                title = f"{title}（第 {candidate.page_number} 页）"
            hits.append(
                RetrievalHit(
                    title=title,
                    snippet=_snippet(candidate.content, query),
                    source_name=candidate.source_name,
                    source_url=candidate.source_url,
                    topic=candidate.topic,
                    score=round(min(1.0, fused[key] / maximum_rrf_score), 6),
                    record_id=candidate.record_id,
                    document_id=candidate.document_id,
                    chunk_id=candidate.chunk_id,
                    page_number=candidate.page_number,
                    section_title=candidate.section_title,
                    **self._review_metadata(candidate.record_id),
                )
            )
            if len(hits) == top_k:
                break
        self.last_audit["selected"] = len(hits)
        logger.info("knowledge_retrieval_finished lexical=%d vector=%d selected=%d vector_failed=%s",
                    lexical_count, vector_count, len(hits), vector_failed)
        return hits

    def _embedding_call(self, method, value):
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(method, value)
        try:
            return future.result(timeout=self.embedding_timeout_seconds)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _embed_documents(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), batch_size):
            batch = texts[offset : offset + batch_size]
            self._stats["document_embedding_requests"] += 1
            self._stats["document_texts_submitted"] += len(batch)
            vectors.extend(
                self._embedding_call(
                    self.embedding.embed_documents, batch
                )
            )
        return vectors

    def _review_metadata(self, record_id: str | None) -> dict:
        record = next((item for item in self.records if item.id == record_id), None)
        if record is None:
            return {"review_status": "user_provided"}
        return {
            "source_locator": record.source_locator,
            "review_status": record.review_status,
            "applicability": record.applicability,
            "limitations": record.limitations,
        }

    @staticmethod
    def _record_metadata(record: KnowledgeRecord) -> dict[str, str]:
        return {
            "retrieval_key": f"builtin:{record.id}",
            "record_id": record.id,
            "title": record.title,
            "source_name": record.source_name,
            "source_url": str(record.source_url),
            "topic": record.topic,
            "content_hash": hashlib.sha256(
                record.content.encode("utf-8")
            ).hexdigest(),
        }

    def _builtin_collection(self):
        return self.chroma_client.get_or_create_collection(
            builtin_collection_name(self.embedding_namespace),
            metadata={"hnsw:space": "cosine"},
        )

    def _user_collection(self, owner_id: str):
        return self.chroma_client.get_or_create_collection(
            owner_collection_name(owner_id, self.embedding_namespace),
            metadata={"hnsw:space": "cosine"},
        )

    def sync_builtin_index(self) -> bool:
        """Embed only new or changed built-in records outside the query path."""
        if self.embedding is None:
            return False
        self._stats["builtin_sync_requests"] += 1
        signature = hashlib.sha256(
            "\x1e".join(
                f"{record.id}:{hashlib.sha256(record.content.encode('utf-8')).hexdigest()}"
                for record in self.records
            ).encode("utf-8")
        ).hexdigest()
        if signature == self._builtin_sync_signature:
            self._stats["builtin_sync_cache_hits"] += 1
            return self._builtin_sync_result
        self._builtin_sync_signature = signature
        try:
            collection = self._builtin_collection()
            existing = collection.get(include=["metadatas"])
            existing_by_id = {
                item_id: metadata or {}
                for item_id, metadata in zip(
                    existing.get("ids", []), existing.get("metadatas") or []
                )
            }
            current_ids = {record.id for record in self.records}
            stale_ids = sorted(set(existing_by_id) - current_ids)
            if stale_ids:
                collection.delete(ids=stale_ids)
            changed = [
                record
                for record in self.records
                if existing_by_id.get(record.id, {}).get("content_hash")
                != self._record_metadata(record)["content_hash"]
            ]
            if changed:
                collection.upsert(
                    ids=[record.id for record in changed],
                    documents=[record.content for record in changed],
                    metadatas=[self._record_metadata(record) for record in changed],
                    embeddings=self._embed_documents(
                        [record.content for record in changed]
                    ),
                )
            self._builtin_sync_result = True
            self._stats["builtin_sync_successes"] += 1
        except Exception:
            self._builtin_sync_result = False
            self._stats["builtin_sync_failures"] += 1
        return self._builtin_sync_result

    def sync_user_documents(
        self,
        owner_id: str,
        conversation_id: str,
        documents: list[UserDocument],
    ) -> bool:
        """Synchronize changed chunks when documents are ingested or deleted."""
        if self.embedding is None:
            return False
        self._stats["user_sync_requests"] += 1
        chunks = [
            chunk
            for document in documents
            for chunk in chunk_user_document(document)
        ]
        signature = hashlib.sha256(
            "\x1e".join(chunk.chunk_id for chunk in chunks).encode("utf-8")
        ).hexdigest()
        signature_key = (owner_id, conversation_id)
        previous_sync = self._user_sync_signatures.get(signature_key)
        if previous_sync and previous_sync[0] == signature:
            self._stats["user_sync_cache_hits"] += 1
            return previous_sync[1]
        try:
            collection = self._user_collection(owner_id)
            existing = collection.get(
                where={"conversation_id": conversation_id},
                include=["metadatas"],
            )
            existing_by_id = {
                item_id: metadata or {}
                for item_id, metadata in zip(
                    existing.get("ids", []), existing.get("metadatas") or []
                )
            }
            current_by_id = {
                user_vector_id(conversation_id, chunk.document_id, chunk.chunk_id): chunk
                for chunk in chunks
            }
            stale_ids = sorted(set(existing_by_id) - set(current_by_id))
            if stale_ids:
                collection.delete(ids=stale_ids)
            changed_items = [
                (item_id, chunk)
                for item_id, chunk in current_by_id.items()
                if existing_by_id.get(item_id, {}).get("content_hash")
                != hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            ]
            if changed_items:
                collection.upsert(
                    ids=[item_id for item_id, _ in changed_items],
                    documents=[chunk.text for _, chunk in changed_items],
                    metadatas=[
                        self._user_chunk_metadata(conversation_id, chunk)
                        for _, chunk in changed_items
                    ],
                    embeddings=self._embed_documents(
                        [chunk.text for _, chunk in changed_items]
                    ),
                )
            result = True
            self._stats["user_sync_successes"] += 1
        except Exception:
            result = False
            self._stats["user_sync_failures"] += 1
        self._user_sync_signatures[signature_key] = (signature, result)
        return result

    @staticmethod
    def _user_chunk_metadata(
        conversation_id: str, chunk: UserDocumentChunk
    ) -> dict[str, str | int]:
        metadata: dict[str, str | int] = {
            "retrieval_key": f"user:{conversation_id}:{chunk.document_id}:{chunk.chunk_id}",
            "title": chunk.filename,
            "source_name": chunk.filename,
            "source_url": f"user-document://{chunk.document_id}",
            "topic": "wardrobe",
            "conversation_id": conversation_id,
            "document_id": chunk.document_id,
            "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "content_hash": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
        }
        if chunk.page_number is not None:
            metadata["page_number"] = chunk.page_number
        if chunk.section_title:
            metadata["section_title"] = chunk.section_title
        if chunk.previous_chunk_id:
            metadata["previous_chunk_id"] = chunk.previous_chunk_id
        if chunk.next_chunk_id:
            metadata["next_chunk_id"] = chunk.next_chunk_id
        return metadata

    def _semantic_ranking(
        self,
        query: str,
        owner_id: str,
        conversation_id: str,
        recall_limit: int,
    ) -> list[str]:
        collections = [
            (self._builtin_collection(), None),
            (
                self._user_collection(owner_id),
                {"conversation_id": conversation_id},
            ),
        ]
        collections = [
            (collection, where)
            for collection, where in collections
            if collection.count() > 0
        ]
        if not collections:
            return []
        self._stats["query_embedding_requests"] += 1
        query_embedding = self._embedding_call(self.embedding.embed_query, query)
        ranked: list[tuple[float, str]] = []
        for collection, where in collections:
            kwargs = {
                "query_embeddings": [query_embedding],
                "n_results": min(recall_limit, collection.count()),
                "include": ["metadatas", "distances"],
            }
            if where is not None:
                kwargs["where"] = where
            result = collection.query(**kwargs)
            for item_id, metadata, distance in zip(
                result["ids"][0], result["metadatas"][0], result["distances"][0]
            ):
                key = metadata.get("retrieval_key") or f"builtin:{item_id}"
                ranked.append((float(distance), key))
        return [key for _, key in sorted(ranked, key=lambda item: (item[0], item[1]))[:recall_limit]]

    def stats(self) -> dict[str, int]:
        """Return aggregate counters without query text, vectors, or credentials."""
        return dict(sorted(self._stats.items()))

    def _candidates(
        self, conversation_id: str, chunks: list[UserDocumentChunk]
    ) -> list[_Candidate]:
        candidates = [
            _Candidate(
                key=f"builtin:{record.id}",
                title=record.title,
                content=record.content,
                source_name=record.source_name,
                source_url=str(record.source_url),
                topic=record.topic,
                record_id=record.id,
            )
            for record in self.records
        ]
        candidates.extend(
            _Candidate(
                key=f"user:{conversation_id}:{chunk.document_id}:{chunk.chunk_id}",
                title=(
                    f"{chunk.filename} · {chunk.section_title}"
                    if chunk.section_title
                    else chunk.filename
                ),
                content=chunk.text,
                source_name=chunk.filename,
                source_url=f"user-document://{chunk.document_id}",
                topic="wardrobe",
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
            )
            for chunk in chunks
        )
        return candidates

    @staticmethod
    def _bm25_ranking(query: str, candidates: list[_Candidate], recall_limit: int) -> list[str]:
        query_tokens = list(dict.fromkeys(_tokenize(query)))
        if not query_tokens or not candidates:
            return []
        documents = [
            [*_tokenize(candidate.title), *_tokenize(candidate.title), *_tokenize(candidate.topic), *_tokenize(candidate.content)]
            for candidate in candidates
        ]
        average_length = sum(len(document) for document in documents) / len(documents)
        document_frequencies = Counter(
            token for document in documents for token in set(document)
        )
        ranked: list[tuple[float, str]] = []
        for candidate, document in zip(candidates, documents):
            frequencies = Counter(document)
            if not any(frequencies[token] for token in query_tokens):
                continue
            score = _bm25_score(
                query_tokens,
                frequencies,
                len(document),
                average_length,
                document_frequencies,
                len(documents),
            )
            ranked.append((score, candidate.key))
        return [key for _, key in sorted(ranked, key=lambda item: (-item[0], item[1]))[:recall_limit]]


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Fuse independent ranked lists without comparing incompatible raw scores."""
    if k < 1:
        raise ValueError("RRF k must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, key in enumerate(ranking, start=1):
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


def _tokenize(value: str) -> list[str]:
    tokens: list[str] = []
    for segment in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()):
        if "\u4e00" <= segment[0] <= "\u9fff":
            characters = list(segment)
            tokens.extend(characters)
            tokens.extend(
                "".join(characters[index : index + 2])
                for index in range(len(characters) - 1)
            )
        else:
            tokens.append(segment)
    return tokens


def _bm25_score(
    query_tokens: list[str],
    frequencies: Counter,
    document_length: int,
    average_length: float,
    document_frequencies: Counter,
    document_count: int,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    score = 0.0
    for token in query_tokens:
        frequency = frequencies[token]
        if frequency == 0:
            continue
        document_frequency = document_frequencies[token]
        inverse_document_frequency = math.log(
            1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        length_ratio = document_length / max(1.0, average_length)
        denominator = frequency + k1 * (1.0 - b + b * length_ratio)
        score += inverse_document_frequency * frequency * (k1 + 1.0) / denominator
    return score


def _snippet(content: str, query: str, limit: int = 180) -> str:
    position = content.find(query[:2]) if query else -1
    start = max(0, position - 30) if position >= 0 else 0
    fragment = content[start:start + limit].strip()
    return fragment + ("..." if start + limit < len(content) else "")
