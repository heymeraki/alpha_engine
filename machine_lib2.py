import os
import sys
import requests
import time
import json
import pandas as pd
from itertools import product
from collections import defaultdict
from datetime import datetime
import aiofiles
import aiohttp
import asyncio

async def async_login(inner_logger):
    def load_decrypted_data(txt_file):
        with open(txt_file, 'r') as f:
            data = f.read().strip().split('\n')
        data = {line.split(': ')[0]: line.split(': ')[1] for line in data}
        return data['username'][1:-1], data['password'][1:-1]

    username, password = load_decrypted_data('user_info.txt')
    conn = aiohttp.TCPConnector(ssl=False)
    session = aiohttp.ClientSession(connector=conn)
    max_login_retries = 3
    for attempt in range(1, max_login_retries + 1):
        try:
            async with session.post(
                'https://api.worldquantbrain.com/authentication',
                auth=aiohttp.BasicAuth(username, password)
            ) as response:
                if response.status == 201:
                    inner_logger.print('Login successful!')
                    return session
                else:
                    body = await response.text()
                    inner_logger.print(
                        f'Login failed (attempt {attempt}/{max_login_retries})! '
                        f'Status: {response.status}, Response: {body}'
                    )
        except aiohttp.ClientError as e:
            inner_logger.print(
                f'Login request error (attempt {attempt}/{max_login_retries}): {e}'
            )
        if attempt < max_login_retries:
            await asyncio.sleep(5 * attempt)
    await session.close()
    raise Exception(f'登录失败，已重试 {max_login_retries} 次，请检查网络和 user_info.txt')

async def async_set_alpha_properties(session, alpha_id, name, color, description, selection_desc, combo_desc, tags, inner_logger):
    params = {'category': None}
    if color:
        params['color'] = color
    if name:
        params['name'] = name
    if tags:
        params['tags'] = tags
    if description:
        params['regular'] = {'description': description}
    if combo_desc:
        params['combo'] = {'description': combo_desc}
    if selection_desc:
        params['selection'] = {'description': selection_desc}
    url = f'https://api.worldquantbrain.com/alphas/{alpha_id}'
    try:
        async with session.patch(url, json=params) as response:
            if response.status == 200:
                inner_logger.print(f'Alpha {alpha_id} properties updated successfully! Tag: {tags}')
            else:
                inner_logger.print(f'Failed to update alpha {alpha_id}. Status code: {response.status}, Response: {await response.text()}')
    except aiohttp.ClientError as e:
        inner_logger.print(f'Error during patch request for alpha {alpha_id}: {e}')
    except Exception as e:
        inner_logger.print(f'An unexpected error occurred for alpha {alpha_id}: {e}')

class SessionManager:
    def __init__(self, session, start_time, expiry_time, inner_logger):
        self.session = session
        self.start_time = start_time
        self.expiry_time = expiry_time
        self.inner_logger = inner_logger
    
    async def refresh_session(self):
        self.inner_logger.print(f'{datetime.now()} Session expired, logging in again...')
        await self.session.close()
        self.session = await async_login(inner_logger=self.inner_logger)
        self.start_time = time.time()

async def simulate_multi(session_manager, alpha_expression_list, region_info, name, neut, decay, delay, maxTrade, stone_bag, tags, semaphore, inner_logger, instrumentType='EQUITY'):
    brain_api_url = 'https://api.worldquantbrain.com'
    async with semaphore:
        if time.time() - session_manager.start_time > session_manager.expiry_time:
            await session_manager.refresh_session()
        if len(alpha_expression_list) > 10:
            raise ValueError('The number of alpha expressions in a pool should be less than 10')
        region, uni = region_info
        sim_data_list = []
        for alpha_expression in alpha_expression_list:
            alpha = f'%s' % alpha_expression
            inner_logger.print(f'{datetime.now()} Simulating for alpha: {alpha}, region: {region}, universe: {uni}, decay: {decay}, delay: {delay}')
            simulation_data = {
                'type': 'REGULAR',
                'settings': {
                    'instrumentType': instrumentType,
                    'region': region,
                    'universe': uni,
                    'delay': delay,
                    'decay': decay,
                    'neutralization': neut,
                    'truncation': 0.08,
                    'pasteurization': 'ON',
                    'unitHandling': 'VERIFY',
                    'nanHandling': 'ON',
                    'language': 'FASTEXPR',
                    'maxTrade': maxTrade,
                    'visualization': False
                },
                'regular': alpha
            }
            sim_data_list.append(simulation_data)
        
        max_retries = 5
        retry_count = 0
        while retry_count < max_retries:
            try:
                async with session_manager.session.post('https://api.worldquantbrain.com/simulations', json=sim_data_list) as simulation_response:
                    simulation_progress_url = simulation_response.headers.get('Location', 0)
                    if simulation_progress_url == 0:
                        json_data = await simulation_response.json()
                        if type(json_data) == list:
                            inner_logger.print(f'{datetime.now()} Response data: {json_data}')
                            detail = json_data.get('detail', 0) if isinstance(json_data, dict) else json_data[0].get('detail', 0) if json_data else 0
                        else:
                            detail = json_data.get('detail', 0)
                        if detail == 'SIMULATION_LIMIT_EXCEEDED':
                            inner_logger.print(f'{datetime.now()} 超过了最大回测数量..正在重试(非报错，可忽略此条)')
                            await asyncio.sleep(5)
                        else:
                            inner_logger.print(f'{datetime.now()} detail: {{}}, json_data: {{}}'.format(detail, json_data))
                            inner_logger.print(f'{datetime.now()} Alpha expression is duplicated')
                            await asyncio.sleep(1)
                        return 0
                    else:
                        inner_logger.print(f'{datetime.now()} Simulation progress URL: {{}}'.format(simulation_progress_url))
                        break
            except Exception as e:
                retry_count += 1
                inner_logger.print(f'{datetime.now()} Error occurred (attempt {retry_count}/{max_retries}): {e}')
                if retry_count >= max_retries:
                    inner_logger.print(f'{datetime.now()} Max retries reached, aborting...')
                    return 1
                await asyncio.sleep(60)
        
        max_progress_retries = 10
        progress_retry_count = 0
        while progress_retry_count < max_progress_retries:
            try:
                async with session_manager.session.get(simulation_progress_url) as resp:
                    json_data = await resp.json()
                    headers = resp.headers
                    retry_after = headers.get('Retry-After', 0)
                    if retry_after == 0:
                        status = json_data.get('status', 0)
                        children = json_data.get('children', [])
                        if status == 'ERROR':
                            inner_logger.print(f'{datetime.now()} Error in simulation: {{}}'.format(simulation_progress_url))
                            inner_logger.print(f'{datetime.now()} Error details: {{}}'.format(json_data))
                            return 1
                        elif status == 'COMPLETE':
                            inner_logger.print(f'{datetime.now()} Simulation completed: {{}}'.format(simulation_progress_url))
                            break
                        elif status in ('RUNNING', 'IN_PROGRESS', 'PENDING', 'QUEUED'):
                            inner_logger.print(f'{datetime.now()} Simulation still running (status={{}}): {{}}, waiting...'.format(status, simulation_progress_url))
                            await asyncio.sleep(10)
                        else:
                            inner_logger.print(f'{datetime.now()} Simulation not complete (status={{}}): {{}}'.format(simulation_progress_url))
                            async with session_manager.session.delete(simulation_progress_url) as delete_resp:
                                delete_json_data = await delete_resp.json()
                                if delete_json_data.get('detail', 0) == '未找到。':
                                    inner_logger.print(f'{datetime.now()} Successfully deleted: {{}}'.format(simulation_progress_url))
                                else:
                                    inner_logger.print(f'{datetime.now()} Failed to delete: {{}}'.format(simulation_progress_url))
                            return 1
                    else:
                        await asyncio.sleep(float(retry_after))
            except Exception as e:
                progress_retry_count += 1
                inner_logger.print(f'{datetime.now()} Progress check error (attempt {progress_retry_count}/{max_progress_retries}): {str(e)}')
                if progress_retry_count >= max_progress_retries:
                    inner_logger.print(f'{datetime.now()} Max progress check retries reached')
                    return 2
                await asyncio.sleep(30)
        
        children_list = []
        for child in children:
            try:
                async with session_manager.session.get(f'{brain_api_url}/simulations/{child}') as child_progress:
                    json_data = await child_progress.json()
                    alpha_id = json_data['alpha']
                    alpha_express = json_data['regular']
                    await async_set_alpha_properties(
                        session_manager.session, alpha_id,
                        f'%s' % name,
                        None, None, None, None, tags, inner_logger
                    )
                    async with aiofiles.open(f'records/{name}_simulated_alpha_expression.txt', 'a') as f:
                        await f.write(f'{alpha_express}\n')
            except KeyError:
                inner_logger.print(f'{datetime.now()} Failed to retrieve alpha ID for: {{}}'.format(f'{brain_api_url}/simulations/{child}'))
            except Exception as e:
                inner_logger.print(f'{datetime.now()} An error occurred while setting alpha properties:{str(e)}')
        return 0

async def simulate_multiple_tasks(alpha_list, region_list, decay_list, delay_list, name, neut, maxTrade, stone_bag, n, inner_logger, instrumentType='EQUITY'):
    """
    串行回测 Alpha 表达式。

    参数 n = 每个模拟批次放几个 Alpha（WQ 批量模拟单批上限 10）。
    一次只跑一批，等该批完成后再跑下一批。
    账号全局同时回测上限为 8 个 Alpha，可通过多开任务来占满配额。
    """
    tags = [name]
    if len(alpha_list) == 1:
        alpha_list = alpha_list + alpha_list
        region_list = region_list + region_list
        decay_list = decay_list + decay_list
        delay_list = delay_list + delay_list
    session = await async_login(inner_logger)
    session_start_time = time.time()
    session_expiry_time = 10800
    session_manager = SessionManager(session, session_start_time, session_expiry_time, inner_logger)
    # 每批放 n 个 Alpha（WQ 批量模拟单批上限 10）
    batch_size = min(n, 10)
    alpha_batches = [alpha_list[i:i + batch_size] for i in range(0, len(alpha_list), batch_size)]
    region_batches = [region_list[i:i + batch_size] for i in range(0, len(region_list), batch_size)]
    decay_batches = [decay_list[i:i + batch_size] for i in range(0, len(decay_list), batch_size)]
    delay_batches = [delay_list[i:i + batch_size] for i in range(0, len(delay_list), batch_size)]
    aborted = False
    consecutive_failures = 0
    try:
        for alpha_batch, region_batch, decay_batch, delay_batch in zip(alpha_batches, region_batches, decay_batches, delay_batches):
            rc = await simulate_multi(
                session_manager, alpha_batch, region_batch[0], name, neut,
                decay_batch[0], delay_batch[0], maxTrade, stone_bag, tags,
                asyncio.Semaphore(1), inner_logger, instrumentType
            )
            if rc in (1, 2):
                consecutive_failures += 1
                inner_logger.print(datetime.now(), f'本批回测失败（连续 {consecutive_failures} 批，返回码 {rc}）')
                if consecutive_failures >= 3:
                    inner_logger.print(datetime.now(), '连续 3 批失败，判定会话/网络异常，结束本轮以重新登录')
                    aborted = True
                    break
            else:
                consecutive_failures = 0
    except asyncio.TimeoutError:
        inner_logger.print(f'{datetime.now()} Task group timed out after 6 hours')
    try:
        await session_manager.session.close()
    except Exception as e:
        inner_logger.print(f'{datetime.now()} Error closing session: {str(e)}')
    if aborted:
        raise Exception('连续多批回测失败，已关闭会话，将重新登录后重试')

async def simulate_grouped_tasks(groups, name, neut, maxTrade, stone_bag, n, region, universe, delay, instrumentType, inner_logger):
    """
    一次登录、串行回测多个 decay 分组，全程复用同一个 session。

    groups: [(decay, [alpha_expression, ...]), ...]
    每个 decay 组内再按 n 分批。session 在有效期内只登录一次，
    避免每个 decay 组都新建事件循环 / 新建 session / 重新登录。
    """
    session = await async_login(inner_logger)
    session_start_time = time.time()
    session_expiry_time = 10800
    session_manager = SessionManager(session, session_start_time, session_expiry_time, inner_logger)
    tags = [name]
    semaphore = asyncio.Semaphore(1)
    batch_size = min(n, 10)
    aborted = False
    consecutive_failures = 0
    try:
        for decay, alpha_expr_list in groups:
            for i in range(0, len(alpha_expr_list), batch_size):
                alpha_batch = alpha_expr_list[i:i + batch_size]
                rc = await simulate_multi(
                    session_manager, alpha_batch, (region, universe), name, neut,
                    decay, delay, maxTrade, stone_bag, tags, semaphore,
                    inner_logger, instrumentType
                )
                if rc in (1, 2):
                    consecutive_failures += 1
                    inner_logger.print(datetime.now(), f'本批回测失败（连续 {consecutive_failures} 批，返回码 {rc}）')
                    if consecutive_failures >= 3:
                        inner_logger.print(datetime.now(), '连续 3 批失败，判定会话/网络异常，结束本轮以重新登录')
                        aborted = True
                        break
                else:
                    consecutive_failures = 0
            if aborted:
                break
    finally:
        try:
            await session_manager.session.close()
        except Exception as e:
            inner_logger.print(f'{datetime.now()} Error closing session: {str(e)}')
    if aborted:
        raise Exception('连续多批回测失败，已关闭会话，将重新登录后重试')

def prune(next_alpha_recs, prefix, keep_num):
    output = []
    num_dict = defaultdict(int)
    for rec in next_alpha_recs:
        exp = rec[1]
        field = exp.split(prefix)[-1].split(',')[0]
        if num_dict[field] < keep_num:
            num_dict[field] += 1
            decay = rec[-1]
            exp = rec[1]
            output.append([exp, decay])
    return output

def read_completed_alphas(filepath, inner_logger):
    completed_alphas = set()
    try:
        with open(filepath, 'r') as f:
            for line in f:
                completed_alphas.add(line.strip())
    except FileNotFoundError:
        pass
    return completed_alphas