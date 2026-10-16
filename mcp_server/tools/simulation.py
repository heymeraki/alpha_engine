"""写操作：有界流水线回测。

不直接暴露挖掘任务里的 while True 无限循环，而是对「给定表达式列表」跑一遍
即返回，复用 machine_lib2.simulate_multiple_tasks —— 它自带登录/会话刷新、
单 alpha 提交、并发槽位上限 8（完成一个补一个的流水线）、truncation=0.08、
maxTrade=ON/OFF、自动去重、结果打 tag 并写入
records/{tag}_simulated_alpha_expression.txt。
"""

import random
from typing import Any

from mcp_server.mcp_instance import mcp
from mcp_server.logger import ToolLogger
from machine_lib2 import simulate_multiple_tasks

MAX_EXPR_PER_CALL = 100


@mcp.tool()
async def run_simulations(
    expressions: list[str],
    tag: str,
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    instrument_type: str = "EQUITY",
    neutralization: str = "SUBINDUSTRY",
    decay: Any = None,
    max_trade: str = "OFF",
    n_jobs: int = 8,
) -> dict:
    """【写】对给定表达式做有界流水线回测，跑完一遍即返回（不持续循环）。

    expressions : 待回测表达式列表，单次最多 100 个；
    tag         : 结果标签，同时作为 records 文件名（建议遵循项目 tag 约定）；
    decay       : int=全部用该值；list=逐表达式指定（长度需一致）；
                  None=每个表达式在 0-10 间随机；
    max_trade   : 只能是 ON / OFF；
    n_jobs      : 并发槽位数（同时在跑的 Alpha 数），账号全局上限 8；
                  每个槽位完成一个立刻补一个，不存在批次概念。
    回测后用 get_results_by_tag 或 query_alphas 读取绩效。
    """
    n = len(expressions)
    if n == 0:
        return {"error": "expressions 为空"}
    if n > MAX_EXPR_PER_CALL:
        return {
            "error": f"单次最多 {MAX_EXPR_PER_CALL} 个表达式，请拆成多次调用",
            "received": n,
        }
    if max_trade not in ("ON", "OFF"):
        return {"error": "max_trade 只能是 ON 或 OFF"}
    concurrency = max(1, min(int(n_jobs), 8))

    if decay is None:
        decay_list = [random.randint(0, 10) for _ in range(n)]
    elif isinstance(decay, int):
        decay_list = [decay] * n
    else:
        decay_list = list(decay)
        if len(decay_list) != n:
            return {"error": "decay 列表长度需与 expressions 一致"}

    log = ToolLogger()
    try:
        await simulate_multiple_tasks(
            expressions,
            [region] * n,
            decay_list,
            [delay] * n,
            tag,
            neutralization,
            max_trade,
            None,
            concurrency,
            log,
            instrument_type,
        )
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "tag": tag,
            "submitted": n,
            "log_tail": log.tail(30),
        }
    return {
        "status": "done",
        "tag": tag,
        "submitted": n,
        "n_jobs": concurrency,
        "settings": {
            "region": region,
            "delay": delay,
            "universe": universe,
            "instrumentType": instrument_type,
            "neutralization": neutralization,
            "maxTrade": max_trade,
        },
        "next_step": "调用 get_results_by_tag(tag) 读取绩效",
        "log_tail": log.tail(20),
    }
