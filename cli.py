#!/usr/bin/env python3
"""
WorldQuant Alpha 因子自动挖掘 CLI 工具

用法:
    python cli.py dig 1step --dataset-id <id> [选项]
    python cli.py dig 2step --dataset-id <id> [选项]
    python cli.py dig 3step --dataset-id <id> [选项]
    python cli.py dig 4step --dataset-id <id> [选项]
    python cli.py check [选项]
    python cli.py submit --alpha-id <id>
    python cli.py scores
    python cli.py backtest-count
    python cli.py payment

前置条件:
    在项目根目录放置 user_info.txt，格式:
        username: "your_email@example.com"
        password: "your_password"
"""

import argparse
import importlib.util
import json
import os
import signal
import sys
import time
from datetime import datetime


def _force_exit(signum, frame):
    print('\n\n[强制退出] 收到中断信号，立即终止。')
    sys.stdout.flush()
    os._exit(0)


# 注册信号处理：Ctrl+C 直接强制退出，不被 asyncio 吞掉
signal.signal(signal.SIGINT, _force_exit)
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, _force_exit)

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TASKS_DIR = os.path.join(PROJECT_ROOT, 'tasks')
LOGS_DIR = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)


class CLILogger:
    def __init__(self, log_file=None):
        self.log_file = log_file

    def _timestamp(self):
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def print(self, *args, sep=' ', end='\n'):
        message = sep.join(map(str, args))
        line = f'[{self._timestamp()}] {message.strip()}'
        print(line, flush=True)
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except Exception:
                pass

    def info(self, message):
        self.print(message)

    def write(self, message):
        if message and message.strip():
            self.print(message.strip())

    def flush(self):
        pass


def load_task_module(task_name):
    module_name = task_name if task_name.endswith('.py') else task_name + '.py'
    module_path = os.path.join(TASKS_DIR, module_name)
    if not os.path.exists(module_path):
        raise FileNotFoundError(f'任务模块不存在: {module_path}')
    spec = importlib.util.spec_from_file_location(task_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[task_name] = module
    spec.loader.exec_module(module)
    return module


def make_logger(task_name):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(LOGS_DIR, f'{task_name}_{timestamp}.log')
    return CLILogger(log_file=log_file)


def add_digging_args(parser):
    parser.add_argument('--dataset-id', required=True, help='数据集 ID')
    parser.add_argument('--region', default='USA', help='区域，默认 USA')
    parser.add_argument('--delay', type=int, default=1, choices=[0, 1], help='延迟，默认 1')
    parser.add_argument('--instrument-type', default='EQUITY', help='标的类型，默认 EQUITY')
    parser.add_argument('--universe', default='TOP3000', help='股票池，默认 TOP3000')
    parser.add_argument('--max-trade', default='OFF', choices=['ON', 'OFF'], help='是否启用 maxTrade，默认 OFF')
    parser.add_argument('--neutralization', default='SECTOR', help='中性化方式，默认 SECTOR')
    parser.add_argument('--n-jobs', type=int, default=8, help='并发回测槽位数（同时在跑的 Alpha 数，账号全局上限 8；每个槽位完成一个立刻补一个，单终端 8 即跑满），默认 8；多开终端时各任务 n-jobs 之和应 <= 8')
    parser.add_argument('--tag', default=None, help='标签（留空自动生成）')


def cmd_dig_1step(args):
    logger = make_logger('dig_1step')
    module = load_task_module('digging_consultant_1step')
    module.run_task(
        dataset_id=args.dataset_id,
        region=args.region,
        delay=args.delay,
        instrumentType=args.instrument_type,
        universe=args.universe,
        maxTrade=args.max_trade,
        neutralization=args.neutralization,
        n_jobs=args.n_jobs,
        tag=args.tag,
        field_recommend=args.field_recommend,
        recommended_fields=args.recommended_fields,
        field_recommend_id=args.field_recommend_id,
        inner_logger=logger,
    )


def cmd_dig_2step(args):
    logger = make_logger('dig_2step')
    module = load_task_module('digging_consultant_2step')
    module.run_task(
        dataset_id=args.dataset_id, region=args.region, delay=args.delay,
        instrumentType=args.instrument_type, universe=args.universe,
        maxTrade=args.max_trade, neutralization=args.neutralization,
        n_jobs=args.n_jobs, tag=args.tag, inner_logger=logger,
    )


def cmd_dig_3step(args):
    logger = make_logger('dig_3step')
    module = load_task_module('digging_consultant_3step')
    module.run_task(
        dataset_id=args.dataset_id, region=args.region, delay=args.delay,
        instrumentType=args.instrument_type, universe=args.universe,
        maxTrade=args.max_trade, neutralization=args.neutralization,
        n_jobs=args.n_jobs, tag=args.tag, inner_logger=logger,
    )


def cmd_dig_4step(args):
    logger = make_logger('dig_4step')
    module = load_task_module('digging_consultant_4step')
    module.run_task(
        dataset_id=args.dataset_id, region=args.region, delay=args.delay,
        instrumentType=args.instrument_type, universe=args.universe,
        maxTrade=args.max_trade, neutralization=args.neutralization,
        n_jobs=args.n_jobs, tag=args.tag, inner_logger=logger,
    )


def cmd_template(args):
    if not args.from_alphas and not args.dataset_id:
        raise ValueError('datafields 直拉 / 推荐器模式需要 --dataset-id；若要按平台已有因子查询请加 --from-alphas')
    logger = make_logger('template')
    module = load_task_module('template_dig')
    module.run_task(
        template_file=args.template_file,
        dataset_id=args.dataset_id, region=args.region, delay=args.delay,
        instrumentType=args.instrument_type, universe=args.universe,
        cli_neut=args.neutralization, cli_maxtrade=args.max_trade,
        n_jobs=args.n_jobs, tag=args.tag,
        raw_fields=args.raw_fields, max_alpha=args.max_alpha,
        recommender=args.recommender, from_alphas=args.from_alphas,
        where=args.where, inner_logger=logger,
    )


def cmd_check(args):
    logger = make_logger('check')
    module = load_task_module('check')
    module.run_task(
        mode=args.mode, n_jobs=args.n_jobs, date=args.date,
        self_corr_mode=args.self_corr_mode, inner_logger=logger,
    )


def cmd_submit(args):
    logger = make_logger('submit')
    module = load_task_module('submit')
    module.run_task(alpha_id=args.alpha_id, inner_logger=logger)


def cmd_scores(args):
    from machine_lib import s
    from machine_lib3 import refresh_alpha_metrics_streaming, get_personal_scores
    print('正在刷新因子提交数据...')
    for update in refresh_alpha_metrics_streaming(s):
        data = json.loads(update)
        status = data.get('status', '')
        message = data.get('message', '')
        if status == 'progress':
            print(f'  [{data.get("progress", 0):.0f}%] {message}')
        elif status == 'completed':
            print(f'  完成: {message}')
        elif status == 'error':
            print(f'  错误: {message}')
    result = get_personal_scores()
    if result is None:
        print('暂无缓存数据。')
        return
    if isinstance(result, dict) and result.get('status') == 'error':
        print(f'错误: {result["message"]}')
        return
    scores = result.get('scores', {})
    metrics = result.get('metrics', [])
    for alpha_type, periods in scores.items():
        print(f'\n=== {alpha_type} ===')
        for period_name, period_scores in periods.items():
            print(f'  [{period_name}]')
            for metric in metrics:
                val = period_scores.get(metric)
                if val is not None:
                    print(f'    {metric}: {val:.4f}')


def cmd_backtest_count(args):
    from machine_lib import s
    from machine_lib3 import query_backtest_count
    result = query_backtest_count(s)
    if result.get('status') == 'success':
        count = result['data'].get('count', 0)
        print(f'今日已回测: {count}')
        print(f'今日剩余: {5000 - count} (每日上限 5000)')
    else:
        print(f'查询失败: {result.get("message", "未知错误")}')


def cmd_payment(args):
    from machine_lib import s
    from machine_lib3 import query_payment
    result = query_payment(s)
    if result.get('status') == 'success':
        if 'data' in result:
            data = result['data']
            print(f'Regular 收益: {data.get("regular")}')
            if data.get('has_super'):
                print(f'Super 收益: {data.get("super_payment")}')
        else:
            print(result.get('message', '暂无数据'))
    else:
        print(f'查询失败: {result.get("message", "未知错误")}')



def cmd_results(args):
    """按 tag 查询回测结果，打印绩效并可选导出 CSV。"""
    from machine_lib import s
    import pandas as pd

    tag = args.tag
    region = args.region
    delay = args.delay
    universe = args.universe
    min_sharpe = args.min_sharpe

    print(f'正在查询 tag={tag} 的回测结果...')
    all_alphas = []
    offset = 0
    limit = 100
    while True:
        url = (
            f'https://api.worldquantbrain.com/users/self/alphas'
            f'?limit={limit}&offset={offset}'
            f'&tag%3D{tag}'
            f'&settings.region={region}'
            f'&settings.delay={delay}'
            f'&settings.universe={universe}'
            f'&order=-is.sharpe&hidden=false'
        )
        resp = s.get(url)
        data = resp.json()
        results = data.get('results', [])
        all_alphas.extend(results)
        count = data.get('count', 0)
        print(f'  已获取 {len(all_alphas)}/{count}')
        if len(results) < limit or len(all_alphas) >= count:
            break
        offset += limit
        time.sleep(1)

    if not all_alphas:
        print('未找到该 tag 的因子。')
        return

    rows = []
    for a in all_alphas:
        is_data = a.get('is', {})
        settings = a.get('settings', {})
        rows.append({
            'alpha_id': a.get('id'),
            'sharpe': is_data.get('sharpe'),
            'fitness': is_data.get('fitness'),
            'turnover': is_data.get('turnover'),
            'returns': is_data.get('returns'),
            'longCount': is_data.get('longCount'),
            'shortCount': is_data.get('shortCount'),
            'margin': is_data.get('margin'),
            'drawdown': is_data.get('drawdown'),
            'region': settings.get('region'),
            'universe': settings.get('universe'),
            'delay': settings.get('delay'),
            'decay': settings.get('decay'),
            'status': a.get('status'),
            'dateCreated': a.get('dateCreated', '')[:10],
            'expression': a.get('regular', {}).get('code', ''),
        })
    df = pd.DataFrame(rows)

    # 过滤 sharpe
    if min_sharpe is not None:
        df = df[df['sharpe'].abs() >= min_sharpe]

    # 打印摘要
    print(f'\n共 {len(df)} 个因子（sharpe >= {min_sharpe}）')
    if not df.empty:
        print(f'sharpe  均值={df["sharpe"].mean():.4f}  最大={df["sharpe"].max():.4f}  最小={df["sharpe"].min():.4f}')
        print(f'fitness 均值={df["fitness"].mean():.4f}  最大={df["fitness"].max():.4f}')
        print(f'turnover 均值={df["turnover"].mean():.4f}')

        # 打印 top 20
        display_cols = ['alpha_id', 'sharpe', 'fitness', 'turnover', 'longCount', 'shortCount', 'decay', 'dateCreated']
        print(f'\n=== Top {min(20, len(df))} by sharpe ===')
        print(df[display_cols].head(20).to_string(index=False))

    # 导出 CSV
    if args.export:
        df.to_csv(args.export, index=False, encoding='utf-8-sig')
        print(f'\n已导出到 {args.export}')

def build_parser():
    parser = argparse.ArgumentParser(
        description='WorldQuant Alpha 因子自动挖掘 CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    dig_parser = subparsers.add_parser('dig', help='因子挖掘（1~4阶段）')
    dig_sub = dig_parser.add_subparsers(dest='step', help='挖掘阶段')

    p1 = dig_sub.add_parser('1step', help='第1阶段：一阶算子因子挖掘')
    add_digging_args(p1)
    p1.add_argument('--field-recommend', default='OFF', choices=['ON', 'OFF'],
                    help='是否使用推荐字段模式，默认 OFF')
    p1.add_argument('--recommended-fields', default=None,
                    help='推荐字段列表（Python 列表字符串），field-recommend=ON 时必填')
    p1.add_argument('--field-recommend-id', default=None,
                    help='推荐字段数据集 ID，field-recommend=ON 时必填')
    p1.set_defaults(func=cmd_dig_1step)

    p2 = dig_sub.add_parser('2step', help='第2阶段：二阶分组算子因子挖掘')
    add_digging_args(p2)
    p2.set_defaults(func=cmd_dig_2step)

    p3 = dig_sub.add_parser('3step', help='第3阶段：trade_when 条件因子挖掘')
    add_digging_args(p3)
    p3.set_defaults(func=cmd_dig_3step)

    p4 = dig_sub.add_parser('4step', help='第4阶段：模板组合因子挖掘')
    add_digging_args(p4)
    p4.set_defaults(func=cmd_dig_4step)

    template_parser = subparsers.add_parser('template', help='按 template/ 下模板文件批量生成因子')
    add_digging_args(template_parser)
    template_parser.set_defaults(neutralization=None, max_trade=None)  # 默认取模板文件内设置
    # 条件查询模式不需要 dataset-id，改为非必填（代码内再校验）
    for _a in template_parser._actions:
        if _a.dest == 'dataset_id':
            _a.required = False
    template_parser.add_argument('--template-file', required=True,
                                 help='模板文件路径，如 template/example1.py')
    template_parser.add_argument('--raw-fields', action='store_true',
                                 help='使用原始字段（默认已做 winsorize+ts_backfill 预处理）')
    template_parser.add_argument('--recommender', default=None,
                                 help='字段推荐器文件，如 recommenders/example_recommender.py；不传则平台直拉字段')
    template_parser.add_argument('--from-alphas', action='store_true',
                                 help='字段来源改为平台已有合格因子（按 --where 条件查询，不使用 dataset）')
    template_parser.add_argument('--where', action='append', default=None,
                                 help='查询条件，可重复，如 --where "sharpe>=1" --where "self_corr<0.7"')
    template_parser.add_argument('--max-alpha', type=int, default=1000,
                                 help='单次最多回测因子数，默认 1000')
    template_parser.set_defaults(func=cmd_template)

    check_parser = subparsers.add_parser('check', help='因子质量检查')
    check_parser.add_argument('--mode', default='USER', choices=['USER', 'CONSULTANT', 'PPAC'])
    check_parser.add_argument('--n-jobs', type=int, default=4)
    check_parser.add_argument('--date', default=None, help='起始日期 YYYY-MM-DD')
    check_parser.add_argument('--self-corr-mode', default='官方自相关',
                              choices=['官方自相关', '本地自相关'])
    check_parser.set_defaults(func=cmd_check)

    submit_parser = subparsers.add_parser('submit', help='提交因子')
    submit_parser.add_argument('--alpha-id', required=True)
    submit_parser.set_defaults(func=cmd_submit)

    scores_parser = subparsers.add_parser('scores', help='个人因子评分')
    scores_parser.set_defaults(func=cmd_scores)

    bt_parser = subparsers.add_parser('backtest-count', help='今日回测用量')
    bt_parser.set_defaults(func=cmd_backtest_count)

    pay_parser = subparsers.add_parser('payment', help='今日收益')
    pay_parser.set_defaults(func=cmd_payment)

    results_parser = subparsers.add_parser('results', help='按 tag 查询回测结果')
    results_parser.add_argument('--tag', required=True, help='因子 tag（如 USA_1_EQUITY_TOP3000_analyst34_step1）')
    results_parser.add_argument('--region', default='USA', help='区域，默认 USA')
    results_parser.add_argument('--delay', type=int, default=1, choices=[0, 1], help='延迟，默认 1')
    results_parser.add_argument('--universe', default='TOP3000', help='股票池，默认 TOP3000')
    results_parser.add_argument('--min-sharpe', type=float, default=None, help='只显示 |sharpe| >= 该值的因子')
    results_parser.add_argument('--export', default=None, help='导出 CSV 文件路径')
    results_parser.set_defaults(func=cmd_results)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, 'func'):
        parser.print_help()
        sys.exit(1)
    print('=' * 60)
    print(f'WorldQuant Alpha 因子挖掘 CLI')
    print(f'启动时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'命令: {args.command} {getattr(args, "step", "")}')
    print('=' * 60)
    try:
        args.func(args)
    except Exception as e:
        print(f'\n任务执行出错: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
