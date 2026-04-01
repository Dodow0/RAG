"""
RAG 知识库问答系统 — FastAPI 后端 v3（SQLModel 版）
"""


import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import threading

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

import config
from db import ensure_doc_chunks_id_autoincrement, ensure_doc_status_column, get_session, init_db
from models import ChunkRecord, DocRecord
from providers import EmbeddingClient, GenerationClient
from tasks import process_uploaded_pdf_async, process_uploaded_pdf_job
from vector_store import VectorStore

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rag")

# ─── 客户端（应用启动时初始化一次）────────────────────────────────────────────

embedder = EmbeddingClient()
generator = GenerationClient()
vector_store = VectorStore()

UPLOAD_DIR = Path("./uploads")
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# ─── SQLAlchemy ORM（SQLite）──────────────────────────────────────────────────

# ─── FastAPI App ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行 (Startup)
    await init_db()
    await ensure_doc_status_column()
    await ensure_doc_chunks_id_autoincrement()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    log.info(
        "\n"
        "╔══════════════════════════════════════════════════════════╗\n"
        "║   RAG 知识库问答系统 — FastAPI 后端 v3                   ║\n"
        "╠══════════════════════════════════════════════════════════╣\n"
        "║  http://localhost:8000                                   ║\n"
        "║  Swagger : http://localhost:8000/docs                    ║\n"
        "║                                                          ║\n"
        "║  ① PDF 提取   : pypdf                                    ║\n"
        "║  ② 文本切分   : LangChain (size=%d, overlap=%d)        ║\n"
        "║  ③ Embedding  : %s              ║\n"
        "║               model=%s              ║\n"
        "║  ④ 向量数据库 : ChromaDB  path=%s               ║\n"
        "║  ⑤ 元数据数据库: SQLite  url=%s     ║\n"
        "║  ⑥ Generation : %s                       ║\n"
        "║               model=%s                     ║\n"
        "╚══════════════════════════════════════════════════════════╝",
        config.CHUNK_SIZE,
        config.CHUNK_OVERLAP,
        config.EMBED_BASE_URL,
        config.EMBED_MODEL,
        config.CHROMA_PATH,
        config.SQLITE_URL,
        config.GEN_BASE_URL,
        config.GEN_MODEL,
    )

    yield  # 在这个节点 FastAPI 开始接收请求

    # 应用关闭时执行的逻辑（比如关闭数据库连接，先打个日志）
    log.info("RAG 知识库问答系统已关闭。")


app = FastAPI(
    title="RAG 知识库问答系统",
    description=(
        "pypdf 提取 → LangChain 切分 → "
        "可配置 Embedding API → ChromaDB → 可配置 Generation API"
    ),
    version="3.0.0",
    lifespan=lifespan,  # <--- 把上面定义好的 lifespan 传给 FastAPI
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Pydantic Schemas ─────────────────────────────────────────────────────────


class Chunk(BaseModel):
    id: str
    title: str
    content: str
    page: Optional[int] = None
    char_start: Optional[int] = None


class DocMeta(BaseModel):
    id: str
    title: str
    file_name: str
    uploaded_at: str
    status: str
    chunk_count: int
    total_chars: int


class DocDetail(BaseModel):
    id: str
    title: str
    file_name: str
    uploaded_at: str
    status: str
    total_chars: int
    chunks: list[Chunk]


class QueryRequest(BaseModel):
    question: str
    doc_ids: Optional[list[str]] = None
    top_k: Optional[int] = None


class RetrievedChunk(BaseModel):
    id: str
    title: str
    content: str
    page: Optional[int] = None
    doc_title: str
    doc_id: str
    relevance_score: int
    distance: float


class QueryResponse(BaseModel):
    answer: str
    retrieved_chunks: list[RetrievedChunk]


class ProviderInfo(BaseModel):
    base_url: str
    model: str


class HealthResponse(BaseModel):
    status: str
    docs: int
    chunks: int
    chroma_vectors: int
    embedding: ProviderInfo
    generation: ProviderInfo
    chunk_size: int
    chunk_overlap: int
    timestamp: str


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _distance_to_score(distance: float) -> int:
    return round(max(0.0, 1.0 - distance) * 100)


async def _doc_to_meta(session: AsyncSession, doc: DocRecord) -> DocMeta:
    chunk_count = (await session.exec(
        select(func.count(ChunkRecord.id)).where(ChunkRecord.doc_id == doc.id)
    )).scalar_one()
    return DocMeta(
        id=doc.id,
        title=doc.title,
        file_name=doc.file_name,
        uploaded_at=doc.uploaded_at,
        status=doc.status,
        chunk_count=chunk_count,
        total_chars=doc.total_chars,
    )


async def _load_doc_detail(session: AsyncSession, doc_id: str) -> Optional[DocDetail]:
    doc = await session.get(DocRecord, doc_id)
    if not doc:
        return None
    chunk_rows = (await session.exec(
        select(ChunkRecord)
        .where(ChunkRecord.doc_id == doc_id)
        .order_by(ChunkRecord.chunk_order)
    )).scalars().all()
    return DocDetail(
        id=doc.id,
        title=doc.title,
        file_name=doc.file_name,
        uploaded_at=doc.uploaded_at,
        status=doc.status,
        total_chars=doc.total_chars,
        chunks=[
            Chunk(
                id=row.chunk_id,
                title=row.title,
                content=row.content,
                page=row.page,
                char_start=row.char_start,
            )
            for row in chunk_rows
        ],
    )


async def _save_doc_and_chunks(
    session: AsyncSession,
    doc_record: DocRecord,
    chunk_records: list[ChunkRecord],
) -> None:
    session.add(doc_record)
    session.add_all(chunk_records)
    await session.commit()


async def _get_doc_count(session: AsyncSession) -> int:
    return (await session.exec(select(func.count(DocRecord.id)))).scalar_one()


async def _build_title_map(session: AsyncSession, metadatas: list[dict]) -> dict[str, str]:
    doc_ids = list({meta["doc_id"] for meta in metadatas})
    rows = (await session.exec(select(DocRecord).where(DocRecord.id.in_(doc_ids)))).scalars().all()
    return {row.id: row.title for row in rows}


def _get_queue():
    raise RuntimeError("RQ disabled in local environment")


async def _stream_generation(question: str, retrieved: list[dict]):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _worker():
        try:
            for delta in generator.generate_stream(question, retrieved):
                loop.call_soon_threadsafe(queue.put_nowait, delta)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, {"error": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_worker, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item


async def _event_stream():
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SSE disabled (Redis unavailable)")


async def _stream_upload_to_disk(
    upload: UploadFile,
    dest_path: Path,
    max_bytes: int,
    chunk_size: int,
) -> int:
    total = 0
    try:
        with dest_path.open("wb") as handle:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("file_too_large")
                handle.write(chunk)
    finally:
        await upload.close()
    return total


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse, tags=["系统"])
async def health(session: AsyncSession = Depends(get_session)):
    """健康检查，返回当前 Provider 配置与知识库统计。"""
    docs = (await session.exec(select(func.count(DocRecord.id)))).scalar_one()
    chunks = (await session.exec(select(func.count(ChunkRecord.id)))).scalar_one()

    return HealthResponse(
        status="ok",
        docs=docs,
        chunks=chunks,
        chroma_vectors=await run_in_threadpool(vector_store.count),
        embedding=ProviderInfo(base_url=config.EMBED_BASE_URL, model=config.EMBED_MODEL),
        generation=ProviderInfo(base_url=config.GEN_BASE_URL, model=config.GEN_MODEL),
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/api/events", tags=["系统"])
async def events():
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SSE disabled (Redis unavailable)")


@app.get("/api/docs", tags=["知识库"])
async def list_docs(session: AsyncSession = Depends(get_session)) -> dict:
    """列出所有文档元信息（不含 chunk 正文）。"""
    docs = (await session.exec(select(DocRecord).order_by(DocRecord.uploaded_at.desc()))).scalars().all()
    payload = [(await _doc_to_meta(session, doc)).model_dump() for doc in docs]
    return {"docs": payload}


@app.get("/api/docs/{doc_id}", tags=["知识库"])
async def get_doc(doc_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """获取单个文档完整内容（含所有 chunks）。"""
    detail = await _load_doc_detail(session, doc_id)
    if not detail:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    return {"doc": detail.model_dump()}


@app.post(
    "/api/upload",
    status_code=status.HTTP_201_CREATED,
    tags=["知识库"],
    summary="上传 PDF，构建向量知识库",
)
async def upload_pdf(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    background_tasks: BackgroundTasks = None,
) -> dict:
    """
    1. PDF 提取
    2. 文本切分
    3. Embedding
    4. Chroma upsert + SQLite 持久化
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "只接受 PDF 文件")

    fname = file.filename or "unknown.pdf"
    stem = fname.removesuffix(".pdf")
    doc_id = str(uuid.uuid4())
    pdf_path = UPLOAD_DIR / f"{doc_id}.pdf"

    try:
        total_bytes = await _stream_upload_to_disk(
            file,
            pdf_path,
            MAX_UPLOAD_BYTES,
            UPLOAD_CHUNK_SIZE,
        )
    except ValueError:
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件超过 50 MB")

    if total_bytes == 0:
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "空文件")

    uploaded_at = datetime.now(timezone.utc).isoformat()
    doc_record = DocRecord(
        id=doc_id,
        title=stem,
        file_name=fname,
        uploaded_at=uploaded_at,
        status="processing",
        total_chars=0,
    )

    try:
        session.add(doc_record)
        await session.commit()
    except Exception as exc:
        log.exception("SQLite 写入失败: %s", exc)
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "写入数据库失败")

    if config.PROCESSING_MODE == "rq":
        try:
            queue = _get_queue()
            queue.enqueue(
                process_uploaded_pdf_job,
                doc_id,
                str(pdf_path),
                fname,
                stem,
                job_timeout=3600,
            )
        except Exception as exc:
            log.exception("任务入队失败: %s", exc)
            doc = await session.get(DocRecord, doc_id)
            if doc:
                doc.status = "failed"
                await session.commit()
            if pdf_path.exists():
                pdf_path.unlink(missing_ok=True)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "任务队列不可用")
    elif config.PROCESSING_MODE == "inline":
        await process_uploaded_pdf_async(doc_id, str(pdf_path), fname, stem)
    else:
        if background_tasks is None:
            background_tasks = BackgroundTasks()
        background_tasks.add_task(
            process_uploaded_pdf_job,
            doc_id,
            str(pdf_path),
            fname,
            stem
        )

    return {"message": "上传成功，正在处理", "doc_id": doc_id}


@app.delete("/api/docs/{doc_id}", tags=["知识库"])
async def delete_doc(doc_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """删除文档，同步清理 ChromaDB 向量。"""
    doc = await session.get(DocRecord, doc_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")

    try:
        await session.delete(doc)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        log.exception("删除数据库记录失败")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "删除文档元数据失败")

    # DB 删除成功后，再去清理向量库
    try:
        await run_in_threadpool(vector_store.delete_doc, doc_id)
    except Exception as exc:
        log.warning("文档 %s 数据库已删，但向量清理失败: %s", doc_id, exc)

    return {"success": True}


@app.post("/api/query", tags=["问答"])
async def query(
    body: QueryRequest,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """
    语义检索增强生成（RAG）：
    Embedding 问题 -> Chroma 检索 -> LLM 生成回答
    """
    q = body.question.strip()
    if not q:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "问题不能为空")

    doc_count = await _get_doc_count(session)
    vector_count = await run_in_threadpool(vector_store.count)
    if doc_count == 0 or vector_count == 0:
        async def _empty_stream():
            yield json.dumps({"type": "meta", "retrieved_chunks": []}, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "error",
                "message": "知识库中暂无文档，请先上传 PDF 文件。",
            }, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

        return StreamingResponse(
            _empty_stream(),
            media_type="application/x-ndjson",
        )

    top_k = body.top_k or config.TOP_K

    log.info("[1/3] Embedding 问题  model=%s", embedder.model)
    q_vec = await run_in_threadpool(embedder.embed_one, q)

    log.info("[2/3] ChromaDB 检索  top_k=%d  filter=%s", top_k, body.doc_ids)
    raw = await run_in_threadpool(vector_store.search, q_vec, top_k, body.doc_ids)

    title_map: dict[str, str] = {}
    if raw["metadatas"] and raw["metadatas"][0]:
        title_map = await _build_title_map(session, raw["metadatas"][0])

    retrieved: list[dict] = []
    if raw["ids"] and raw["ids"][0]:
        for doc_text, meta, dist in zip(
            raw["documents"][0],
            raw["metadatas"][0],
            raw["distances"][0],
        ):
            retrieved.append({
                "id": meta["chunk_id"],
                "title": meta["title"],
                "content": doc_text,
                "page": meta.get("page") or None,
                "doc_title": title_map.get(meta["doc_id"], meta["doc_id"]),
                "doc_id": meta["doc_id"],
                "distance": round(dist, 6),
                "relevance_score": _distance_to_score(dist),
            })

    if not retrieved:
        # 使用一个独立的异步生成器返回完整的流状态
        async def _empty_stream():
            yield json.dumps({"type": "meta", "retrieved_chunks": []}, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "error",
                "message": "未在知识库中找到与问题相关的内容，请尝试换一种问法或上传更多文档。"
            }, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

        return StreamingResponse(
            _empty_stream(),
            media_type="application/x-ndjson",
        )

    log.info("[3/3] Generation(stream)  model=%s", generator.model)

    async def _response_stream():
        meta = {
            "type": "meta",
            "retrieved_chunks": [RetrievedChunk(**r).model_dump() for r in retrieved],
        }
        yield json.dumps(meta, ensure_ascii=False) + "\n"

        async for item in _stream_generation(q, retrieved):
            if isinstance(item, dict) and item.get("error"):
                yield json.dumps({"type": "error", "message": item["error"]}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                return
            yield json.dumps({"type": "delta", "text": item}, ensure_ascii=False) + "\n"

        yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    return StreamingResponse(_response_stream(), media_type="application/x-ndjson")
