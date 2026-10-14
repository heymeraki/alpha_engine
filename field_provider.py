"""
字段来源提供者（Field Provider）
================================
字段有三种来源：
  1) 平台 datafields 直拉（默认）；
  2) 外部推荐器：recommenders/ 下模块实现 recommend(ctx)；
  3) 平台已有合格因子：按一组指标条件查询（--from-alphas + --where），
     返回这些因子的表达式，作为模板字段槽输入（不做二次预处理）。

条件查询两段式：
  - sharpe/fitness/turnover/margin/returns 等 is.* 指标走服务端过滤（快）；
  - 自相关 self_corr / 平台相关 prod_corr 在列表接口里没有值，需对候选
    逐个调用 /alphas/{id}/correlations/self|prod 按需触发（平台返回
    Retry-After，轮询取值），慢且限流，因此支持 target 早停。

新增推荐逻辑只需在 recommenders/ 加文件；条件查询由本模块直接支持。
"""

import re
import time

from machine_lib import get_datafields, process_datafields, get_vec_fields


# 服务端可过滤的 is 指标（含别名）
SERVER_METRICS = {
    'sharpe': 'is.sharpe',
    'fitness': 'is.fitness',
    'turnover': 'is.turnover',
    'margin': 'is.margin',
    'returns': 'is.returns',
    'drawdown': 'is.drawdown',
    'longcount': 'is.longCount',
    'shortcount': 'is.shortCount',
    'long': 'is.longCount',
    'short': 'is.shortCount',
    'pnl': 'is.pnl',
}

# 相关性指标 -> correlations 端点的 kind
CHECK_METRICS = {
    'self_corr': 'self',
    'autocorr': 'self',
    'prod_corr': 'prod',
    'platform_corr': 'prod',
}

# 服务端简单参数只可靠支持严格 > / <（>= 会被编码成 >== 导致 "Expected number"）；
# 连续指标上 >= / <= 与严格比较几乎无差别，统一归一化。
_OP_ENCODE = {'>': '>', '>=': '>', '<': '<', '<=': '<', '=': '=', '==': '='}
_COND_RE = re.compile(r'^\s*([A-Za-z_]+)\s*(>=|<=|==|=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$')


def parse_where(where_list):
    """解析 ['sharpe>=1', 'self_corr<0.7'] 为 (metric, op, value) 列表。"""
    conds = []
    for w in where_list or []:
        m = _COND_RE.match(w)
        if not m:
            raise ValueError(f"无法解析条件 '{w}'，正确格式如 sharpe>=1、turnover<=0.7、self_corr<0.7")
        conds.append((m.group(1).lower(), m.group(2), float(m.group(3))))
    return conds


def _compare(x, op, y):
    if op in ('>', '>='):
        return x > y or (op == '>=' and x == y)
    if op in ('<', '<='):
        return x < y or (op == '<=' and x == y)
    return x == y


class FieldContext:
    """传给推荐器 / 条件查询的上下文。"""

    def __init__(self, session, instrument_type, region, delay, universe, dataset_id):
        self.session = session
        self.instrument_type = instrument_type
        self.region = region
        self.delay = delay
        self.universe = universe
        self.dataset_id = dataset_id

    def fetch(self, data_type='all', dataset_id=None, raw=False):
        """拉取平台 datafields。"""
        df = get_datafields(
            self.session, instrument_type=self.instrument_type,
            region=self.region, delay=self.delay, universe=self.universe,
            dataset_id=dataset_id or self.dataset_id,
        )
        if raw:
            matrix = df[df['type'] == 'MATRIX']['id'].tolist()
            vector = get_vec_fields(df[df['type'] == 'VECTOR']['id'].tolist())
        else:
            matrix = process_datafields(df, 'matrix')
            vector = process_datafields(df, 'vector')
        if data_type == 'matrix':
            return matrix
        if data_type == 'vector':
            return vector
        return matrix + vector

    def fetch_alphas_by_conditions(self, where_list, page_size=100, max_count=10000,
                                   target=None, logger=None):
        """
        按指标条件查询平台已有因子，返回去重后的表达式列表。
          target : 相关性过滤时，收集到该数量合格因子即早停（None 不早停）；
          logger : 可选，需有 .print 方法（默认用内建 print）。
        """
        log = logger.print if logger is not None else (lambda *a, **k: print(*a))

        conds = parse_where(where_list)
        server_params = []
        corr_conds = []
        for metric, op, val in conds:
            if metric in SERVER_METRICS:
                server_params.append((SERVER_METRICS[metric] + _OP_ENCODE[op], str(val)))
            elif metric in CHECK_METRICS:
                corr_conds.append((CHECK_METRICS[metric], op, val))
            else:
                supported = sorted(set(SERVER_METRICS) | set(CHECK_METRICS))
                raise ValueError(f"不支持的指标 '{metric}'，支持: {', '.join(supported)}")

        base_url = 'https://api.worldquantbrain.com/users/self/alphas'
        common_params = [
            ('settings.region', self.region),
            ('settings.delay', self.delay),
            ('settings.universe', self.universe),
            ('settings.instrumentType', self.instrument_type),
            ('order', '-is.sharpe'),
            ('limit', page_size),
        ]

        # 分页拉取。相关性条件时边拉边过滤，凑够 target 立即停止翻页（避免过度请求）；
        # 无相关性条件时整批收集，最后按 max_count 截断。
        accepted = []
        offset = 0
        total = None
        announced = False
        consecutive_errors = 0
        while True:
            resp = self.session.get(base_url, params=common_params + server_params + [('offset', offset)])
            js = resp.json()
            if not isinstance(js, dict):
                raise RuntimeError(f'条件查询返回异常 (status {resp.status_code}): {js}')
            if total is None:
                total = int(js.get('count', 0))
            page = js.get('results', [])

            if corr_conds:
                if not announced:
                    log(f'服务端共匹配 {total} 个，开始按需查询相关性（较慢）...')
                    announced = True
                for alpha in page:
                    aid = alpha.get('id')
                    try:
                        values = {}
                        for kind, _, _ in corr_conds:
                            if kind not in values:
                                values[kind] = self._fetch_corr(aid, kind, logger)
                    except Exception as e:
                        consecutive_errors += 1
                        log(f'  alpha {aid} 相关性获取失败({e})，跳过')
                        if consecutive_errors >= 5:
                            raise RuntimeError('连续多个 alpha 相关性获取失败，疑似会话异常')
                        continue
                    consecutive_errors = 0
                    if all(_compare(values[kind], op, threshold) for kind, op, threshold in corr_conds):
                        accepted.append(alpha)
                    if (len(accepted)) % 5 == 0:
                        log(f'  已合格 {len(accepted)}（翻页至 offset {offset}）')
                    if target and len(accepted) >= target:
                        break
            else:
                accepted.extend(page)

            offset += len(page) if page else page_size
            reached_target = bool(corr_conds and target and len(accepted) >= target)
            if offset >= total or not page or offset >= max_count or reached_target:
                break
            time.sleep(1)

        if not corr_conds:
            accepted = accepted[:max_count]

        expressions = [a.get('regular', {}).get('code') for a in accepted]
        return list(dict.fromkeys(e for e in expressions if e))

    def _fetch_corr(self, alpha_id, kind, logger=None, timeout=30):
        """
        按需获取单个 alpha 的相关性（self / prod），轮询 Retry-After。
        复刻 check.py 逻辑但不依赖 pandas：
          self -> 取 records 中 correlation 的最大值；
          prod -> 取 alphas>0 行中 max 的最大值；
          无记录 -> 0。
        """
        url = f'https://api.worldquantbrain.com/alphas/{alpha_id}/correlations/{kind}'
        start = time.time()
        while True:
            resp = self.session.get(url)
            retry_after = resp.headers.get('Retry-After')
            if retry_after:
                if time.time() - start > timeout:
                    raise TimeoutError(f'{kind} 相关性查询超时: {alpha_id}')
                time.sleep(float(retry_after))
                continue
            try:
                js = resp.json()
            except ValueError:
                # 空 body / 非 JSON（平台计算中的瞬时状态），短暂等待后重试
                if time.time() - start > timeout:
                    raise TimeoutError(f'{kind} 相关性查询超时(非JSON): {alpha_id}')
                time.sleep(1)
                continue
            records = js.get('records', [])
            if not records:
                return 0.0
            # properties 为列表，每项 {name, title, type}，records 与之对齐
            columns = [p['name'] for p in js['schema']['properties']]
            try:
                if kind == 'self':
                    ci = columns.index('correlation')
                    vals = [float(rec[ci]) for rec in records if rec[ci] is not None]
                else:
                    ai = columns.index('alphas')
                    mi = columns.index('max')
                    vals = [float(rec[mi]) for rec in records
                            if rec[mi] is not None and float(rec[ai]) > 0]
            except (ValueError, TypeError, IndexError):
                return 0.0
            return max(vals) if vals else 0.0


def load_recommender(path):
    """加载推荐器文件，返回其 recommend 函数。"""
    namespace = {}
    with open(path, 'r', encoding='utf-8') as f:
        exec(compile(f.read(), path, 'exec'), namespace)
    recommend = namespace.get('recommend')
    if not callable(recommend):
        raise ValueError(f'推荐器 {path} 必须定义 recommend(ctx) 函数')
    return recommend


def resolve_fields(ctx, recommender=None):
    """字段入口：recommender 为 None 时平台直拉 datafields，否则调用推荐器。"""
    if recommender is None:
        return ctx.fetch('all')

    fields = load_recommender(recommender)(ctx)
    if not isinstance(fields, (list, tuple)):
        raise ValueError(f'推荐器 {recommender} 的 recommend 必须返回列表')
    return list(dict.fromkeys(str(f).strip() for f in fields if str(f).strip()))
