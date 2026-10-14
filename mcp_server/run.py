"""
MCP Server 启动入口
===================
启动：python -m mcp_server （MCP 客户端以项目根目录为 cwd 拉起本命令）

关键：MCP stdio 传输把 JSON-RPC 直接写入 sys.stdout.buffer；而项目库
（machine_lib import 期登录等）会向 sys.stdout 打印人类日志。这里把
sys.stdout 的「文本写入」重定向到日志文件，同时保留原始 stdout.buffer
给协议使用，二者互不干扰。
"""

import os
import sys
import io

# --- 1. 固定工作目录到项目根，保证 user_info.txt / records / logs 等相对路径正确 ---
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.makedirs("logs", exist_ok=True)

# --- 2. 隔离人类可读的 stdout 文本，保留原始二进制 buffer 给 MCP stdio ---
_ORIG_STDOUT_BUFFER = sys.stdout.buffer
_STDOUT_SINK = open(os.path.join("logs", "mcp_stdout.log"), "a", encoding="utf-8")


class _DivertedText(io.TextIOBase):
    """文本写入进日志文件；.buffer 仍指向原始 stdout 二进制缓冲（协议专用）。"""

    encoding = "utf-8"
    errors = "strict"

    def __init__(self, binary_buffer, sink):
        self.buffer = binary_buffer
        self._sink = sink

    def write(self, s):
        if s:
            self._sink.write(s)
        return len(s)

    def flush(self):
        self._sink.flush()

    def isatty(self):
        return False


sys.stdout = _DivertedText(_ORIG_STDOUT_BUFFER, _STDOUT_SINK)

# --- 3. 导入即注册工具（此时 machine_lib 的登录日志已被重定向，不污染协议）---
from mcp_server.mcp_instance import mcp  # noqa: E402
from mcp_server.tools import (  # noqa: E402,F401
    discovery,
    research,
    simulation,
    manage,
    account,
)


def main():
    mcp.run()  # 默认 stdio 传输；stdio_server 读取 sys.stdout.buffer（原始 fd1）


if __name__ == "__main__":
    main()
