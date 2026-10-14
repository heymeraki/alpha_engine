# 模板示例 A：多层 op 嵌套（层间自动笛卡尔积）
# ============================================================
# 规则：
#   1) pattern：表达式骨架，{片段名} 是待构建的占位。
#   2) fields：字段槽，运行时用 --dataset-id/--region/--delay/--universe
#      自动查字段填充，无需手动列字段。{'type':'matrix'/'vector'} 可过滤类型。
#   3) build：每个片段从某字段槽出发，ops 是【从内到外】的若干层，
#      每层一个算子列表，层内/层间自动笛卡尔积。
#        裸名字 'rank'        -> rank(x)
#        带参数 'ts_rank({x}, 22)' / 'group_rank({x}, sector)'
#   4) decay / neutralization：每个表达式只取一个（标量）；
#      也可写列表，每个表达式随机取一个。不写则 decay 随机0-10、neut=SUBINDUSTRY。
# ============================================================

pattern = '{a}'

fields = {'f1': {'type': 'matrix'}}

build = {
    'a': {'field': 'f1', 'ops': [
        # 内层算子
        ['rank({x})', 'ts_rank({x}, 22)', 'ts_mean({x}, 66)'],
        # 外层算子（与内层自动笛卡尔积）
        ['rank({x})', 'group_rank({x}, sector)', 'ts_rank({x}, 252)'],
    ]},
}

# decay = [1,4,6,8,10]
neutralization = 'SUBINDUSTRY'
