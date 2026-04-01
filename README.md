# RAG 知识库问答系统

一个前后端分离的 RAG（Retrieval-Augmented Generation）项目：
- 前端：React + Vite，支持 PDF 上传、文档管理、流式问答、检索片段可视化
- 后端：FastAPI + SQLite + ChromaDB，负责 PDF 解析、分块、向量化、检索与生成

## 功能特性

- PDF 文档上传与入库（支持单次多文件上传，单文件默认最大 50MB）
- 基于 `pypdf` 的文本提取
- 基于 `langchain-text-splitters` 的语义分块
- 可切换任意 OpenAI 兼容接口的 Embedding / Generation Provider
- ChromaDB 向量检索（余弦距离）
- `/api/query` NDJSON 流式输出（边生成边返回）
- SQLite 持久化文档元数据与 chunk 明细
- 文档删除时同步清理向量数据

## 技术栈

- Frontend: React 19, Vite 7
- Backend: FastAPI, Uvicorn, SQLModel/SQLAlchemy, pypdf, LangChain Text Splitters, OpenAI SDK, ChromaDB
- Storage: SQLite (`rag_docs.db`), Chroma persistent dir (`chroma_db/`)

## 项目结构

```text
RAG/
├─ backend/
│  ├─ main.py                # FastAPI 入口
│  ├─ tasks.py               # 文档处理任务（background/inline/rq）
│  ├─ pipeline.py            # PDF 提取与分块
│  ├─ providers.py           # Embedding/Generation 客户端
│  ├─ vector_store.py        # ChromaDB 封装
│  ├─ db.py                  # Async SQLite 初始化与会话
│  ├─ models.py              # ORM 模型（docs / doc_chunks）
│  ├─ config.py              # 所有运行参数（支持环境变量覆盖）
│  ├─ requirements.txt
│  ├─ uploads/               # 上传 PDF 存储目录
│  ├─ chroma_db/             # 向量库持久化目录
│  └─ rag_docs.db            # SQLite 数据库文件
├─ frontend/
│  ├─ src/
│  │  ├─ main.jsx
│  │  ├─ app.jsx             # 主界面
│  │  └─ App.css
│  ├─ package.json
│  └─ vite.config.js
├─ run_rag.bat               # Windows 一键启动脚本
└─ README.md
```

## 环境要求

- Python 3.10+
- Node.js 18+
- npm 9+
- Windows / macOS / Linux（`run_rag.bat` 仅 Windows）

## 快速开始

### 1. 克隆并进入项目

```bash
git clone <your-repo-url>
cd RAG
```

### 2. 配置后端

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

创建 `backend/.env`（最少需要可用的 API Key）：

```env
# Embedding
EMBED_BASE_URL=https://api.openai.com/v1
EMBED_API_KEY=your_api_key
EMBED_MODEL=text-embedding-3-small

# Generation
GEN_BASE_URL=https://api.openai.com/v1
GEN_API_KEY=your_api_key
GEN_MODEL=gpt-4o-mini

# Retrieval / chunk
TOP_K=5
CHUNK_SIZE=800
CHUNK_OVERLAP=150

# Storage
SQLITE_URL=sqlite:///./rag_docs.db
CHROMA_PATH=./chroma_db
CHROMA_COLLECTION=rag_knowledge_base

# Task mode: rq | background | inline
PROCESSING_MODE=background
```

启动后端：

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

后端地址：
- API: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`

### 3. 配置前端

```bash
cd ../frontend
npm install
npm run dev
```

前端地址：
- `http://localhost:5173`

### 4. Windows 一键启动（可选）

仓库根目录提供 `run_rag.bat`，会：
- 激活指定 Conda 环境
- 启动后端和前端
- 自动打开浏览器

> 注意：脚本里的 Conda 路径和环境名是本地硬编码，使用前请按你的机器修改。

## 处理模式说明

`PROCESSING_MODE` 支持：

- `background`（默认）：FastAPI BackgroundTasks 异步处理上传文档
- `inline`：上传请求内同步处理，返回更慢但行为直观
- `rq`：通过 Redis + RQ 队列处理（需要额外部署 Redis 与 worker）

当前代码中 `/api/events` 默认返回 `503`（本地环境禁用 SSE 推送），前端主要依赖轮询 `/api/health` 和 `/api/docs` 更新状态。

## API 概览

### 系统

- `GET /api/health`
  - 返回服务状态、文档数、chunk 数、向量数、模型配置等
- `GET /api/events`
  - 当前默认 `503`（SSE 未启用）

### 文档管理

- `GET /api/docs`
  - 获取文档列表（不含 chunk 正文）
- `GET /api/docs/{doc_id}`
  - 获取单文档详情（包含 chunks）
- `POST /api/upload`
  - 上传 PDF，返回 `doc_id`
- `DELETE /api/docs/{doc_id}`
  - 删除文档与对应向量

### 问答

- `POST /api/query`
  - 请求体：

```json
{
  "question": "你的问题",
  "doc_ids": ["可选：指定文档范围"],
  "top_k": 5
}
```

  - 响应为 `application/x-ndjson`，按行返回：
    - `{"type":"meta","retrieved_chunks":[...]}`
    - `{"type":"delta","text":"..."}`
    - `{"type":"error","message":"..."}`（可选）
    - `{"type":"done"}`

## 常见问题

- 上传成功但一直 `processing`
  - 检查 Embedding API 是否可用、Key 是否正确、后端日志是否报错。
- 问答返回“知识库为空”
  - 说明当前 SQLite/Chroma 中没有可检索数据，先上传并等待处理完成。
- 前端显示后端未连接
  - 确认后端监听地址为 `127.0.0.1:8000`，且前端调用地址与之一致。

## 开发建议

- 生产环境建议收敛 CORS 白名单（当前后端为 `allow_origins=["*"]`）
- 若需高并发文档处理，优先切到 `rq` 并部署 Redis + worker
- 可将前端 API 地址改为环境变量，避免硬编码 `http://localhost:8000/api`
