"""写操作：修改 Alpha 名称/颜色/标签，提交 Alpha。"""

from mcp_server.mcp_instance import mcp
from mcp_server.logger import ToolLogger
from machine_lib import s, set_alpha_properties
from tasks.submit import submit_alpha as _submit_alpha


@mcp.tool()
def update_alpha(
    alpha_id: str,
    name: str = "",
    color: str = "",
    tags: list[str] = None,
) -> dict:
    """【写】修改 Alpha 的名称 / 颜色 / 标签。

    仅传入需要修改的字段；tags 为「完整标签列表」（会整体覆盖，不是追加）。
    color 取值如 RED / ORANGE / YELLOW / GREEN / BLUE / PURPLE。
    """
    resp = set_alpha_properties(
        s,
        alpha_id,
        name=name or None,
        color=color or None,
        tags=tags,
    )
    return {
        "alpha_id": alpha_id,
        "status_code": getattr(resp, "status_code", None),
        "updated": {"name": name or None, "color": color or None, "tags": tags},
    }


@mcp.tool()
def submit_alpha(alpha_id: str) -> dict:
    """【写】向平台提交 Alpha，触发提交评估（含自相关/平台相关等检查）并轮询至出结果。

    返回 final_status_code：200=提交成功；403=未通过检查（结果里带 checks）；
    404=超时。
    """
    log = ToolLogger()
    code = _submit_alpha(s, alpha_id, log)
    return {
        "alpha_id": alpha_id,
        "final_status_code": code,
        "submitted": code == 200,
        "log_tail": log.tail(30),
    }
