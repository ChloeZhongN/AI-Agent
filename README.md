# AI Agent & MCP 智能体大作业项目

本项目构建了一个基于 **Python + Model Context Protocol (MCP) 思路 + 通义千问** 的智能办公/科研助手。

> 当前版本通过 OpenAI 兼容函数调用驱动本地 Python 工具注册表，采用 MCP 风格的工具流程，但尚未启动独立的 MCP 协议服务端。

它既**能说**——支持自然语言多轮对话；也**会做**——能自主判断并调用本地工具（读取文件、数学计算），再结合工具结果生成最终答复。

---

## 1. 需求描述

用户希望用一句自然语言完成办公场景中的小任务，例如：

- “帮我计算 (1024 × 8 + 256) ÷ 16”
- “读取 README.md，并总结这个项目做了什么”
- “先读 requirements.txt，再告诉我需要安装哪些依赖”

智能体需要理解意图、决定是否调用工具、执行工具，并把结果整理成易读的回答。

## 2. 业务流描述

```text
用户输入
   │
   ▼
前端（网页）──POST /api/chat/stream──▶ FastAPI 接口层
                                        │
                                        ▼
                              大模型意图理解（qwen-plus）
                                   │            │
                              无需工具       需要工具
                                   │            ▼
                                   │      MCP 工具执行器
                                   │      ├─ read_local_file
                                   │      └─ simple_calculator
                                   │            │
                                   │     工具结果回传大模型
                                   │            │
                                   ▼            ▼
                              流式返回回答 / 工具调用轨迹
                                        │
                                        ▼
                              前端 Markdown 渲染 + 语音朗读
```

会话历史保存在服务端内存中，同一个 `session_id` 的多轮对话会携带上下文，实现**多轮对话记忆**。

## 3. 功能特性

| 能力 | 说明 |
| --- | --- |
| 自然语言对话 | 通义千问 `qwen-plus`，支持 Markdown 回答 |
| MCP 工具调用 | 自动决策调用 `read_local_file` / `simple_calculator` |
| 多轮对话记忆 | 服务端按 `session_id` 保存上下文，历史对话可切换 |
| 流式反馈 | SSE 实时展示“思考 → 调工具 → 整理结果”的全过程 |
| 工具可视化 | 前端展示工具名称、参数、返回值，可展开/折叠 |
| 语音输入 | 浏览器 Web Speech API，中文语音转文字 |
| 语音朗读 | 自动朗读 / 单条朗读，可随时关闭 |
| 会话管理 | 新建、切换、删除会话，最近记录本地持久化 |
| 界面体验 | 深浅色主题、响应式布局、代码复制、消息复制 |

## 4. 项目结构

```text
AI-Agent/
├── backend/
│   ├── server.py          # MCP 工具定义与执行器
│   ├── client.py          # 大模型对话 + 工具调度 + 会话记忆
│   └── api.py             # FastAPI 接口层（REST + SSE）
├── frontend/
│   ├── app.py             # 一键启动脚本（API + 前端）
│   ├── index.html         # 页面结构
│   └── assets/
│       ├── styles.css     # 界面样式
│       ├── app.js         # 对话、SSE、Markdown、语音交互
│       └── logo.svg
├── tests/
├── requirements.txt
└── README.md
```

## 5. 快速开始

### 5.1 安装依赖

```bash
pip install -r requirements.txt
```

### 5.2 启动（推荐）

在项目根目录执行：

```bash
python frontend/app.py
```

脚本会自动启动 FastAPI 服务并打开浏览器：

- 前端页面：<http://127.0.0.1:8000>
- 接口文档：<http://127.0.0.1:8000/docs>

可选参数：

```bash
python frontend/app.py --port 8080 --no-browser
python frontend/app.py --reload        # 开发时热重载
```

### 5.3 其他启动方式

```bash
# 仅启动 API（前端静态文件也由它托管）
uvicorn backend.api:app --reload --port 8000

# 命令行体验智能体
python -m backend.client
```

### 5.4 配置大模型（必需）

启动前必须通过环境变量提供阿里云百炼 API Key。密钥不应写入源代码、README 或提交到 Git：

```powershell
# PowerShell
$env:DASHSCOPE_API_KEY="你的 API Key"
# 仅在使用自定义兼容接口时设置：
$env:DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:DASHSCOPE_MODEL="qwen-plus"
python frontend/app.py
```

```bash
# macOS / Linux
export DASHSCOPE_API_KEY="你的 API Key"
python frontend/app.py
```

如果 API Key 曾经提交到公开仓库，请先在百炼控制台撤销并重新生成。删除当前代码里的密钥不会清除 Git 历史。

> 语音输入需要浏览器授权麦克风；建议使用 Chrome / Edge，并通过 `http://127.0.0.1` 访问（`file://` 方式打开无法调用接口）。

## 6. 接口说明

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查，返回模型与可用工具 |
| `POST` | `/api/chat` | 非流式对话，返回最终回复与工具记录 |
| `POST` | `/api/chat/stream` | 流式对话（SSE） |
| `GET` | `/api/sessions` | 服务端会话列表 |
| `GET` | `/api/sessions/{id}` | 获取指定会话历史 |
| `DELETE` | `/api/sessions/{id}` | 删除指定会话 |

SSE 事件类型：

```text
session      { session_id }
status       { stage: "thinking" | "planning" }
tool_call    { id, name, arguments }
tool_result  { id, name, arguments, result }
answer       { content }
error        { message }
done         { session_id }
```

请求示例：

```bash
curl -X POST http://127.0.0.1:8000/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"帮我计算 1024 * 8\", \"session_id\": \"demo\"}"
```

## 7. 使用示例

1. **计算任务（会做）**：输入“帮我计算 (1024 × 8 + 256) ÷ 16”，前端会显示 `simple_calculator` 的参数与结果，再输出自然语言解释。
2. **文件读取（会做）**：输入“读取 README.md 并总结项目内容”，智能体调用 `read_local_file`，基于真实文件内容总结，不会编造。
3. **多轮记忆（能说）**：先问“帮我读一下 requirements.txt”，再问“刚才读到的依赖里有哪些是前端相关的？”，智能体可以结合上一轮上下文回答。
4. **语音交互**：点击输入框右侧麦克风说出指令；开启右上角扬声器后，回复会自动朗读。
5. **会话管理**：左侧切换历史对话，刷新页面后仍可恢复当前会话。

## 8. 实现说明

- **工具层**：`backend/server.py` 注册可用工具，`execute_tool` 按名称分发；新增工具只需实现函数并加入 `AVAILABLE_TOOLS`，同时在 `client.py` 的 `tools_declaration` 中补充描述。
- **工具安全边界**：计算器仅解析基础算术 AST，不执行 Python 代码；文件读取仅允许项目目录内的 UTF-8 文件，且限制为 1 MB。
- **智能体循环**：`run_agent_turn` 采用「模型决策 → 执行工具 → 结果回传 → 再决策」的循环，最多 5 轮，避免死循环。
- **上下文管理**：每个 `ChatSession` 保存原始消息与展示消息；超长时按用户消息边界裁剪，避免留下孤立的 `tool` 消息。
- **流式接口**：FastAPI 用后台线程执行智能体，通过 `queue.Queue` 把事件转成 SSE，前端用 `fetch` + `ReadableStream` 解析，实现工具调用过程实时可见。
- **前端渲染**：无第三方依赖的轻量 Markdown 渲染器，先转义 HTML 再渲染，避免 XSS；支持标题、列表、表格、引用、代码块与行内格式。
- **语音能力**：`SpeechRecognition` 负责语音输入，`speechSynthesis` 负责朗读，均做了浏览器兼容与权限异常提示。

## 9. 小组分工

| 成员 | 分工 |
| --- | --- |
| 待填写 | 后端工具链与大模型调度 |
| 待填写 | 前端界面与交互实现 |
| 待填写 | 测试、文档与演示 |

## 10. 常见问题

**页面显示“服务未连接”**

确认已运行 `python frontend/app.py`，并通过 <http://127.0.0.1:8000> 访问，而不是直接双击 `index.html`。

**调用模型报错 / 超时**

检查 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL` 与模型名称是否正确，以及网络是否可访问对应服务。

**读取文件提示找不到**

工具以项目根目录为工作目录。请使用相对项目根目录的路径，例如 `README.md`、`backend/server.py`。

**语音按钮不可用**

Chrome / Edge 以外的浏览器可能不支持 Web Speech API；同时需要允许麦克风权限。

## 11. 博客园随笔

作业要求的 Markdown 随笔草稿见 [`docs/blogpark-post.md`](docs/blogpark-post.md)。发布前需补齐课程链接、作业链接、小组成员学号、分工和每位成员心得，并把发布后的随笔链接补充到此处。
