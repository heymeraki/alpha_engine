"""只读研究工具：条件查询因子、单因子详情、相关性、按 tag 取结果。"""

import time

from mcp_server.mcp_instance import mcp
from mcp_server.logger import ToolLogger
from machine_lib import s
from field_provider import (
    FieldContext,
    parse_where,
    SERVER_METRICS,
    CHECK_METRICS,
    _OP_ENCODE,
    _compare,
)

_BRAIN = "https://api.worldquantbrain.com"
_ALPHAS = _BRAIN + "/users/self/alphas"


def _compact(alpha: dict) -> dict:
    """把平台原始 alpha 压缩成研究关心的字段。"""
    ism = alpha.get("is", {}) or {}
    st = alpha.get("settings", {}) or {}
    return {
        "id": alpha.get("id"),
        "expression": (alpha.get("regular", {}) or {}).get("code"),
        "name": alpha.get("name"),
        "tags": alpha.get("tags"),
        "status": alpha.get("status"),
        "sharpe": ism.get("sharpe"),
        "fitness": ism.get("fitness"),
        "turnover": ism.get("turnover"),
        "returns": ism.get("returns"),
        "margin": ism.get("margin"),
        "drawdown": ism.get("drawdown"),
        "longCount": ism.get("longCount"),
        "shortCount": ism.get("shortCount"),
        "decay": st.get("decay"),
        "neutralization": st.get("neutralization"),
        "region": st.get("region"),
        "universe": st.get("universe"),
        "dateSubmitted": alpha.get("dateSubmitted"),
    }


def _split_conditions(where):
    """把 where 拆成 (服务端参数, 相关性条件)；不支持的指标直接报错。"""
    server, corr = [], []
    for metric, op, val in parse_where(where):
        if metric in SERVER_METRICS:
            server.append((SERVER_METRICS[metric] + _OP_ENCODE[op], str(val)))
        elif metric in CHECK_METRICS:
            corr.append((CHECK_METRICS[metric], op, val))
        else:
            supported = sorted(set(SERVER_METRICS) | set(CHECK_METRICS))
            raise ValueError(f"不支持的指标 '{metric}'，支持: {', '.join(supported)}")
    return server, corr


@mcp.tool()
def query_alphas(
    where: list[str],
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    instrument_type: str = "EQUITY",
    target: int = 50,
    max_count: int = 1000,
) -> dict:
    """按一个或多个指标条件查询平台因子，返回含 id/表达式/绩效 的完整行。

    where 示例：['sharpe>1', 'fitness>1', 'turnover<0.7', 'margin<50']。
    服务端指标：sharpe/fitness/turnover/margin/returns/drawdown/longCount/shortCount。
    相关性指标 self_corr / prod_corr 需逐个按需查询（慢），且仅对进入过提交
    评估的因子有值；target 为收集到该数量合格因子即早停。
    """
    server, corr = _split_conditions(where)
    ctx = FieldContext(s, instrument_type, region, delay, universe, "")
    common = [
        ("settings.region", region),
        ("settings.delay", delay),
        ("settings.universe", universe),
        ("settings.instrumentType", instrument_type),
        ("order", "-is.sharpe"),
        ("limit", 100),
    ]
    log = ToolLogger()
    out, offset, total, corr_errors = [], 0, None, 0
    while True:
        js = s.get(_ALPHAS, params=common + server + [("offset", offset)]).json()
        if total is None:
            total = int(js.get("count", 0))
        page = js.get("results", [])
        for alpha in page:
            if corr:
                values = {}
                try:
                    for kind, _, _ in corr:
                        values.setdefault(kind, ctx._fetch_corr(alpha["id"], kind, log))
                except Exception as e:
                    corr_errors += 1
                    log.print(f"  {alpha.get('id')} 相关性获取失败({e})，跳过")
                    if corr_errors >= 5:
                        return {
                            "error": "连续多个相关性获取失败，疑似会话异常",
                            "conditions": where,
                            "alphas": out,
                        }
                    continue
                corr_errors = 0
                if not all(_compare(values[k], op, v) for k, op, v in corr):
                    continue
            out.append(_compact(alpha))
            if target and len(out) >= target:
                break
        offset += len(page) if page else 100
        if offset >= total or not page or offset >= max_count or (target and len(out) >= target):
            break
        time.sleep(1)
    return {
        "count": len(out),
        "total_matched": total,
        "conditions": where,
        "alphas": out,
    }


@mcp.tool()
def get_alpha(alpha_id: str) -> dict:
    """获取单个 Alpha 的完整信息：表达式 / 设置 / 绩效指标 / 提交检查 / 标签。"""
    resp = s.get(f"{_BRAIN}/alphas/{alpha_id}")
    if resp.status_code != 200:
        return {"alpha_id": alpha_id, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    a = resp.json()
    ism = a.get("is", {}) or {}
    st = a.get("settings", {}) or {}
    checks = [
        {
            "name": c.get("name"),
            "result": c.get("result"),
            "value": c.get("value"),
            "limit": c.get("limit"),
        }
        for c in ism.get("checks", [])
    ]
    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "tags": a.get("tags"),
        "color": a.get("color"),
        "status": a.get("status"),
        "stage": a.get("stage"),
        "expression": (a.get("regular", {}) or {}).get("code"),
        "settings": {
            "region": st.get("region"),
            "universe": st.get("universe"),
            "delay": st.get("delay"),
            "decay": st.get("decay"),
            "neutralization": st.get("neutralization"),
            "instrumentType": st.get("instrumentType"),
            "maxTrade": st.get("maxTrade"),
            "truncation": st.get("truncation"),
        },
        "metrics": {
            k: ism.get(k)
            for k in [
                "sharpe",
                "fitness",
                "turnover",
                "returns",
                "margin",
                "drawdown",
                "longCount",
                "shortCount",
                "bookSize",
                "pnl",
            ]
        },
        "checks": checks,
        "dateCreated": a.get("dateCreated"),
        "dateSubmitted": a.get("dateSubmitted"),
    }


@mcp.tool()
def get_alpha_correlations(alpha_id: str, timeout: int = 120) -> dict:
    """获取 Alpha 的自相关(self)与平台相关(prod)。

    平台按需计算，可能返回 Retry-After 触发轮询，冷启动可能耗时（默认上限 120 秒）。
    无历史记录返回 0。
    """
    ctx = FieldContext(s, "EQUITY", "USA", 1, "TOP3000", "")
    log = ToolLogger()
    result = {}
    for kind in ("self", "prod"):
        try:
            result[kind] = ctx._fetch_corr(alpha_id, kind, log, timeout=timeout)
        except Exception as e:
            result[kind] = {"error": str(e)}
    return {"alpha_id": alpha_id, "correlations": result, "log_tail": log.tail(10)}


@mcp.tool()
def get_results_by_tag(tag: str, min_sharpe: float = 0.0, limit: int = 100) -> dict:
    """查询带某 tag 的 Alpha 绩效，按 sharpe 降序，可按 min_sharpe 过滤。

    回测后用它读取某 tag 下的结果；返回精简绩效行。
    """
    common = [("tags", tag), ("order", "-is.sharpe"), ("limit", 100)]
    out, offset, total = [], 0, None
    while True:
        js = s.get(_ALPHAS, params=common + [("offset", offset)]).json()
        if total is None:
            total = int(js.get("count", 0))
        page = js.get("results", [])
        for alpha in page:
            row = _compact(alpha)
            if (row["sharpe"] or 0) >= min_sharpe:
                out.append(row)
            if len(out) >= limit:
                break
        offset += len(page) if page else 100
        if offset >= total or not page or len(out) >= limit:
            break
        time.sleep(1)
    return {"tag": tag, "total_on_platform": total, "returned": len(out), "alphas": out}
