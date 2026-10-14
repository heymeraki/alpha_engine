"""
工具日志适配器
==============
底层库（machine_lib2 / tasks.submit 等）需要一个带 .print 方法的 inner_logger。
MCP stdio 用 stdout 传 JSON-RPC，不能把人类日志打到 stdout，因此这里：
  - 每条日志写入 logs/mcp_server.log（持久、可审计）；
  - 同时缓存在内存（环形、有上限），工具返回时带 log_tail 给 AI 看进度/报错。
"""

import os
import datetime

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "mcp_server.log")


class ToolLogger:
    """单次工具调用的日志收集器（.print 与项目 CLILogger 接口一致）。"""

    def __init__(self, cap=300):
        self.cap = cap
        self.lines = []

    def print(self, *args):
        msg = " ".join(str(a) for a in args)
        line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
        self.lines.append(line)
        if len(self.lines) > self.cap:
            del self.lines[: self.cap // 2]
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def tail(self, n=30):
        return self.lines[-n:]
