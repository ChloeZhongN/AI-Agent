"""Automated tests for the agent's local tools and conversation flow."""
import asyncio
import gc
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import api, client, server


def model_response(content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls)
            )
        ]
    )


def model_tool_call(name, arguments, call_id="call-1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


async def asgi_request(application, method, path, body=b"", headers=()):
    request_sent = False
    response_messages = []

    async def receive():
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        response_messages.append(message)

    raw_path = path.encode("ascii")
    await application(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": raw_path,
            "query_string": b"",
            "headers": list(headers),
            "client": ("testclient", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    response_start = next(
        message for message in response_messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in response_messages
        if message["type"] == "http.response.body"
    )
    return response_start["status"], response_body


class AgentToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.database = self.workspace / "test_todos.db"
        self.root_patcher = patch.object(server, "ROOT_DIR", self.workspace)
        self.db_patcher = patch.object(server, "DB_PATH", self.database)
        self.root_patcher.start()
        self.db_patcher.start()
        server._init_db()

    def tearDown(self):
        self.db_patcher.stop()
        self.root_patcher.stop()
        gc.collect()
        self.temp_dir.cleanup()

    def test_calculator_evaluates_supported_arithmetic(self):
        result = server.simple_calculator("(1024 * 8 + 256) / 16")
        self.assertIn("结果是: 528.0", result)

    def test_calculator_rejects_unsupported_expressions(self):
        result = server.simple_calculator("__import__('os').system('echo unsafe')")
        self.assertIn("计算出错", result)
        self.assertNotIn("unsafe", result)

    def test_file_read_returns_existing_utf8_content(self):
        (self.workspace / "notes.txt").write_text("会议安排：下午三点", encoding="utf-8")
        result = server.read_local_file("notes.txt")
        self.assertIn("成功读取文件", result)
        self.assertIn("会议安排：下午三点", result)

    def test_file_read_reports_missing_file(self):
        result = server.read_local_file("missing.txt")
        self.assertIn("找不到文件", result)

    def test_file_write_creates_nested_file_and_preserves_utf8(self):
        result = server.write_local_file("reports/summary.md", "# 总结\n完成")
        self.assertIn("成功将内容写入文件", result)
        self.assertEqual(
            (self.workspace / "reports" / "summary.md").read_text(encoding="utf-8"),
            "# 总结\n完成",
        )

    def test_file_tool_workflow_writes_then_reads_document(self):
        content = "# 今日安排\n1. 完成接口测试\n2. 提交测试报告"
        write_result = server.execute_tool(
            "write_local_file",
            {"file_path": "daily/plan.md", "content": content},
        )
        read_result = server.execute_tool(
            "read_local_file", {"file_path": "daily/plan.md"}
        )
        self.assertIn("成功将内容写入文件", write_result)
        self.assertIn(content, read_result)

    def test_file_write_rejects_path_outside_workspace(self):
        result = server.write_local_file("../outside.txt", "不应写入")
        self.assertIn("安全限制", result)
        self.assertFalse((self.workspace.parent / "outside.txt").exists())

    def test_todo_add_list_complete_and_delete(self):
        added = server.manage_todos("add", task="提交测试报告")
        self.assertIn("已成功添加", added)
        todo_id = int(added.split("ID: ")[1].split("）")[0])

        listed = server.manage_todos("list")
        self.assertIn("提交测试报告", listed)
        self.assertIn("[未完成]", listed)

        completed = server.manage_todos("complete", todo_id=todo_id)
        self.assertIn("已完成", completed)
        self.assertIn("[已完成]", server.manage_todos("list"))

        deleted = server.manage_todos("delete", todo_id=todo_id)
        self.assertIn("已删除", deleted)
        self.assertIn("清单为空", server.manage_todos("list"))

    def test_todo_add_rejects_blank_task(self):
        result = server.manage_todos("add", task="  ")
        self.assertIn("内容不能为空", result)

    def test_image_analysis_reports_missing_local_image(self):
        result = server.analyze_image("missing.png")
        self.assertIn("找不到图片文件", result)

    def test_image_analysis_sends_image_and_question_to_model(self):
        image_path = self.workspace / "sample.png"
        image_path.write_bytes(b"fake image bytes")
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="识别到一张示例图片"))]
        )

        with patch.object(server.vl_client.chat.completions, "create", return_value=response) as create:
            result = server.analyze_image("sample.png", "图片里有什么？")

        self.assertIn("识别到一张示例图片", result)
        payload = create.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(payload[1]["text"], "图片里有什么？")
        self.assertTrue(payload[0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_execute_tool_dispatches_registered_tool(self):
        result = server.execute_tool("simple_calculator", {"expression": "6 * 7"})
        self.assertIn("结果是: 42", result)

    def test_execute_tool_reports_unknown_tool(self):
        result = server.execute_tool("unknown_tool", {})
        self.assertIn("未找到名为", result)

    def test_agent_uses_tool_then_returns_natural_language_answer_and_events(self):
        session_id = "test-tool-flow"
        client.reset_session(session_id)
        self.addCleanup(client.reset_session, session_id)
        events = []
        responses = [
            model_response(tool_calls=[model_tool_call("simple_calculator", {"expression": "6 * 7"})]),
            model_response(content="答案是 42。"),
        ]

        with patch.object(client.client.chat.completions, "create", side_effect=responses):
            result = client.run_agent_turn(
                "请计算 6 乘以 7", session_id=session_id,
                on_event=lambda event, data: events.append((event, data)),
            )

        self.assertEqual(result["reply"], "答案是 42。")
        self.assertEqual(result["session_id"], session_id)
        self.assertEqual(result["tool_calls"][0]["name"], "simple_calculator")
        self.assertIn("结果是: 42", result["tool_calls"][0]["result"])
        self.assertEqual(
            [event for event, _ in events],
            ["status", "tool_call", "tool_result", "status", "answer"],
        )
        history = client.get_history(session_id)
        self.assertEqual(history["messages"][-1]["content"], "答案是 42。")

    def test_agent_answers_naturally_and_retains_multi_turn_context(self):
        session_id = "test-language-flow"
        client.reset_session(session_id)
        self.addCleanup(client.reset_session, session_id)
        responses = [
            model_response(content="你好！我可以帮你计算、读写文件和管理待办。"),
            model_response(content="可以，我会继续围绕智能助手项目为你解答。"),
        ]

        with patch.object(
            client.client.chat.completions, "create", side_effect=responses
        ) as create:
            first = client.run_agent_turn("你好，你能做什么？", session_id=session_id)
            second = client.run_agent_turn(
                "请继续介绍这个智能助手。", session_id=session_id
            )

        self.assertIn("计算", first["reply"])
        self.assertIn("智能助手", second["reply"])
        self.assertEqual(first["tool_calls"], [])
        self.assertEqual(second["tool_calls"], [])
        second_turn_messages = create.call_args_list[1].kwargs["messages"]
        self.assertTrue(
            any(
                item.get("role") == "assistant"
                and item.get("content") == first["reply"]
                for item in second_turn_messages
            )
        )
        history = client.get_history(session_id)["messages"]
        self.assertEqual(
            [item["role"] for item in history],
            ["user", "assistant", "user", "assistant"],
        )

    def test_chat_api_forwards_natural_language_and_returns_agent_result(self):
        agent_result = {
            "session_id": "api-chat-session",
            "reply": "已为你完成计算，结果是 42。",
            "tool_calls": [
                {
                    "id": "call-api-1",
                    "name": "simple_calculator",
                    "arguments": {"expression": "6 * 7"},
                    "result": "计算表达式 '6 * 7' 的结果是: 42",
                }
            ],
        }
        with patch.object(api, "run_agent_turn", return_value=agent_result) as run_turn:
            status, body = asyncio.run(
                asgi_request(
                    api.app,
                    "POST",
                    "/api/chat",
                    json.dumps(
                        {"message": "请计算 6 乘以 7", "session_id": "api-chat-session"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers=((b"content-type", b"application/json"),),
                )
            )

        run_turn.assert_called_once_with(
            "请计算 6 乘以 7", session_id="api-chat-session"
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), agent_result)

    def test_chat_api_rejects_empty_message(self):
        status, body = asyncio.run(
            asgi_request(
                api.app,
                "POST",
                "/api/chat",
                b'{"message":""}',
                headers=((b"content-type", b"application/json"),),
            )
        )
        self.assertEqual(status, 422)
        self.assertIn("message", json.loads(body)["detail"][0]["loc"])

    def test_health_api_reports_available_tools(self):
        response = api.health()
        self.assertEqual(response["status"], "ok")
        self.assertEqual(set(response["tools"]), set(server.AVAILABLE_TOOLS))
        self.assertTrue(response["model"])

    def test_upload_api_saves_supported_image_and_returns_tool_path(self):
        upload_dir = self.workspace / "uploads"
        upload_dir.mkdir()

        class FakeUpload:
            filename = "diagram.PNG"

            async def read(self):
                return b"image content"

        with patch.object(api, "UPLOADS_DIR", upload_dir):
            response = asyncio.run(api.upload_image(FakeUpload()))

        self.assertRegex(response["path"], r"^uploads/[0-9a-f]{12}\.png$")
        self.assertEqual(response["url"], f"/{response['path']}")
        self.assertEqual(
            (self.workspace / response["path"]).read_bytes(), b"image content"
        )

    def test_upload_api_rejects_unsupported_file_type(self):
        class FakeUpload:
            filename = "document.txt"

            async def read(self):
                self.fail("Unsupported files must be rejected before reading")

        with self.assertRaises(api.HTTPException) as error:
            asyncio.run(api.upload_image(FakeUpload()))
        self.assertEqual(error.exception.status_code, 400)


    def test_agent_rejects_blank_input_without_model_call(self):
        with patch.object(client.client.chat.completions, "create") as create:  # noqa: SIM117
            with self.assertRaises(client.AgentError):
                client.run_agent_turn("   ")
        create.assert_not_called()

    def test_agent_converts_model_failure_to_agent_error(self):
        with patch.object(  # noqa: SIM117
            client.client.chat.completions, "create", side_effect=RuntimeError("model unavailable")
        ):
            with self.assertRaisesRegex(client.AgentError, "大模型调用失败"):
                client.run_agent_turn("请帮我总结", session_id="test-model-error")
        client.reset_session("test-model-error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
