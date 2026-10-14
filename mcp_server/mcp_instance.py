"""FastMCP 单例。所有工具模块共享这一个实例并通过 @mcp.tool() 注册。"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "wq-research",
    instructions=(
        "WorldQuant BRAIN 量化研究助手。\n"
        "典型流程：list_datasets/list_datafields/list_operators 做发现 -> "
        "query_alphas 按条件找已有因子 -> run_simulations 有界批量回测 -> "
        "get_results_by_tag/get_alpha_correlations 检查质量 -> "
        "update_alpha 改名打标 -> submit_alpha 提交。\n"
        "写操作均走项目已验证的批量模拟器：单批<=n_jobs(<=10)、truncation=0.08、"
        "maxTrade=ON/OFF、自动去重、结果按 tag 归档。单次 run_simulations 最多 100 个表达式。"
    ),
)
