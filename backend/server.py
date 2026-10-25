"""Local tools available to the AI Agent."""

import ast
import math
import operator
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_SIZE = 1_000_000
MAX_EXPRESSION_LENGTH = 256
MAX_AST_NODES = 64
MAX_RESULT_MAGNITUDE = 1e100

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def read_local_file(file_path: str) -> str:
    """Read a UTF-8 text file under the project root, up to 1 MB."""
    try:
        requested = Path(file_path)
        if not requested.is_absolute():
            requested = PROJECT_ROOT / requested
        resolved = requested.resolve(strict=True)
        resolved.relative_to(PROJECT_ROOT)
        if not resolved.is_file():
            return "错误：目标不是文件。"
        with resolved.open("rb") as source:
            raw_content = source.read(MAX_FILE_SIZE + 1)
        if len(raw_content) > MAX_FILE_SIZE:
            return "错误：文件超过 1 MB，无法读取。"
        content = raw_content.decode("utf-8")
        return f"成功读取文件，内容如下：\n{content}"
    except ValueError:
        return "错误：只能读取项目目录内的文件。"
    except FileNotFoundError:
        return f"错误：找不到项目目录内的文件 '{file_path}'。"
    except (OSError, UnicodeError) as exc:
        return f"读取文件时发生错误：{exc}"


def _evaluate_math(node: ast.AST, depth: int = 0):
    if depth > 32:
        raise ValueError("表达式嵌套层级过深。")

    if isinstance(node, ast.Expression):
        return _evaluate_math(node.body, depth + 1)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        result = node.value
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        result = _UNARY_OPERATORS[type(node.op)](_evaluate_math(node.operand, depth + 1))
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_math(node.left, depth + 1)
        right = _evaluate_math(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("指数绝对值不能超过 100。")
        result = _BINARY_OPERATORS[type(node.op)](left, right)
    else:
        raise ValueError("仅支持数字、括号和基础算术运算符。")

    if type(result) not in (int, float):
        raise ValueError("不支持复数等非实数结果。")
    if isinstance(result, float) and not math.isfinite(result):
        raise ValueError("计算结果不是有限数值。")
    if abs(result) > MAX_RESULT_MAGNITUDE:
        raise ValueError("计算结果过大。")
    return result


def simple_calculator(expression: str) -> str:
    """Evaluate a small arithmetic expression without executing Python code."""
    try:
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("表达式不能为空。")
        if len(expression) > MAX_EXPRESSION_LENGTH:
            raise ValueError("表达式不能超过 256 个字符。")
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
            raise ValueError("表达式过于复杂。")
        result = _evaluate_math(tree)
        return f"计算表达式 '{expression}' 的结果是: {result}"
    except (ArithmeticError, SyntaxError, TypeError, ValueError, OverflowError) as exc:
        return f"计算出错：{exc}"


AVAILABLE_TOOLS = {
    "read_local_file": read_local_file,
    "simple_calculator": simple_calculator,
}


def execute_tool(tool_name: str, arguments: dict) -> str:
    """Dispatch a validated model tool call to a local implementation."""
    if tool_name not in AVAILABLE_TOOLS:
        return f"错误：未找到名为 '{tool_name}' 的工具。"
    if not isinstance(arguments, dict):
        return "错误：工具参数格式无效。"
    try:
        return AVAILABLE_TOOLS[tool_name](**arguments)
    except TypeError as exc:
        return f"错误：工具参数无效：{exc}"


if __name__ == "__main__":
    print("MCP Agent 工具服务已就绪。")
