# 模板示例 B：多字段 + 部分固定部分遍历
#  group_vector_neut(op(field_1)) / rank(field_2)
# ============================================================
# - 固定部分（group_vector_neut、rank 等）直接写在 pattern；
# - 多字段槽默认 same：f2 与 f1 取【同一个字段】，无需手动列；
# - 若想要“字段对”笛卡尔积，把 f2 声明为 {'independent': True}。
# ============================================================

pattern = 'group_vector_neut({a}) / rank({b})'

fields = {
    'f1': {'type': 'matrix'},
    'f2': {},                       # 默认 same -> 与 f1 同字段
}

build = {
    'a': {'field': 'f1', 'ops': [
        ['rank({x})', 'ts_rank({x}, 22)', 'group_rank({x}, sector)'],
    ]},
    'b': {'field': 'f2', 'ops': [
        ['rank({x})'],
    ]},
}

decays = [2, 4, 8]                  # 列表：每个表达式随机取一个
neutralization = 'SUBINDUSTRY'
