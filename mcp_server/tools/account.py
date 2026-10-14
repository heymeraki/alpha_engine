"""只读账号工具：回测计数、今日收入、个人绩效、可提交候选。"""

from mcp_server.mcp_instance import mcp
from machine_lib import s
from machine_lib3 import (
    query_payment,
    query_backtest_count,
    get_personal_scores,
    get_submittable_alphas,
    refresh_alpha_metrics_streaming,
)


@mcp.tool()
def get_backtest_count() -> dict:
    """查询近 13 小时内失败回测数量，用于对照每日回测上限。"""
    return query_backtest_count(s)


@mcp.tool()
def get_payment() -> dict:
    """查询今日基础 Alpha / 超级 Alpha 收入。"""
    return query_payment(s)


@mcp.tool()
def get_scores(refresh: bool = False) -> dict:
    """查询个人提交绩效（近 30 天 / 本季度 / 全部，REGULAR 与 SUPER 分开）。

    缓存为空或需要最新数据时设 refresh=True，先从平台流式刷新（可能较慢）。
    """
    if refresh:
        refresh_alpha_metrics_streaming(s)
    scores = get_personal_scores()
    if not scores:
        return {"status": "empty", "hint": "缓存为空，请用 refresh=True 先刷新"}
    return scores


@mcp.tool()
def get_submittable_candidates(refresh: bool = False) -> dict:
    """列出本地缓存中 sharpe>=1、理论上可提交的 Alpha（按 sharpe 降序）。

    refresh=True 时先从平台刷新缓存。
    """
    if refresh:
        refresh_alpha_metrics_streaming(s)
    alphas = get_submittable_alphas()
    if not alphas:
        return {"count": 0, "hint": "暂无可提交候选（或缓存为空，请 refresh=True）"}
    return {"count": len(alphas), "alphas": alphas}
