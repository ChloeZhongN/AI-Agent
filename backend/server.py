# backend/server.py
import os

# ==================== 1. 定义智能体可以调用的“工具函数”（会做） ====================

def read_local_file(file_path: str) -> str:
    """
    工具 1：读取本地文件的内容
    参数: file_path (str) - 文件路径
    返回: 文件内容字符串
    """
    try:
        if not os.path.exists(file_path):
            return f"错误：找不到文件 '{file_path}'。"
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return f"成功读取文件，内容如下：\n{content}"
    except Exception as e:
        return f"读取文件时发生错误: {str(e)}"

def simple_calculator(expression: str) -> str:
    """
    工具 2：简易计算器
    参数: expression (str) - 数学表达式，例如 "100 * 5"
    返回: 计算结果
    """
    try:
        # 使用安全的 eval 进行基础数学计算
        result = eval(expression)
        return f"计算表达式 '{expression}' 的结果是: {result}"
    except Exception as e:
        return f"计算出错: {str(e)}"

# ==================== 2. 集中注册工具（供客户端查询和调用） ====================
# 这里模拟 MCP Server 注册的可用工具列表
AVAILABLE_TOOLS = {
    "read_local_file": read_local_file,
    "simple_calculator": simple_calculator
}

def execute_tool(tool_name: str, arguments: dict) -> str:
    """
    根据工具名称和参数，分发并执行对应的工具函数
    """
    if tool_name not in AVAILABLE_TOOLS:
        return f"错误：未找到名为 '{tool_name}' 的工具。"
    
    # 动态调用对应的函数并传入参数
    tool_func = AVAILABLE_TOOLS[tool_name]
    return tool_func(**arguments)

if __name__ == "__main__":
    print("MCP Server 工具服务端已就绪，等待 Client 调用...")