import { useState, useRef, useCallback, useEffect } from "react";
import "./App.css";

const THEME_STORAGE_KEY = "rag-theme";

// ─── API Client ────────────────────────────────────────────
const API_BASE = "http://localhost:8000/api";
const EVENTS_URL = "http://localhost:8000/api/events";

const api = {
  async uploadPDF(file) {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || "上传失败");
    }
    const data = await res.json();
    return {
      message: data.message,
      docId: data.doc_id,
    };
  },
  getDocs: async function () {
    const res = await fetch(`${API_BASE}/docs`);
    if (!res.ok) throw new Error("获取文档列表失败");

    const data = await res.json();

    return {
      docs: (data.docs || []).map(d => ({
        id: d.id,
        title: d.title,
        fileName: d.file_name,
        uploadedAt: d.uploaded_at,
        status: d.status,
        chunkCount: d.chunk_count,
        totalChars: d.total_chars,
      })),
    };
  },
  async getDoc(id) {
    const res = await fetch(`${API_BASE}/docs/${id}`);
    if (!res.ok) throw new Error("获取文档失败");
    const data = await res.json();
    const d = data.doc || {};
    return {
      doc: {
        id: d.id,
        title: d.title,
        fileName: d.file_name,
        uploadedAt: d.uploaded_at,
        totalChars: d.total_chars,
        chunks: (d.chunks || []).map(c => ({
          id: c.id,
          title: c.title,
          content: c.content,
          page: c.page,
          charStart: c.char_start,
        })),
      },
    };
  },
  async deleteDoc(id) {
    const res = await fetch(`${API_BASE}/docs/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error("删除失败");
    return res.json();
  },
  async queryStream(question, { onMeta, onDelta, onError, onDone }) {
    const res = await fetch(`${API_BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || "问答失败");
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error("响应不支持流式读取");
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (!line) continue;
        let payload;
        try {
          payload = JSON.parse(line);
        } catch {
          continue;
        }
        if (payload.type === "meta") onMeta?.(payload);
        else if (payload.type === "delta") onDelta?.(payload.text || "");
        else if (payload.type === "error") onError?.(payload.message || "生成失败");
        else if (payload.type === "done") onDone?.();
      }
    }

    buffer += decoder.decode();
    const tail = buffer.trim();
    if (tail) {
      try {
        const payload = JSON.parse(tail);
        if (payload.type === "meta") onMeta?.(payload);
        else if (payload.type === "delta") onDelta?.(payload.text || "");
        else if (payload.type === "error") onError?.(payload.message || "生成失败");
        else if (payload.type === "done") onDone?.();
      } catch {
      }
    }
  },
  async health() {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error("服务不可用");
    return res.json();
  },
};

function UploadZone({ onUpload, isProcessing }) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef();
  const handle = useCallback((files) => {
    const pdfs = Array.from(files).filter(f => f.type === "application/pdf");
    if (pdfs.length) onUpload(pdfs);
  }, [onUpload]);

  return (
    <div
      onDragOver={e => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => { e.preventDefault(); setDragOver(false); handle(e.dataTransfer.files); }}
      onClick={() => !isProcessing && inputRef.current?.click()}
      style={{
        border: `2px dashed ${dragOver ? "var(--accent)" : "var(--border-soft)"}`,
        borderRadius: "14px",
        padding: "28px 16px",
        textAlign: "center",
        cursor: isProcessing ? "not-allowed" : "pointer",
        background: dragOver ? "var(--upload-active-bg)" : "var(--upload-idle-bg)",
        transition: "all 0.3s",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        multiple
        style={{ display: "none" }}
        onChange={e => handle(e.target.files)}
      />
      <div style={{ fontSize: "42px", marginBottom: "10px" }}>{isProcessing ? "⏳" : "📤"}</div>
      <div style={{ color: isProcessing ? "var(--accent)" : "var(--text-muted)", fontSize: "14px", fontFamily: "'Space Mono', monospace" }}>
        {isProcessing
          ? <span style={{ animation: "pulse 1.5s infinite", display: "block" }}>正在上传 & 解析…</span>
          : <><div style={{ color: "var(--text)", fontWeight: "700", marginBottom: "4px" }}>拖拽 PDF 到此处</div><div>或点击选择文件</div></>}
      </div>
    </div>
  );
}

function DocCard({ doc, onRemove }) {
  const [expanded, setExpanded] = useState(false);
  const [chunks, setChunks] = useState(null);
  const [loading, setLoading] = useState(false);

  const toggleExpand = async () => {
    if (!expanded && !chunks) {
      setLoading(true);
      try {
        const data = await api.getDoc(doc.id);
        setChunks(data.doc.chunks);
      } catch {
        setChunks([]);
      }
      setLoading(false);
    }
    setExpanded(v => !v);
  };

  return (
    <div style={{ background: "var(--panel-soft)", border: "1px solid var(--border-soft)", borderRadius: "10px", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", padding: "12px 14px", gap: "8px" }}>
        <span style={{ fontSize: "16px" }}>📎</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: "var(--text)", fontWeight: "600", fontSize: "14px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.title}</div>
          <div style={{ color: "var(--text-muted)", fontSize: "12px", fontFamily: "monospace", marginTop: "4px" }}>
            {doc.status === "failed" ? "失败" : doc.status === "processing" ? "处理中" : `${doc.chunkCount} 片段`} / {new Date(doc.uploadedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
          </div>
        </div>
        <button onClick={toggleExpand} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "14px" }}>
          {loading ? "…" : expanded ? "▾" : "▸"}
        </button>
        <button onClick={() => onRemove(doc.id)} style={{ background: "none", border: "none", color: "#663344", cursor: "pointer", fontSize: "16px" }}>✕</button>
      </div>
      {expanded && (
        <div style={{ borderTop: "1px solid var(--border-soft)", maxHeight: "250px", overflowY: "auto" }}>
          {(chunks || []).map(c => (
            <div key={c.id} style={{ padding: "10px 14px", borderBottom: "1px solid var(--border-subtle)" }}>
              <div style={{ color: "var(--accent)", fontSize: "12px", marginBottom: "4px" }}>
                {c.title}{c.page ? ` / P${c.page}` : ""}
              </div>
              <div style={{ color: "var(--text-soft)", fontSize: "13px", lineHeight: "1.6", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                {c.content}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RetrievedChunk({ chunk, index }) {
  const color = chunk.relevanceScore >= 80 ? "var(--accent)" : chunk.relevanceScore >= 60 ? "#f59e0b" : "#6b7280";
  return (
    <div style={{
      background: "var(--panel-softer)",
      border: `1px solid ${color}44`,
      borderRadius: "12px",
      padding: "16px",
      animation: `slideIn 0.4s ease ${index * 0.1}s both`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "12px" }}>
        <div>
          <div style={{ color: "var(--text)", fontWeight: "600", fontSize: "15px", marginBottom: "4px" }}>{chunk.title}</div>
          <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>来源：{chunk.docTitle}{chunk.page ? ` P${chunk.page}` : ""}</div>
        </div>
        <div style={{ background: `${color}22`, color, padding: "4px 12px", borderRadius: "20px", fontSize: "14px", fontWeight: "700", fontFamily: "monospace", whiteSpace: "nowrap", height: "fit-content" }}>
          {chunk.relevanceScore}%
        </div>
      </div>
      <div style={{ background: "var(--chunk-content-bg)", borderRadius: "8px", padding: "14px", color: "var(--text-soft)", fontSize: "14px", lineHeight: "1.8", maxHeight: "150px", overflowY: "auto", marginBottom: "10px", fontFamily: "Georgia, serif" }}>
        {chunk.content}
      </div>
      <div style={{ color: "var(--text-muted)", fontSize: "12px", fontStyle: "italic" }}>distance: {chunk.distance}</div>
    </div>
  );
}

function ChatMessage({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{ display: "flex", flexDirection: isUser ? "row-reverse" : "row", gap: "12px", animation: "slideIn 0.3s ease both" }}>
      <div style={{ width: "36px", height: "36px", borderRadius: "50%", background: isUser ? "linear-gradient(135deg,#6366f1,#8b5cf6)" : "linear-gradient(135deg,var(--accent),#0f766e)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "16px", flexShrink: 0 }}>
        {isUser ? "🤔" : "🤖"}
      </div>
      <div style={{
        maxWidth: "80%",
        background: isUser ? "var(--message-user-bg)" : "var(--message-bot-bg)",
        border: isUser ? "1px solid var(--message-user-border)" : "1px solid var(--border-soft)",
        borderRadius: isUser ? "16px 4px 16px 16px" : "4px 16px 16px 16px",
        padding: "14px 18px",
        color: "var(--text-strong)",
        fontSize: "15px",
        lineHeight: "1.8",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}>
        {msg.content}
        {msg.streaming && <span style={{ opacity: 0.6 }}>▍</span>}
      </div>
    </div>
  );
}

function StatusBadge({ health }) {
  if (!health) return (
    <div style={{ background: "var(--badge-idle-bg)", border: "1px solid var(--border-soft)", borderRadius: "20px", padding: "6px 16px", fontSize: "13px", color: "var(--text-muted)" }}>
      连接中…
    </div>
  );
  return (
    <div style={{ background: "var(--accent-soft-bg)", border: "1px solid var(--accent-border)", borderRadius: "20px", padding: "6px 16px", fontSize: "13px", color: "var(--accent)" }}>
      ● {health.docs} 文档 / {health.chunks} 片段
    </div>
  );
}

export default function RAGSystem() {
  const [themeMode, setThemeMode] = useState(() => localStorage.getItem(THEME_STORAGE_KEY) || "dark");
  const [docs, setDocs] = useState([]);
  const [health, setHealth] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingFile, setProcessingFile] = useState("");
  const [messages, setMessages] = useState([{
    role: "assistant",
    content: "你好！小助手随时为你服务，请先上传 PDF 文件构建知识库，然后向我提问，后端服务已启动。",
  }]);
  const [retrievedChunks, setRetrievedChunks] = useState([]);
  const [chunkPage, setChunkPage] = useState(1);
  const CHUNKS_PER_PAGE = 3;
  const [query, setQuery] = useState("");
  const [isQuerying, setIsQuerying] = useState(false);
  const [serverError, setServerError] = useState(false);
  const chatEndRef = useRef();
  const isDarkMode = themeMode === "dark";

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, themeMode);
    document.documentElement.setAttribute("data-theme", themeMode);
  }, [themeMode]);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const h = await api.health();
        setHealth(h);
        setServerError(false);
      } catch {
        setServerError(true);
        setHealth(null);
      }
    };
    const fetchDocs = async () => {
      try {
        const data = await api.getDocs();
        setDocs(data.docs);
      } catch {
      }
    };
    fetchHealth();
    fetchDocs();
    const id = setInterval(() => { fetchHealth(); fetchDocs(); }, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const es = new EventSource(EVENTS_URL);
    const onStatus = (ev) => {
      let payload;
      try {
        payload = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!payload || payload.type !== "doc_status") return;
      const { doc_id, status, title, chunk_count, total_chars, error } = payload;
      setDocs(prev => prev.map(d => d.id === doc_id ? {
        ...d,
        status: status || d.status,
        title: title || d.title,
        chunkCount: typeof chunk_count === "number" ? chunk_count : d.chunkCount,
        totalChars: typeof total_chars === "number" ? total_chars : d.totalChars,
      } : d));
      if (status === "completed") {
        setMessages(prev => [...prev, { role: "assistant", content: `✅ 处理完成：${title || doc_id}` }]);
      } else if (status === "failed") {
        setMessages(prev => [...prev, { role: "assistant", content: `❌ 处理失败：${title || doc_id}${error ? `（${error}）` : ""}` }]);
      }
    };
    es.addEventListener("doc_status", onStatus);
    es.onerror = () => {};
    return () => {
      es.removeEventListener("doc_status", onStatus);
      es.close();
    };
  }, []);

  const handleUpload = async (files) => {
    setIsProcessing(true);
    for (const file of files) {
      setProcessingFile(file.name);
      try {
        const data = await api.uploadPDF(file);
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `✅ ${data.message || "上传成功，正在处理"}：${file.name}`,
        }]);
        const list = await api.getDocs();
        setDocs(list.docs);
      } catch (err) {
        setMessages(prev => [...prev, { role: "assistant", content: `❌ 上传「${file.name}」失败：${err.message}` }]);
      }
    }
    setIsProcessing(false);
    setProcessingFile("");
  };

  const handleRemove = async (id) => {
    try {
      await api.deleteDoc(id);
      setDocs(prev => prev.filter(d => d.id !== id));
      const h = await api.health();
      setHealth(h);
    } catch (err) {
      alert("删除失败：" + err.message);
    }
  };

  const handleQuery = async () => {
    if (!query.trim() || isQuerying) return;
    const userMsg = query;
    setQuery("");
    setIsQuerying(true);
    setMessages(prev => [...prev, { role: "user", content: userMsg }]);
    setRetrievedChunks([]);
    setChunkPage(1);

    try {
      const streamId = `stream_${Date.now()}`;

      await api.queryStream(userMsg, {
        onMeta: (payload) => {
          const raw = payload.retrieved_chunks || [];
          const normalized = raw.map((c) => ({
            ...c,
            docTitle: c.docTitle ?? c.doc_title,
            docId: c.docId ?? c.doc_id,
            relevanceScore: typeof c.relevanceScore === "number"
              ? c.relevanceScore
              : (typeof c.relevance_score === "number" ? c.relevance_score : Number(c.relevance_score)),
          }));
          setRetrievedChunks(normalized);
        },
        onDelta: (text) => {
          if (!text) return;
          setMessages(prev => {
            const exists = prev.some(m => m.id === streamId);
            if (!exists) {
              return [...prev, { id: streamId, role: "assistant", content: text, streaming: true }];
            }
            return prev.map(m => m.id === streamId ? { ...m, content: (m.content || "") + text } : m);
          });
        },
        onError: (message) => {
          setMessages(prev => {
            const exists = prev.some(m => m.id === streamId);
            if (!exists) {
              return [...prev, { id: streamId, role: "assistant", content: `❌ ${message}`, streaming: false }];
            }
            return prev.map(m => m.id === streamId ? { ...m, content: m.content + `\n\n❌ ${message}`, streaming: false } : m);
          });
        },
        onDone: () => {
          setMessages(prev => prev.map(m => m.id === streamId ? { ...m, streaming: false } : m));
        },
      });
    } catch (err) {
      setMessages(prev => [...prev, { role: "assistant", content: `❌ 问答失败：${err.message}` }]);
    }
    setIsQuerying(false);
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--app-bg)", fontFamily: "'Space Mono', monospace", color: "var(--text)", display: "flex", flexDirection: "column", transition: "background .25s ease,color .25s ease" }}>
      <div style={{ padding: "18px 28px", borderBottom: "1px solid var(--border)", background: "var(--header-bg)", backdropFilter: "blur(12px)", display: "flex", alignItems: "center", gap: "16px", position: "sticky", top: 0, zIndex: 100 }}>
        <div style={{ width: "42px", height: "42px", background: "linear-gradient(135deg,var(--accent),#0f766e)", borderRadius: "10px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "20px", animation: "glow 3s ease infinite" }}>⚙</div>
        <div>
          <div style={{ fontWeight: "700", fontSize: "18px", letterSpacing: ".05em" }}>RAG 知识库问答系统</div>
          <div style={{ color: "var(--text-muted)", fontSize: "12px", marginTop: "4px" }}>
            Retrieval-Augmented Generation
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: "10px", alignItems: "center" }}>
          <button
            onClick={() => setThemeMode(prev => prev === "dark" ? "light" : "dark")}
            style={{
              background: "var(--badge-idle-bg)",
              border: "1px solid var(--border-soft)",
              borderRadius: "999px",
              padding: "8px 14px",
              fontSize: "13px",
              color: "var(--text-strong)",
              cursor: "pointer",
            }}
          >
            {isDarkMode ? "☀ 白天模式" : "🌙 黑夜模式"}
          </button>
          {serverError && (
            <div style={{ background: "rgba(239,68,68,.1)", border: "1px solid rgba(239,68,68,.3)", borderRadius: "20px", padding: "6px 14px", fontSize: "13px", color: "#ef4444" }}>
              ⚠ 后端未连接
            </div>
          )}
          <StatusBadge health={health} />
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", overflow: "hidden", height: "calc(100vh - 80px)" }}>
        <div style={{ width: "300px", flexShrink: 0, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", background: "var(--sidebar-bg)" }}>
          <div style={{ padding: "20px 18px 16px", borderBottom: "1px solid var(--border)" }}>
            <div style={{ fontSize: "12px", color: "var(--text-muted)", letterSpacing: ".12em", marginBottom: "14px", fontWeight: "bold" }}>● 知识库管理</div>
            <UploadZone onUpload={handleUpload} isProcessing={isProcessing} />
            {isProcessing && processingFile && (
              <div style={{ marginTop: "10px", color: "var(--accent)", fontSize: "12px", textAlign: "center", animation: "pulse 1.5s infinite" }}>
                ⏳ {processingFile}
              </div>
            )}
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "14px" }}>
            {docs.length === 0 ? (
              <div style={{ textAlign: "center", color: "var(--empty-text)", padding: "40px 16px", fontSize: "13px" }}>
                <div style={{ fontSize: "32px", marginBottom: "10px", color: "var(--border-soft)" }}>📭</div>
                知识库为空<br />上传 PDF 开始构建
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {docs.map(doc => <DocCard key={doc.id} doc={doc} onRemove={handleRemove} />)}
              </div>
            )}
          </div>
          <div style={{ padding: "16px 18px", borderTop: "1px solid var(--border)" }}>
            <div style={{ fontSize: "12px", color: "var(--text-muted)", letterSpacing: ".12em", marginBottom: "12px", fontWeight: "bold" }}>● 统计</div>
            {[
              ["文档", docs.length, "var(--stat-doc, var(--accent))"],
              ["片段", health?.chunks ?? 0, "var(--stat-chunk, #0094ff)"],
              ["问答", messages.filter(m => m.role === "user").length, "var(--stat-qa, #f59e0b)"],
            ].map(([l, v, c]) => (
              <div key={l} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                <span style={{ color: "var(--text-muted)", fontSize: "13px" }}>{l}</span>
                <span style={{ color: c, fontWeight: "700", fontSize: "14px" }}>{v}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 3, display: "flex", flexDirection: "column", borderRight: "1px solid var(--border)", overflow: "hidden" }}>
          <div style={{ padding: "12px 24px", borderBottom: "1px solid var(--border)", background: "var(--header-soft)", fontSize: "14px", color: "var(--text-muted)", fontWeight: "bold", letterSpacing: "0.05em" }}>
            💬 智能对话
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "28px", display: "flex", flexDirection: "column", gap: "20px" }}>
            {messages.map((msg, i) => <ChatMessage key={i} msg={msg} />)}
            {isQuerying && (
              <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "50%", background: "linear-gradient(135deg,var(--accent),#0f766e)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "16px" }}>🤖</div>
                <div style={{ display: "flex", gap: "6px", padding: "14px 18px", background: "var(--message-bot-bg)", borderRadius: "4px 16px 16px 16px", border: "1px solid var(--border)" }}>
                  {[0, 0.2, 0.4].map(d => <div key={d} style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--accent)", animation: `pulse 1.2s ${d}s infinite` }} />)}
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <div style={{ padding: "18px 28px", borderTop: "1px solid var(--border)", background: "var(--panel-strong)" }}>
            <div className="query-input-wrap" style={{ display: "flex", gap: "12px", background: "var(--panel-soft)", border: "1px solid var(--border)", borderRadius: "14px", padding: "12px 16px" }}>
              <textarea
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleQuery(); } }}
                placeholder="向知识库提问… (Enter 发送，Shift+Enter 换行)"
                rows={2}
                style={{ flex: 1, background: "none", border: "none", color: "var(--text-strong)", fontSize: "15px", fontFamily: "'Space Mono', monospace", resize: "none", lineHeight: "1.6" }}
              />
              <button
                onClick={handleQuery}
                disabled={isQuerying || !query.trim()}
                style={{ width: "44px", height: "44px", background: isQuerying || !query.trim() ? "var(--disabled-bg)" : "var(--accent)", border: "none", borderRadius: "12px", cursor: isQuerying || !query.trim() ? "not-allowed" : "pointer", fontSize: "18px", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "all .2s", alignSelf: "flex-end", color: isQuerying || !query.trim() ? "var(--text-muted)" : "#fff" }}
              >
                {isQuerying ? <span style={{ animation: "spin 1s linear infinite", display: "block" }}>⟳</span> : "→"}
              </button>
            </div>
          </div>
        </div>

        <div style={{ flex: 2, display: "flex", flexDirection: "column", background: "var(--right-bg)", overflow: "hidden" }}>
          <div style={{ padding: "12px 24px", borderBottom: "1px solid var(--border)", background: "var(--header-soft)", fontSize: "14px", color: "var(--text-muted)", fontWeight: "bold", letterSpacing: "0.05em" }}>
            📄 检索片段 {retrievedChunks.length > 0 ? `(共 ${retrievedChunks.length} 条)` : ""}
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "28px" }}>
            {retrievedChunks.length === 0 ? (
              <div style={{ textAlign: "center", color: "var(--empty-text)", padding: "80px 20px", fontSize: "14px" }}>
                <div style={{ fontSize: "42px", marginBottom: "14px", color: "var(--border-soft)" }}>⚙</div>
                暂无检索结果<br />提问后将在此显示相关文档片段
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div style={{ color: "var(--text-muted)", fontSize: "12px", letterSpacing: ".1em", marginBottom: "6px", fontWeight: "bold" }}>
                  ● 按相关性排序的上下文
                </div>

                {[...retrievedChunks]
                  .sort((a, b) => b.relevanceScore - a.relevanceScore)
                  .slice((chunkPage - 1) * CHUNKS_PER_PAGE, chunkPage * CHUNKS_PER_PAGE)
                  .map((chunk, i) => (
                    <RetrievedChunk key={`${chunkPage}-${i}`} chunk={chunk} index={i} />
                  ))}

                {retrievedChunks.length > CHUNKS_PER_PAGE && (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "12px", borderTop: "1px dashed var(--border)", paddingTop: "16px" }}>
                    <button
                      onClick={() => setChunkPage(p => Math.max(1, p - 1))}
                      disabled={chunkPage === 1}
                      style={{ background: chunkPage === 1 ? "var(--disabled-bg)" : "var(--accent-soft-bg)", color: chunkPage === 1 ? "var(--text-muted)" : "var(--accent)", border: "none", padding: "6px 14px", borderRadius: "8px", cursor: chunkPage === 1 ? "not-allowed" : "pointer", fontSize: "13px", transition: "all .2s" }}
                    >
                      ← 上一页
                    </button>
                    <span style={{ color: "var(--text-muted)", fontSize: "13px", fontFamily: "monospace" }}>
                      {chunkPage} / {Math.ceil(retrievedChunks.length / CHUNKS_PER_PAGE)}
                    </span>
                    <button
                      onClick={() => setChunkPage(p => Math.min(Math.ceil(retrievedChunks.length / CHUNKS_PER_PAGE), p + 1))}
                      disabled={chunkPage === Math.ceil(retrievedChunks.length / CHUNKS_PER_PAGE)}
                      style={{ background: chunkPage === Math.ceil(retrievedChunks.length / CHUNKS_PER_PAGE) ? "var(--disabled-bg)" : "var(--accent-soft-bg)", color: chunkPage === Math.ceil(retrievedChunks.length / CHUNKS_PER_PAGE) ? "var(--text-muted)" : "var(--accent)", border: "none", padding: "6px 14px", borderRadius: "8px", cursor: chunkPage === Math.ceil(retrievedChunks.length / CHUNKS_PER_PAGE) ? "not-allowed" : "pointer", fontSize: "13px", transition: "all .2s" }}
                    >
                      下一页 →
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
