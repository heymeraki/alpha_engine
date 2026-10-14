from machine_lib import *
from machine_lib2 import *
from machine_lib3 import *
import asyncio
import time
from collections import defaultdict

def run_task(dataset_id, region, delay, instrumentType, universe, maxTrade, neutralization, n_jobs, tag, inner_logger):
    delay = int(delay)
    n_jobs = int(n_jobs)

    while True:
      try:
        try:
            result = query_backtest_count(s)
            if result.get('status') == 'success':
                count = result['data'].get('count', 0)
                remaining = 5000 - count
                inner_logger.print(datetime.now(), '=================今日回测统计==================')
                inner_logger.print(datetime.now(), f'今日已回测数量: {count}')
                inner_logger.print(datetime.now(), f'今日剩余数量: {remaining} (每天最多5000次)')
                inner_logger.print(datetime.now(), '=============================================')
            else:
                inner_logger.print(datetime.now(), f'查询今日回测数量失败: {result.get("message", "未知错误")}')
        except Exception as e:
            inner_logger.print(datetime.now(), f'查询今日回测数量时发生异常: {str(e)}')

        inner_logger.print(datetime.now(), '=================您的三阶段配置信息==================')
        inner_logger.print(datetime.now(), f'dataset_id: {dataset_id}')
        inner_logger.print(datetime.now(), f'region: {region}')
        inner_logger.print(datetime.now(), f'delay: {delay}')
        inner_logger.print(datetime.now(), f'instrumentType: {instrumentType}')
        inner_logger.print(datetime.now(), f'universe: {universe}')
        inner_logger.print(datetime.now(), f'maxTrade: {maxTrade}')
        inner_logger.print(datetime.now(), f'n_jobs: {n_jobs}')
        inner_logger.print(datetime.now(), '=============================================')
        time.sleep(2)

        if tag is None:
            tag = f'{region}_{delay}_{instrumentType}_{universe}_{dataset_id}_step2'
        step2_tag_list = [tag]

        for step2_tag in step2_tag_list:
            if 'ILLIQUID' in step2_tag:
                parts = step2_tag.split('_')
                region = parts[0]
                delay = parts[1]
                instrumentType = parts[2]
                ILLIQUID_tag = parts[3]
                universe = parts[4]
                dataset_id = parts[5]
                step_num = parts[6]
                universe = f'{ILLIQUID_tag}_{universe}'
            else:
                parts = step2_tag.split('_')
                region = parts[0]
                delay = parts[1]
                instrumentType = parts[2]
                universe = parts[3]
                dataset_id = parts[4]
                step_num = parts[5]

            if int(delay) == 1:
                sharpe_step3_th = 1.2
                fitness_step3_th = 0.75
            elif int(delay) == 0:
                sharpe_step3_th = 2.6
                fitness_step3_th = 1.4
            else:
                inner_logger.print(datetime.now(), 'delay must be 0 or 1.')
                continue

            step3_tag = step2_tag.replace('_step2', '_step3')

            so_tracker = get_alphas('2024-10-07', '2029-12-31', sharpe_step3_th, fitness_step3_th, 100, 100, region, universe, delay, instrumentType, 500, 'track', step2_tag, 'RED', s, inner_logger)
            so_layer = prune(so_tracker['next'] + so_tracker['decay'], 'ts_backfill(', 3)

            th_alpha_list = []
            for expr, decay in so_layer:
                for alpha in trade_when_factory('trade_when', expr, region, delay):
                    th_alpha_list.append((alpha, decay))

            inner_logger.print(datetime.now(), len(th_alpha_list))

            completed_alphas = read_completed_alphas(f'records/{step3_tag}_simulated_alpha_expression.txt', inner_logger)
            raw_alpha_list = th_alpha_list[:]
            alpha_list = [alpha_decay for alpha_decay in raw_alpha_list if alpha_decay[0] not in completed_alphas]

            if len(alpha_list) == 0:
                inner_logger.print(datetime.now(), f'已经完成了{len(completed_alphas)}个alpha表达式，一共有{len(raw_alpha_list)}个alpha表达式')
                inner_logger.print(datetime.now(), f'{step3_tag} is done.')
                continue

            inner_logger.print(datetime.now(), f'{step3_tag}progress: {len(raw_alpha_list) - len(alpha_list)}/{len(raw_alpha_list)}')

            grouped_dict = defaultdict(list)
            for alpha, decay in alpha_list:
                grouped_dict[decay].append(alpha)

            groups = list(grouped_dict.items())
            asyncio.run(simulate_grouped_tasks(groups, step3_tag, neutralization, maxTrade, [], n_jobs, region, universe, delay, instrumentType, inner_logger))

        inner_logger.print(datetime.now(), '本轮结束，600秒后开始下一轮...')
        time.sleep(600)
      except Exception as e:
        inner_logger.print(datetime.now(), f'本轮发生错误: {e}，10秒后开始下一轮...')
        time.sleep(10)

run_task = while_true_try_decorator(run_task)
