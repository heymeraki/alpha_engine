import random
from machine_lib import *
from machine_lib2 import *
from config import *
from machine_lib3 import *

def run_task(dataset_id, region, delay, instrumentType, universe, maxTrade, neutralization, n_jobs, tag, field_recommend, recommended_fields, field_recommend_id, inner_logger):
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

        inner_logger.print(datetime.now(), '=================您的配置信息==================')
        inner_logger.print(datetime.now(), f'dataset_id: {dataset_id}')
        inner_logger.print(datetime.now(), f'region: {region}')
        inner_logger.print(datetime.now(), f'delay: {delay}')
        inner_logger.print(datetime.now(), f'instrumentType: {instrumentType}')
        inner_logger.print(datetime.now(), f'universe: {universe}')
        inner_logger.print(datetime.now(), f'maxTrade: {maxTrade}')
        inner_logger.print(datetime.now(), f'n_jobs: {n_jobs}')

        if field_recommend == 'ON':
            dataset_id = field_recommend_id
            recommended_fields = eval(recommended_fields)
            inner_logger.print('注意！只有一阶段需要开启数据字段，后面的2,3,4阶段只需要修改dataset_id为如[recommend1]即可')
            inner_logger.print('您开启本次一阶段开启了数据字段模式')
            inner_logger.print(f'其中第一个数据字段是：{recommended_fields[:1]}')

        inner_logger.print(datetime.now(), '=============================================')
        time.sleep(2)

        if tag is None:
            tag = f'{region}_{delay}_{instrumentType}_{universe}_{dataset_id}_step1'

        completed_file_path = os.path.join(RECORDS_PATH, f'{tag}_simulated_alpha_expression.txt')
        completed_alphas = read_completed_alphas(completed_file_path, inner_logger)

        inner_logger.print(datetime.now(), f'Processing dataset_id: {dataset_id}')

        if field_recommend == 'OFF':
            inner_logger.print(datetime.now(), '获取数据集中，可能会很慢（新增的限流）')
            group = get_datafields(s, region=region, delay=delay, universe=universe, dataset_id=dataset_id)
            if len(group) == 0:
                inner_logger.print(datetime.now(), f'No data fields found for dataset_id: {dataset_id}, region: {region}, delay: {delay}, universe: {universe}')
                time.sleep(600)
                continue
            pc_fields = process_datafields(group, 'matrix') + process_datafields(group, 'vector')
        else:
            pc_fields = recommended_fields

        pc_fields = random.sample(pc_fields, min(len(pc_fields), 50))
        raw_alpha_list = first_order_factory(pc_fields, ts_ops + basic_ops)
        raw_alpha_list = list(dict.fromkeys(raw_alpha_list))
        alpha_list = [alpha for alpha in raw_alpha_list if alpha not in completed_alphas]
        alpha_list = list(dict.fromkeys(alpha_list))

        if len(alpha_list) <= 1:
            inner_logger.print(datetime.now(), f'{tag} is already completed，600秒后重新检查...')
            time.sleep(600)
            continue

        inner_logger.print(datetime.now(), f'{dataset_id} progress: {len(raw_alpha_list) - len(alpha_list)}/{len(raw_alpha_list)}')
        random.shuffle(alpha_list)
        if len(alpha_list) > 1000:
            alpha_list = alpha_list[:1000]

        region_list = [(region, universe)] * len(alpha_list)
        decay_list = [random.randint(0, 10) for _ in range(len(alpha_list))]
        delay_list = [delay] * len(alpha_list)

        asyncio.run(simulate_multiple_tasks(alpha_list, region_list, decay_list, delay_list, tag, neutralization, maxTrade, [], n_jobs, inner_logger, instrumentType))
        inner_logger.print(datetime.now(), '本轮完成，10秒后开始下一轮...')
        time.sleep(10)
      except Exception as e:
        inner_logger.print(datetime.now(), f'本轮发生错误: {e}，10秒后开始下一轮...')
        time.sleep(10)

run_task = while_true_try_decorator(run_task)
