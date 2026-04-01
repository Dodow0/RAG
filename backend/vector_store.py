"""
vector_store.py — ChromaDB 向量库封装。

所有 ChromaDB 读写操作集中在这里，main.py 只调用高层方法。
"""

from __future__ import annotations

import logging
from typing import Optional

import chromadb
from chromadb.config import Settings
from config import CHROMA_PATH, CHROMA_COLLECTION

log = logging.getLogger("rag.vectorstore")


class VectorStore:
    """
    ChromaDB 持久化向量库，使用余弦距离索引。

    每个向量记录的 metadata 字段：
        doc_id    — 所属文档 ID
        chunk_id  — chunk 在文档内的序号（"1", "2", ...）
        title     — chunk 标题
        page      — 来源页码（int 或 0）
    """

    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
        self._col = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            "VectorStore  path=%s  collection=%s  count=%d",
            CHROMA_PATH, CHROMA_COLLECTION, self._col.count(),
        )

    # ── 写操作 ─────────────────────────────────────────────────────────────────

    def upsert_chunks(
        self,
        doc_id: str,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """
        将一批 chunks 及其向量写入 ChromaDB。
        Chroma ID = "{doc_id}__{chunk_id}"，确保全局唯一且可反查文档。
        """
        ids, docs, metas, vecs = [], [], [], []

        for chunk, vec in zip(chunks, embeddings):
            ids.append(f"{doc_id}__{chunk['id']}")
            docs.append(chunk["content"])
            metas.append({
                "doc_id":   doc_id,
                "chunk_id": chunk["id"],
                "title":    chunk["title"],
                "page":     chunk.get("page") or 0,
            })
            vecs.append(vec)

        self._col.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=vecs)
        log.info("upsert %d vectors  doc_id=%s  total=%d", len(ids), doc_id, self._col.count())

    def delete_doc(self, doc_id: str) -> None:
        """删除某个文档的全部向量（通过 metadata 过滤）。"""
        self._col.delete(where={"doc_id": {"$eq": doc_id}})
        log.info("deleted doc_id=%s  remaining=%d", doc_id, self._col.count())

    # ── 读操作 ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        doc_ids: Optional[list[str]] = None,
    ) -> dict:
        """
        余弦相似度检索 Top-K。

        doc_ids 非空时，只在这些文档中检索（Chroma where 过滤）。
        返回 Chroma 原始结果字典，包含 ids / documents / metadatas / distances。
        """
        where: Optional[dict] = None
        if doc_ids:
            where = (
                {"doc_id": {"$eq": doc_ids[0]}}
                if len(doc_ids) == 1
                else {"doc_id": {"$in": doc_ids}}
            )

        return self._col.query(
            query_embeddings=[query_vector],
            n_results=min(top_k, self._col.count() or 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    # ── 统计 ───────────────────────────────────────────────────────────────────

    def count(self) -> int:
        return self._col.count()
