# backend/api.py
"""FastAPI 接口层：把智能体能力暴露给前端。

启动方式（在项目根目录）：
    python frontend/app.py
或：
    uvicorn backend.api:app --reload --port 8000
"""
import json
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

if __package__:
    from backend.client import (
        MODEL,
        AgentError,
        get_history,
        list_sessions,
        reset_session,
        run_agent_turn,
    )
    from backend.server import AVAILABLE_TOOLS
else:  # pragma: no cover - 兼容直接运行 backend/api.py
    from client import MODEL, AgentError, get_history, list_sessions, reset_session, run_agent_turn
    from server import AVAILABLE_TOOLS

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"

app = FastAPI(title="MCP 智能办公助手 API", version="1.0.0")

# ==================== 请求模型 ====================
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="用户自然语言输入")
    session_id: Optional[str] = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]*$",
        description="会话 ID，留空则由服务端新建",
    )


def _sse(event: str, data: dict) -> str:
    """构造一条 SSE 消息。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ==================== 智能体对话 ====================
@app.post("/api/chat")
def chat(req: ChatRequest):
    """非流式接口：一次性返回最终回复与工具调用记录。"""
    try:
        result = run_agent_turn(req.message, session_id=req.session_id)
    except AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"服务异常：{exc}") from exc

    return {
        "session_id": result["session_id"],
        "reply": result["reply"],
        "tool_calls": result["tool_calls"],
    }


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """流式接口（SSE）：实时推送思考状态、工具调用与最终回答。"""
    events: "queue.Queue[tuple[str, dict]]" = queue.Queue()
    session_id = req.session_id or uuid.uuid4().hex

    def worker() -> None:
        try:
            run_agent_turn(
                req.message,
                session_id=session_id,
                on_event=lambda event, data: events.put((event, data)),
            )
        except AgentError as exc:
            events.put(("error", {"message": str(exc)}))
        except Exception as exc:  # noqa: BLE001
            events.put(("error", {"message": f"服务异常：{exc}"}))
        finally:
            events.put(("done", {}))

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        # 先告诉前端本次使用的会话 ID，再持续推送智能体事件
        yield _sse("session", {"session_id": session_id})
        while True:
            try:
                event, data = events.get(timeout=15)
            except queue.Empty:
                yield ": ping\n\n"
                continue

            if event == "done":
                yield _sse("done", {"session_id": session_id})
                break

            yield _sse(event, data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 会话管理 ====================
@app.get("/api/sessions")
def sessions():
    return {"sessions": [{"id": s["id"], "title": s["title"], "updated_at": s["updated_at"]} for s in list_sessions()]}


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    return get_history(session_id)


@app.delete("/api/sessions/{session_id}")
def session_delete(session_id: str):
    reset_session(session_id)
    return {"ok": True}


# ==================== 健康检查 ====================
@app.get("/api/health")
def health():
    model_configured = bool(os.getenv("DASHSCOPE_API_KEY"))
    return {
        "status": "ok" if model_configured else "configuration_required",
        "model_configured": model_configured,
        "model": MODEL,
        "tools": list(AVAILABLE_TOOLS.keys()),
    }


# ==================== 前端静态资源 ====================
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/", include_in_schema=False)
def index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="前端文件不存在")
    return FileResponse(index_file, media_type="text/html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    icon = ASSETS_DIR / "logo.svg"
    if icon.exists():
        return FileResponse(icon, media_type="image/svg+xml")
    raise HTTPException(status_code=404)
