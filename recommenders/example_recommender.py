"""
示例字段推荐器
================
照此文件实现 recommend(ctx) 即可，返回字段（或字段组合）表达式列表。
ctx.fetch(...) 可拉取平台字段（默认已做 winsorize+ts_backfill 预处理）。

下面演示：原始字段 + 少量字段两两的加减乘除组合。
你的正式推荐逻辑写好后直接替换本函数内部即可。
"""

import itertools


def recommend(ctx):
    # 拉当前 dataset 的 matrix 字段（已预处理）
    fields = ctx.fetch('matrix')

    output = list(fields)  # 1) 原始字段本身

    # 2) 取前几个字段，两两做加减乘除（演示用，控制规模）
    sample = fields[:5]
    for a, b in itertools.combinations(sample, 2):
        output.append(f'({a}) + ({b})')
        output.append(f'({a}) - ({b})')
        output.append(f'({a}) * ({b})')
        output.append(f'({a}) / ({b})')

    return output
