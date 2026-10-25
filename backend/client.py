# backend/client.py
import json
import os
import threading
import time
import uuid
from typing import Callable, Optional

from openai import OpenAI

try:
    if __package__:
        from backend.server import AVAILABLE_TOOLS, execute_tool
    else:
        from server import AVAILABLE_TOOLS, execute_tool
except ImportError:
    from server import AVAILABLE_TOOLS, execute_tool

API_KEY = os.getenv(
    "DASHSCOPE_API_KEY",
    "sk-ws-H.PXMDLYL.VuYv.MEQCIATz2j4r5MBxYptDPOU3T55SIorp8io-lb7N0B7Kk-s2AiAadQ0AfLxM0PuuQemnX9PWKy5SeLr_hmCLQfiSRDEphQ",
)
BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://ws-sry84uag76dm6rj8.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)
MODEL = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

MAX_TOOL_ROUNDS = 5
MAX_MESSAGES_PER_SESSION = 40
MAX_SESSIONS = 100

SYSTEM_PROMPT = (
    "你是「MCP 智能办公助手」，一个具备语言交互（能说）和行动执行（会做）的全能型 AI 智能体。\n"
    "行为准则：\n"
    "1. 用简洁、友好的中文回答，善用 Markdown 排版。\n"
    "2. 当用户的需求涉及：读取/创建本地文件、数学计算、识别/分析图片、管理待办清单（Todo）时，必须调用对应工具，严禁凭空编造。\n"
    "3. 如果用户上传了图片（提示中包含图片路径如 uploads/xxx.png），请主动调用 `analyze_image` 工具识别图片内容。\n"
    "4. 拿到工具结果后，用自然、有条理的语言向用户总结结论；若工具报错，请说明原因并给出建议。\n"
    "5. 保持多轮对话上下文连贯，记住用户之前交代的信息。"
)

tools_declaration = [
    {
        "type": "function",
        "function": {
            "name": "read_local_file",
            "description": "当用户需要读取本地文本文件、查看代码或文档内容时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "相对项目根目录的文件路径，如 'README.md'"}
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_local_file",
            "description": "当用户要求创建、保存、修改本地文件、生成日程表或导出 Markdown 报告时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "要保存的文件路径，如 'plan.md'"},
                    "content": {"type": "string", "description": "要写入文件的完整文本内容"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simple_calculator",
            "description": "当用户需要进行数学计算、算术求解时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "纯数学算术表达式，如 '(1024 * 8) + 256'"}
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": "当用户要求识别图片、提取图片文字(OCR)、分析图片内容，或消息中附带了图片路径时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "本地图片路径（如 'uploads/xxx.png'）或图片 URL"},
                    "question": {"type": "string", "description": "需要针对该图片回答的具体问题或识别要求"},
                },
                "required": ["image_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_todos",
            "description": "管理用户的待办事项清单（SQLite数据库）。支持查看、添加、完成、删除待办任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "complete", "delete"],
                        "description": "操作类型：list(查询列表), add(新增任务), complete(完成任务), delete(删除任务)",
                    },
                    "task": {"type": "string", "description": "当 action 为 add 时，填写待办任务的具体描述"},
                    "todo_id": {"type": "integer", "description": "当 action 为 complete 或 delete 时，填写任务的 ID"},
                },
                "required": ["action"],
            },
        },
    },
]


class AgentError(RuntimeError):
    """智能体执行过程中可展示给用户的错误。"""


class ChatSession:
    def __init__(self, session_id: Optional[str] = None):
        self.id = session_id or uuid.uuid4().hex
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.lock = threading.Lock()
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.display = []

    def title(self) -> str:
        for item in self.display:
            if item.get("role") == "user":
                text = " ".join(str(item.get("content", "")).split())
                return text[:24] + ("…" if len(text) > 24 else "")
        return "新对话"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.display,
        }


_sessions = {}
_sessions_lock = threading.Lock()


def get_session(session_id: Optional[str] = None) -> ChatSession:
    with _sessions_lock:
        if session_id and session_id in _sessions:
            return _sessions[session_id]

        session = ChatSession(session_id if session_id else None)
        _sessions[session.id] = session

        if len(_sessions) > MAX_SESSIONS:
            oldest = sorted(_sessions.values(), key=lambda s: s.updated_at)
            for item in oldest[: len(_sessions) - MAX_SESSIONS]:
                _sessions.pop(item.id, None)
        return session


def get_history(session_id: str) -> dict:
    session = get_session(session_id)
    return session.to_dict()


def reset_session(session_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)


def list_sessions() -> list:
    with _sessions_lock:
        items = sorted(_sessions.values(), key=lambda s: s.updated_at, reverse=True)
        return [s.to_dict() for s in items]


def _trim_context(session: ChatSession) -> None:
    if len(session.messages) <= MAX_MESSAGES_PER_SESSION:
        return
    cut = len(session.messages) - MAX_MESSAGES_PER_SESSION
    while cut < len(session.messages) and session.messages[cut].get("role") != "user":
        cut += 1
    if cut < len(session.messages):
        session.messages = [session.messages[0]] + session.messages[cut:]
    session.display = session.display[-MAX_MESSAGES_PER_SESSION:]


EventCallback = Callable[[str, dict], None]


def _noop(_event: str, _data: dict) -> None:
    pass


def run_agent_turn(
    user_prompt: str,
    session_id: Optional[str] = None,
    on_event: Optional[EventCallback] = None,
) -> dict:
    prompt = (user_prompt or "").strip()
    if not prompt:
        raise AgentError("请输入内容后再发送。")

    emit = on_event or _noop
    session = get_session(session_id)

    with session.lock:
        session.messages.append({"role": "user", "content": prompt})
        session.display.append({"role": "user", "content": prompt, "ts": time.time()})
        session.updated_at = time.time()

        tool_records = []
        emit("status", {"stage": "thinking"})

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=session.messages,
                    tools=tools_declaration,
                    tool_choice="auto",
                )
            except Exception as exc:
                raise AgentError(f"大模型调用失败：{exc}") from exc

            message = response.choices[0].message

            if message.tool_calls:
                assistant_message = {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments or "{}",
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
                session.messages.append(assistant_message)

                for call in message.tool_calls:
                    name = call.function.name
                    try:
                        arguments = json.loads(call.function.arguments or "{}")
                        if not isinstance(arguments, dict):
                            arguments = {}
                    except json.JSONDecodeError:
                        arguments = {}

                    emit("tool_call", {"id": call.id, "name": name, "arguments": arguments})

                    try:
                        result = str(execute_tool(name, arguments))
                    except Exception as exc:
                        result = f"工具执行失败：{exc}"
                    result = _clip_tool_result(result)

                    record = {
                        "id": call.id,
                        "name": name,
                        "arguments": arguments,
                        "result": result,
                    }
                    tool_records.append(record)
                    session.messages.append(
                        {"role": "tool", "tool_call_id": call.id, "content": result}
                    )
                    emit("tool_result", record)

                emit("status", {"stage": "planning"})
                continue

            reply = message.content or "抱歉，我暂时没有生成有效回复。"
            session.messages.append({"role": "assistant", "content": reply})
            session.display.append(
                {
                    "role": "assistant",
                    "content": reply,
                    "tool_calls": tool_records,
                    "ts": time.time(),
                }
            )
            session.updated_at = time.time()
            _trim_context(session)
            emit("answer", {"content": reply})
            return {"reply": reply, "tool_calls": tool_records, "session_id": session.id}

        reply = "这个问题需要连续调用太多次工具，我先停在这里。可以拆成几个小任务再试试。"
        session.messages.append({"role": "assistant", "content": reply})
        session.display.append(
            {
                "role": "assistant",
                "content": reply,
                "tool_calls": tool_records,
                "ts": time.time(),
            }
        )
        session.updated_at = time.time()
        _trim_context(session)
        emit("answer", {"content": reply})
        return {"reply": reply, "tool_calls": tool_records, "session_id": session.id}


def _clip_tool_result(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（内容过长，已截断，原长度 {len(text)} 字符）"


def run_agent(user_prompt: str, session_id: str = "cli") -> str:
    print(f"\n【用户输入】: {user_prompt}")

    def print_event(event: str, data: dict) -> None:
        if event == "status":
            print("【AI 决策】: 正在思考…" if data.get("stage") == "thinking" else "【AI 决策】: 正在整理工具结果…")
        elif event == "tool_call":
            print(f"【正在执行工具】: {data['name']}，参数: {data['arguments']}")
        elif event == "tool_result":
            print(f"【工具返回结果】: {data['result']}")

    result = run_agent_turn(user_prompt, session_id=session_id, on_event=print_event)
    print(f"【AI 最终回复】: {result['reply']}")
    return result["reply"]


if __name__ == "__main__":
    print("可用 MCP 工具:", ", ".join(AVAILABLE_TOOLS))
    run_agent("帮我计算一下 1024 乘以 8 是多少？", session_id="demo")