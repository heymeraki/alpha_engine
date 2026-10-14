import os
import random
import asyncio
import itertools
from machine_lib import *
from machine_lib2 import *
from config import *
from machine_lib3 import *
from field_provider import FieldContext, resolve_fields


# ---------------- 模板加载 ----------------

def load_template(template_file):
    """执行模板文件，返回其命名空间（模板完全自描述）。"""
    namespace = {}
    with open(template_file, 'r', encoding='utf-8') as f:
        exec(compile(f.read(), template_file, 'exec'), namespace)
    if 'pattern' not in namespace:
        raise ValueError(f'模板文件缺少 pattern: {template_file}')
    return namespace


def apply_fragment(frag, x):
    """把单目片段作用于内层表达式 x。"""
    frag = str(frag).strip()
    if '{x}' in frag:
        return frag.replace('{x}', str(x))
    return f'{frag}({x})'


# ---------------- 字段槽位 ----------------

def slot_pool(df, opts, raw_fields):
    """平台模式：按槽位选项返回候选字段。"""
    opts = opts or {}
    ftype = opts.get('type')
    if raw_fields:
        matrix = df[df['type'] == 'MATRIX']['id'].tolist()
        vector = get_vec_fields(df[df['type'] == 'VECTOR']['id'].tolist())
    else:
        matrix = process_datafields(df, 'matrix')
        vector = process_datafields(df, 'vector')
    if ftype == 'matrix':
        return matrix
    if ftype == 'vector':
        return vector
    return matrix + vector


def resolve_slot_binding(fields):
    """
    多字段槽默认 same 同字段。
    返回 (独立槽列表, {绑定槽: 被跟随槽})。
    """
    slot_names = list(fields.keys())
    primary = slot_names[0]
    independent = [primary]
    bound = {}
    for s in slot_names[1:]:
        opts = fields[s] or {}
        if opts.get('independent'):
            independent.append(s)
        else:
            bound[s] = opts.get('same', primary)
    return independent, bound


# ---------------- 表达式展开 ----------------

def expand_expressions(ns, pools):
    """
    按字段池 pools（{槽位: [字段,...]}）展开表达式。
    字段来源（平台直拉 / 推荐器）由调用方决定，本函数只负责组合。
    """
    pattern = ns['pattern']
    fields = ns.get('fields') or {}
    build = ns.get('build') or {}
    if not fields:
        raise ValueError("模板缺少 fields（至少声明一个字段槽，如 fields = {'f1': {}}）")

    independent, bound = resolve_slot_binding(fields)

    expressions = []
    for combo in itertools.product(*[pools[s] for s in independent]):
        values = dict(zip(independent, combo))
        for b, target in bound.items():
            values[b] = values[target]   # same：复制同字段

        # 每个片段：从其字段槽出发，逐层套算子（自动笛卡尔积）
        fragment_values = {}
        for fname, spec in build.items():
            xlist = [values[spec['field']]]
            for layer in spec['ops']:
                xlist = [apply_fragment(frag, x) for x in xlist for frag in layer]
            fragment_values[fname] = xlist

        names = list(fragment_values)
        for fcombo in itertools.product(*[fragment_values[n] for n in names]):
            expr = pattern
            for n, v in zip(names, fcombo):
                expr = expr.replace('{' + n + '}', v)
            for s in fields:           # 允许骨架直接引用字段槽
                expr = expr.replace('{' + s + '}', values[s])
            expressions.append(expr)

    expressions = list(dict.fromkeys(expressions))
    leftover = [e for e in expressions if '{' in e or '}' in e]
    return expressions, leftover


# ---------------- 设置解析 ----------------

def first_present(ns, *keys):
    for k in keys:
        if k in ns and ns[k] is not None:
            return ns[k]
    return None


def pick_value(spec):
    """列表则随机取一个，标量直接返回。"""
    if isinstance(spec, (list, tuple)):
        return random.choice(list(spec))
    return spec


# ---------------- 主任务 ----------------

def run_task(template_file, dataset_id, region, delay, instrumentType, universe,
             cli_neut, cli_maxtrade, n_jobs, tag, raw_fields, max_alpha,
             recommender, from_alphas, where, inner_logger):
    delay = int(delay)
    n_jobs = int(n_jobs)

    while True:
      try:
        # 今日回测用量
        try:
            result = query_backtest_count(s)
            if result.get('status') == 'success':
                count = result['data'].get('count', 0)
                inner_logger.print(datetime.now(), '=================今日回测统计==================')
                inner_logger.print(datetime.now(), f'今日已回测数量: {count}，剩余: {5000 - count}（每天最多5000次）')
                inner_logger.print(datetime.now(), '=============================================')
            else:
                inner_logger.print(datetime.now(), f'查询今日回测数量失败: {result.get("message", "未知错误")}')
        except Exception as e:
            inner_logger.print(datetime.now(), f'查询今日回测数量时发生异常: {str(e)}')

        ns = load_template(template_file)
        inner_logger.print(datetime.now(), f'模板文件: {template_file}')

        fields = ns.get('fields') or {}
        if not fields:
            raise ValueError("模板缺少 fields（至少声明一个字段槽）")

        # 字段池：平台条件查询 / 推荐器 / datafields 直拉
        ctx = FieldContext(s, instrumentType, region, delay, universe, dataset_id)
        if from_alphas:
            if not where:
                raise ValueError('--from-alphas 需配合至少一个 --where 条件')
            inner_logger.print(datetime.now(), f'字段来源：平台条件查询，条件 {where}')
            expressions = ctx.fetch_alphas_by_conditions(
                where, target=max_alpha, logger=inner_logger)
            if not expressions:
                inner_logger.print(datetime.now(), '没有满足条件的因子，600秒后重新检查...')
                time.sleep(600)
                continue
            pools = {slot: list(expressions) for slot in fields}
        elif recommender:
            inner_logger.print(datetime.now(), f'字段来源：推荐器 {recommender}')
            recommended = resolve_fields(ctx, recommender)
            pools = {slot: list(recommended) for slot in fields}
        else:
            if not dataset_id:
                raise ValueError('datafields 直拉模式需要 --dataset-id')
            inner_logger.print(datetime.now(), '字段来源：平台直拉。获取数据集中，可能会很慢（新增的限流）')
            df = get_datafields(s, instrument_type=instrumentType, region=region, delay=delay,
                                universe=universe, dataset_id=dataset_id)
            if len(df) == 0:
                inner_logger.print(datetime.now(), f'No data fields found for dataset_id: {dataset_id}')
                time.sleep(600)
                continue
            pools = {slot: slot_pool(df, fields[slot], raw_fields) for slot in fields}

        if tag is None:
            stem = os.path.splitext(os.path.basename(template_file))[0]
            source_part = dataset_id if dataset_id else 'fromalphas'
            tag = f'{region}_{delay}_{instrumentType}_{universe}_{source_part}_tpl_{stem}'

        completed_file = os.path.join(RECORDS_PATH, f'{tag}_simulated_alpha_expression.txt')
        completed_alphas = read_completed_alphas(completed_file, inner_logger)

        raw_alpha_list, leftover = expand_expressions(ns, pools)
        if leftover:
            inner_logger.print(datetime.now(), f'警告：{len(leftover)} 个表达式存在未解析占位符，已剔除。示例: {leftover[0]}')

        alpha_list = [a for a in raw_alpha_list if a not in completed_alphas and '{' not in a]
        alpha_list = list(dict.fromkeys(alpha_list))

        if len(alpha_list) <= 1:
            inner_logger.print(datetime.now(), f'{tag} is already completed，600秒后重新检查...')
            time.sleep(600)
            continue

        inner_logger.print(datetime.now(), f'{tag} progress: {len(raw_alpha_list) - len(alpha_list)}/{len(raw_alpha_list)}')
        random.shuffle(alpha_list)
        if len(alpha_list) > max_alpha:
            alpha_list = alpha_list[:max_alpha]

        # decay / neut / maxTrade：CLI 显式传入则覆盖模板，否则用模板，再否则用默认
        decay_spec = first_present(ns, 'decays', 'decay')
        neut_spec = cli_neut if cli_neut is not None else first_present(ns, 'neutralizations', 'neutralization')
        maxtrade_spec = cli_maxtrade if cli_maxtrade is not None else first_present(ns, 'max_trades', 'max_trade')

        decay_list = [pick_value(decay_spec) if decay_spec is not None else random.randint(0, 10)
                      for _ in alpha_list]
        neut = pick_value(neut_spec) if neut_spec is not None else 'SUBINDUSTRY'
        maxtrade = pick_value(maxtrade_spec) if maxtrade_spec is not None else 'OFF'

        inner_logger.print(datetime.now(), f'本次设置 -> neutralization: {neut}, maxTrade: {maxtrade}，decay 按模板分配')

        region_list = [(region, universe)] * len(alpha_list)
        delay_list = [delay] * len(alpha_list)

        asyncio.run(simulate_multiple_tasks(alpha_list, region_list, decay_list, delay_list,
                  tag, neut, maxtrade, [], n_jobs, inner_logger, instrumentType))
        inner_logger.print(datetime.now(), '本轮完成，10秒后开始下一轮...')
        time.sleep(10)
      except Exception as e:
        inner_logger.print(datetime.now(), f'本轮发生错误: {e}，10秒后开始下一轮...')
        time.sleep(10)


run_task = while_true_try_decorator(run_task)
