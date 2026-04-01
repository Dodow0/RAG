from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

import config
from models import Base


def _to_async_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


ASYNC_SQLITE_URL = _to_async_url(config.SQLITE_URL)
async_engine = create_async_engine(
    ASYNC_SQLITE_URL,
    future=True,
    connect_args={"timeout": 30},
)


@event.listens_for(async_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
async_session_maker = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def init_db() -> None:
    async with async_engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)


async def ensure_doc_status_column() -> None:
    if not config.SQLITE_URL.startswith("sqlite"):
        return
    async with async_engine.begin() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(docs)")
        cols = result.fetchall()
        has_status = any(row[1] == "status" for row in cols)
        if not has_status:
            await conn.exec_driver_sql(
                "ALTER TABLE docs ADD COLUMN status TEXT NOT NULL DEFAULT 'processing'"
            )
            await conn.exec_driver_sql(
                "UPDATE docs SET status='completed' WHERE total_chars > 0"
            )


async def ensure_doc_chunks_id_autoincrement() -> None:
    if not config.SQLITE_URL.startswith("sqlite"):
        return
    async with async_engine.begin() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(doc_chunks)")
        cols = result.fetchall()
        if not cols:
            return
        id_col = next((c for c in cols if c[1] == "id"), None)
        if not id_col:
            return
        col_type = (id_col[2] or "").upper()
        notnull = id_col[3]
        pk = id_col[5]
        if col_type == "INTEGER" and pk == 1 and notnull == 1:
            return

        await conn.exec_driver_sql(
            """
            CREATE TABLE doc_chunks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                doc_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                page INTEGER,
                char_start INTEGER,
                chunk_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(doc_id) REFERENCES docs(id)
            )
            """
        )
        await conn.exec_driver_sql(
            """
            INSERT INTO doc_chunks_new (id, doc_id, chunk_id, title, content, page, char_start, chunk_order)
            SELECT id, doc_id, chunk_id, title, content, page, char_start, chunk_order
            FROM doc_chunks
            """
        )
        await conn.exec_driver_sql("DROP TABLE doc_chunks")
        await conn.exec_driver_sql("ALTER TABLE doc_chunks_new RENAME TO doc_chunks")
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_doc_chunks_doc_id ON doc_chunks (doc_id)"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_doc_chunks_chunk_id ON doc_chunks (chunk_id)"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_doc_chunks_chunk_order ON doc_chunks (chunk_order)"
        )
