"""只读发现工具：配置常量、数据集、字段、算子。"""

import pandas as pd

import config
from mcp_server.mcp_instance import mcp
from machine_lib import (
    s,
    get_datafields,
    basic_ops,
    ts_ops,
    group_ops,
    vec_ops,
    arsenal,
)

_BRAIN = "https://api.worldquantbrain.com"


@mcp.tool()
def list_config_options() -> dict:
    """返回平台可选的常量：regions / delays / instrumentTypes / universes。"""
    return {
        "regions": config.REGION_LIST,
        "delays": config.DELAY_LIST,
        "instrumentTypes": config.INSTRUMENT_TYPE_LIST,
        "universes": config.UNIVERSE_UNIQUE,
    }


@mcp.tool()
def list_datasets(
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    instrument_type: str = "EQUITY",
    search: str = "",
) -> dict:
    """列出某市场设置下可用的数据集。

    返回 id / 名称 / 类别 / 字段数 / Alpha 数 / 覆盖率 / 价值分 / 金字塔乘数。
    search 给定时按 id 或名称做子串过滤（不区分大小写）。
    """
    common = [
        ("instrumentType", instrument_type),
        ("region", region),
        ("delay", delay),
        ("universe", universe),
        ("limit", 50),
    ]
    records = []
    offset = 0
    total = None
    while True:
        js = s.get(_BRAIN + "/data-sets", params=common + [("offset", offset)]).json()
        if total is None:
            total = int(js.get("count", 0))
        page = js.get("results", [])
        for d in page:
            records.append(
                {
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "category": (d.get("category") or {}).get("id"),
                    "fieldCount": d.get("fieldCount"),
                    "alphaCount": d.get("alphaCount"),
                    "coverage": d.get("coverage"),
                    "valueScore": d.get("valueScore"),
                    "pyramidMultiplier": d.get("pyramidMultiplier"),
                }
            )
        offset += len(page) if page else 50
        if offset >= total or not page:
            break
    if search:
        key = search.lower()
        records = [
            d
            for d in records
            if key in str(d["id"]).lower() or key in str(d["name"]).lower()
        ]
    return {"count": len(records), "settings": [region, delay, universe], "datasets": records}


@mcp.tool()
def list_datafields(
    dataset_id: str,
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    instrument_type: str = "EQUITY",
    field_type: str = "",
    search: str = "",
    limit: int = 300,
) -> dict:
    """列出某数据集下的字段。

    返回 id / 类型(MATRIX/VECTOR) / 描述 / 覆盖率 / Alpha 数。
    field_type 可空，或 matrix / vector 做类型过滤；search 为字段 id 子串。
    """
    df = get_datafields(s, instrument_type, region, delay, universe, dataset_id, search)
    fields = []
    for _, row in df.iterrows():
        ftype = str(row.get("type") or "").lower()
        if field_type and field_type.lower() not in ftype:
            continue
        coverage = row.get("coverage")
        fields.append(
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "description": row.get("description"),
                "coverage": round(float(coverage), 3) if pd.notna(coverage) else None,
                "alphaCount": row.get("alphaCount"),
            }
        )
        if len(fields) >= limit:
            break
    return {"count": len(fields), "dataset_id": dataset_id, "fields": fields}


@mcp.tool()
def list_operators(category: str = "") -> dict:
    """列出平台实际可用的算子（已按 /operators 过滤）。

    category 可空返回全部分组，或指定 basic / ts / group / vector / arsenal。
    """
    groups = {
        "basic": basic_ops,
        "ts": ts_ops,
        "group": group_ops,
        "vector": vec_ops,
        "arsenal": arsenal,
    }
    if category:
        return {"category": category, "operators": groups.get(category.lower(), [])}
    return groups
