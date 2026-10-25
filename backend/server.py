# backend/server.py
"""MCP 工具服务端：提供文件读写、数学计算、图片视觉识别、SQLite待办管理。"""
import ast
import base64
import mimetypes
import operator as op
import os
import sqlite3
import json
from pathlib import Path
from openai import OpenAI

API_KEY = os.getenv(
    "DASHSCOPE_API_KEY",
    "sk-ws-H.PXMDLYL.VuYv.MEQCIATz2j4r5MBxYptDPOU3T55SIorp8io-lb7N0B7Kk-s2AiAadQ0AfLxM0PuuQemnX9PWKy5SeLr_hmCLQfiSRDEphQ",
)
BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://ws-sry84uag76dm6rj8.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)
VL_MODEL = os.getenv("DASHSCOPE_VL_MODEL", "qwen3.8-omni-flash")

vl_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "workspace_data.db"


def _init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT NOT NULL,
                status TEXT DEFAULT '未完成',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


_init_db()


def read_local_file(file_path: str) -> str:
    """工具 1：读取本地文件的内容"""
    try:
        target = (ROOT_DIR / file_path).resolve()
        if not target.exists():
            return f"错误：找不到文件 '{file_path}'。"
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
        return f"成功读取文件 '{file_path}'，内容如下：\n{content}"
    except Exception as e:
        return f"读取文件时发生错误: {str(e)}"


def write_local_file(file_path: str, content: str) -> str:
    """工具 2：创建或修改本地文本文件/Markdown 报告"""
    try:
        target = (ROOT_DIR / file_path).resolve()
        if ROOT_DIR not in target.parents and target != ROOT_DIR:
            return "错误：出于安全限制，仅允许在项目工作区内创建或修改文件。"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"成功将内容写入文件 '{file_path}'（共 {len(content)} 字符）。"
    except Exception as e:
        return f"写入文件时发生错误: {str(e)}"


_SAFE_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.USub: op.neg,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("不支持的算术表达式")


def simple_calculator(expression: str) -> str:
    """工具 3：安全计算器（基于 AST 语法树解析，杜绝 eval 注入隐患）"""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
        return f"计算表达式 '{expression}' 的结果是: {result}"
    except Exception as e:
        return f"计算出错: {str(e)}"


def analyze_image(image_path: str, question: str = "请详细描述这张图片的内容，如果包含文字或数据请提取出来。") -> str:
    """工具 4：识别与分析图片内容（支持本地路径或上传的图片）"""
    try:
        if image_path.startswith(("http://", "https://")):
            image_url = image_path
        else:
            target = (ROOT_DIR / image_path).resolve()
            if not target.exists():
                return f"错误：找不到图片文件 '{image_path}'。"
            mime_type, _ = mimetypes.guess_type(str(target))
            mime_type = mime_type or "image/png"
            with open(target, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")
            image_url = f"data:{mime_type};base64,{b64_data}"

        response = vl_client.chat.completions.create(
            model=VL_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": question},
                    ],
                }
            ],
        )
        ans = response.choices[0].message.content
        return f"【图片识别结果】（针对 {image_path}）：\n{ans}"
    except Exception as e:
        return f"图片识别失败: {str(e)}"


def manage_todos(action: str, task: str = "", todo_id: int = 0) -> str:
    """工具 5：待办清单管理（基于 SQLite 数据库持久化存储）"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            if action == "add":
                if not task.strip():
                    return "错误：新增待办时 task 内容不能为空。"
                cursor.execute("INSERT INTO todos (task) VALUES (?)", (task.strip(),))
                conn.commit()
                return f"已成功添加待办事项（ID: {cursor.lastrowid}）：{task}"

            elif action == "complete":
                cursor.execute("UPDATE todos SET status = '已完成' WHERE id = ?", (todo_id,))
                conn.commit()
                return f"已将待办事项 #{todo_id} 标记为【已完成】。" if cursor.rowcount else f"未找到 ID 为 {todo_id} 的待办事项。"

            elif action == "delete":
                cursor.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
                conn.commit()
                return f"已删除待办事项 #{todo_id}。" if cursor.rowcount else f"未找到 ID 为 {todo_id} 的待办事项。"

            else:
                cursor.execute("SELECT id, task, status, created_at FROM todos ORDER BY id ASC")
                rows = cursor.fetchall()
                if not rows:
                    return "当前待办清单为空。"
                lines = ["当前 SQLite 数据库中的待办清单："]
                for r_id, r_task, r_status, r_time in rows:
                    icon = "[已完成]" if r_status == "已完成" else "[未完成]"
                    lines.append(f"- #{r_id} {icon} {r_task} （创建于 {r_time}）")
                return "\n".join(lines)
    except Exception as e:
        return f"操作待办数据库出错: {str(e)}"


AVAILABLE_TOOLS = {
    "read_local_file": read_local_file,
    "write_local_file": write_local_file,
    "simple_calculator": simple_calculator,
    "analyze_image": analyze_image,
    "manage_todos": manage_todos,
}


def execute_tool(tool_name: str, arguments: dict) -> str:
    if tool_name not in AVAILABLE_TOOLS:
        return f"错误：未找到名为 '{tool_name}' 的工具。"
    tool_func = AVAILABLE_TOOLS[tool_name]
    return tool_func(**arguments)


if __name__ == "__main__":
    print("MCP Server 工具服务端已就绪，当前已注册工具：", list(AVAILABLE_TOOLS.keys()))