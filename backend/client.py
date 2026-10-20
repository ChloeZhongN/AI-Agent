# backend/client.py
import json
from openai import OpenAI
from server import execute_tool  # 导入刚才写好的工具执行函数

# ==================== 1. 初始化阿里云百炼大模型客户端 ====================
client = OpenAI(
    api_key="sk-ws-H.PXMDLYL.VuYv.MEQCIATz2j4r5MBxYptDPOU3T55SIorp8io-lb7N0B7Kk-s2AiAadQ0AfLxM0PuuQemnX9PWKy5SeLr_hmCLQfiSRDEphQ",  # 密钥
    base_url="https://ws-sry84uag76dm6rj8.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", #OpenAI 地址
)

# ==================== 2. 声明大模型能调用的“工具描述”（告诉大模型有哪些工具可用） ====================
tools_declaration = [
    {
        "type": "function",
        "function": {
            "name": "read_local_file",
            "description": "当用户需要读取本地文本文件、查看文件内容时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要读取的文件路径，例如 'test.txt'"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simple_calculator",
            "description": "当用户需要进行数学计算、算术求解时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如 '50 + 20 * 3'"
                    }
                },
                "required": ["expression"]
            }
        }
    }
]

# ==================== 3. 智能体核心对话与调度逻辑 ====================
def run_agent(user_prompt: str):
    """
    接收用户输入的自然语言，让大模型决策：是直接回答（能说），还是调用工具（会做）。
    """
    print(f"\n【用户输入】: {user_prompt}")
    
    # 初始化对话历史（支持多轮对话记忆，加分项！）
    messages = [
        {"role": "system", "content": "你是一个具备工具调用能力的智能办公助手。如果用户的需求需要通过工具完成，请准确调用相应工具。"},
        {"role": "user", "content": user_prompt}
    ]

    # 第一次请求大模型：让大模型判断是否需要调用工具
    response = client.chat.completions.create(
        model="qwen-plus",  # 使用通义千问模型
        messages=messages,
        tools=tools_declaration,  # 把工具列表传给大模型
        tool_choice="auto"       # 让大模型自己决定是否调用工具
    )

    response_message = response.choices[0].message
    messages.append(response_message) # 将大模型的响应加入历史记录

    # 检查大模型是否决定调用工具
    if response_message.tool_calls:
        print("【AI 决策】: 检测到需要调用外部工具！")
        
        for tool_call in response_message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            print(f"【正在执行工具】: {tool_name}，参数: {tool_args}")
            
            # 执行本地 Server 提供的工具函数
            tool_result = execute_tool(tool_name, tool_args)
            print(f"【工具返回结果】: {tool_result}")

            # 将工具执行的结果再传回给大模型
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result
            })

        # 第二次请求大模型：让大模型根据工具的返回结果，生成最终给用户的自然语言答复
        second_response = client.chat.completions.create(
            model="qwen-plus",
            messages=messages
        )
        final_answer = second_response.choices[0].message.content
        print(f"【AI 最终回复】: {final_answer}")
        return final_answer
    else:
        # 如果不需要调用工具，直接返回大模型的对话结果
        print(f"【AI 最终回复】: {response_message.content}")
        return response_message.content

# ==================== 4. 测试运行 ====================
if __name__ == "__main__":
    # 测试 1：触发计算器工具（会做）
    run_agent("帮我计算一下 1024 乘以 8 是多少？")
    
    # 测试 2：普通的自然语言对话（能说）
    run_agent("你好，请简单介绍一下你自己。")