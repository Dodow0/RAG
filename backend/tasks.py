from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import delete

from db import async_session_maker
from models import ChunkRecord, DocRecord
from pipeline import extract_pdf_path, split_text
from providers import EmbeddingClient
from vector_store import VectorStore

log = logging.getLogger("rag.worker")

embedder = EmbeddingClient()
vector_store = VectorStore()

def _publish_event(payload: dict) -> None:
    # Redis disabled in local environment
    return


async def process_uploaded_pdf_async(
    doc_id: str,
    pdf_path: str,
    original_name: str,
    file_stem: str,
) -> None:
    pdf_file = Path(pdf_path)
    try:
        log.info("[1/4] pypdf  <- %s  (%.1f KB)", original_name, pdf_file.stat().st_size / 1024)
        full_text, page_ranges, meta_title = extract_pdf_path(str(pdf_file))

        if not full_text.strip():
            raise ValueError("empty_text")

        log.info("[2/4] split  %d chars / %d pages", len(full_text), len(page_ranges))
        chunks = split_text(full_text, page_ranges, file_stem)

        log.info("[3/4] embedding  model=%s  n=%d", embedder.model, len(chunks))
        embeddings = embedder.embed([c["content"] for c in chunks])

        log.info("[4/4] chroma upsert  doc_id=%s", doc_id)
        vector_store.upsert_chunks(doc_id, chunks, embeddings)

        doc_title = meta_title or file_stem
        chunk_records = [
            ChunkRecord(
                doc_id=doc_id,
                chunk_id=chunk["id"],
                title=chunk["title"],
                content=chunk["content"],
                page=chunk.get("page"),
                char_start=chunk.get("char_start"),
                chunk_order=idx,
            )
            for idx, chunk in enumerate(chunks)
        ]

        async with async_session_maker() as session:
            doc = await session.get(DocRecord, doc_id)
            if not doc:
                log.warning("doc record missing, skip write: %s", doc_id)
                vector_store.delete_doc(doc_id)
                return
            doc.title = doc_title
            doc.total_chars = len(full_text)
            doc.status = "completed"
            session.add_all(chunk_records)
            await session.commit()

        log.info("done: %s  %d chunks", doc_title, len(chunks))
        _publish_event({
            "type": "doc_status",
            "doc_id": doc_id,
            "status": "completed",
            "title": doc_title,
            "chunk_count": len(chunks),
            "total_chars": len(full_text),
        })
    except Exception as exc:
        log.exception("job failed doc_id=%s: %s", doc_id, exc)
        try:
            async with async_session_maker() as session:
                doc = await session.get(DocRecord, doc_id)
                if doc:
                    doc.status = "failed"
                    await session.exec(delete(ChunkRecord).where(ChunkRecord.doc_id == doc_id))
                    await session.commit()
        finally:
            try:
                vector_store.delete_doc(doc_id)
            except Exception as cleanup_exc:
                log.warning("vector cleanup failed doc_id=%s: %s", doc_id, cleanup_exc)
        _publish_event({
            "type": "doc_status",
            "doc_id": doc_id,
            "status": "failed",
            "error": str(exc),
        })


def process_uploaded_pdf_job(
    doc_id: str,
    pdf_path: str,
    original_name: str,
    file_stem: str,
) -> None:
    asyncio.run(
        process_uploaded_pdf_async(
            doc_id,
            pdf_path,
            original_name,
            file_stem,
        )
    )
