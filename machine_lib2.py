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
        # 先登录拿到新会话再替换、最后关旧会话，把并发 worker 在途请求被打断的窗口降到最小
        new_session = await async_login(inner_logger=self.inner_logger)
        old_session = self.session
        self.session = new_session
        self.start_time = time.time()
        try:
            await old_session.close()
        except Exception:
            pass

# ============================ 流水线回测（单 alpha 提交 + 常驻并发槽位） ============================
#
# 旧实现：批量 POST 一批（<=8 个），轮询父任务等整批全部 COMPLETE 后才提交下一批
#         （整批屏障：先完成的槽位要空等最慢的任务；平台变慢时木桶效应被放大）。
# 现实现：单个 alpha 提交，n 个常驻 worker 各自独立「提交 -> 轮询 -> 完成」，完成一个
#         立刻补一个，槽位不空转；PATCH 改名/写本地记录在后台并发执行，不占模拟槽位。

BRAIN_API_URL = 'https://api.worldquantbrain.com'
SIMULATIONS_URL = f'{BRAIN_API_URL}/simulations'
# 账号全局「同时回测中的 Alpha」上限为 8
MAX_CONCURRENT_SIMULATIONS = 8
# 改名打 tag 是平台普通写接口，限流较严，后台并发收敛到 2（不占用模拟槽位，慢点不影响吞吐）
MAX_CONCURRENT_PATCH = 2
SESSION_EXPIRY_TIME = 10800
POST_MAX_RETRIES = 5            # 提交阶段网络异常重试次数
PROGRESS_MAX_RETRIES = 10       # 进度查询网络异常重试次数
PATCH_MAX_RETRIES = 4          # 改名打 tag 限流/网关错误重试次数
LIMIT_WAIT_MAX = 30             # 撞 SIMULATION_LIMIT_EXCEEDED 后最多等待次数
CONSECUTIVE_FAILURE_ABORT = 10  # 连续多少个任务失败判定会话异常
POST_PROCESS_GATHER_TIMEOUT = 120  # 收尾时等待后台改名/写记录的上限（秒）


def _alpha_url(alpha_id):
    return f'{BRAIN_API_URL}/alphas/{alpha_id}'


def _build_simulation_payload(alpha_expression, region_info, instrumentType, decay, delay, neut, maxTrade):
    region, uni = region_info
    return {
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
        'regular': f'{alpha_expression}'
    }


async def _refresh_if_needed(session_manager, refresh_lock):
    """会话过期则重新登录；多 worker 并发时只允许一个刷新，其余等待复用新会话。"""
    if time.time() - session_manager.start_time <= session_manager.expiry_time:
        return
    async with refresh_lock:
        if time.time() - session_manager.start_time > session_manager.expiry_time:
            await session_manager.refresh_session()


def _is_transient_session_error(exc):
    """会话被并发刷新关闭 / 连接中断类错误：换新会话后短重试即可，不计入网络故障重试。"""
    if isinstance(exc, aiohttp.ClientConnectionError):
        return True
    return 'Session is closed' in str(exc)


async def _patch_alpha_with_retry(session_manager, alpha_id, name, tags, inner_logger):
    """改名打 tag；遇 429 限流 / 5xx 网关错误时遵从 Retry-After 并指数退避重试。
    始终使用 session_manager 的最新会话，兼容重试期间会话被其他 worker 刷新。"""
    url = _alpha_url(alpha_id)
    params = {'category': None, 'name': name, 'tags': tags}
    attempt = 0
    switch_retries = 0
    while attempt < PATCH_MAX_RETRIES:
        try:
            async with session_manager.session.patch(url, json=params) as response:
                if response.status == 200:
                    inner_logger.print(f'Alpha {alpha_id} properties updated successfully! Tag: {tags}')
                    return True
                retry_after = response.headers.get('Retry-After')
                if response.status in (429, 500, 502, 503, 504):
                    attempt += 1
                    wait = float(retry_after) if retry_after else min(2 ** attempt, 20)
                    body = await response.text()
                    inner_logger.print(
                        f'{datetime.now()} PATCH alpha {alpha_id} 返回 {response.status}，'
                        f'{wait}s 后重试（{attempt}/{PATCH_MAX_RETRIES}）: {body[:200]}'
                    )
                    await asyncio.sleep(wait)
                    continue
                inner_logger.print(
                    f'Failed to update alpha {alpha_id}. Status code: {response.status}, '
                    f'Response: {await response.text()}'
                )
                return False
        except Exception as e:
            if _is_transient_session_error(e):
                switch_retries += 1
                if switch_retries > 20:
                    inner_logger.print(f'{datetime.now()} PATCH alpha {alpha_id} 等待新会话超时，放弃改名')
                    return False
                inner_logger.print(f'{datetime.now()} PATCH 期间会话被刷新，1s 后用新会话重试: {e}')
                await asyncio.sleep(1)
                continue
            attempt += 1
            wait = min(2 ** attempt, 20)
            inner_logger.print(
                f'{datetime.now()} PATCH alpha {alpha_id} 异常（{attempt}/{PATCH_MAX_RETRIES}）: {e}，{wait}s 后重试'
            )
            await asyncio.sleep(wait)
    inner_logger.print(f'{datetime.now()} PATCH alpha {alpha_id} 重试 {PATCH_MAX_RETRIES} 次仍失败，跳过改名（本地记录仍会写入）')
    return False


async def _post_process(session_manager, alpha_id, alpha_expr, name, tags,
                        inner_logger, refresh_lock, record_lock, patch_semaphore):
    """模拟完成后的收尾：PATCH 改名打 tag + 追加写入本地记录。后台并发执行，不占用模拟槽位。"""
    try:
        await _refresh_if_needed(session_manager, refresh_lock)
        async with patch_semaphore:
            await _patch_alpha_with_retry(session_manager, alpha_id, name, tags, inner_logger)
    except Exception as e:
        inner_logger.print(f'{datetime.now()} PATCH 改名异常 alpha {alpha_id}: {e}')
    try:
        async with record_lock:
            async with aiofiles.open(f'records/{name}_simulated_alpha_expression.txt', 'a') as f:
                await f.write(f'{alpha_expr}\n')
    except Exception as e:
        inner_logger.print(f'{datetime.now()} 写入本地记录异常 alpha {alpha_id}: {e}')


async def simulate_one(session_manager, expression, region_info, instrumentType,
                       decay, delay, neut, maxTrade, tags, inner_logger,
                       refresh_lock, record_lock, patch_semaphore, post_tasks):
    """提交并轮询单个 alpha 模拟；成功后把改名/写记录丢后台，worker 立即补下一个。

    返回: 'ok' / 'duplicate' / 'error' / 'progress_failed' / 'limit_exceeded'
    """
    region, uni = region_info
    payload = _build_simulation_payload(expression, region_info, instrumentType,
                                        decay, delay, neut, maxTrade)
    inner_logger.print(
        f'{datetime.now()} Simulating for alpha: {expression}, region: {region}, '
        f'universe: {uni}, decay: {decay}, delay: {delay}'
    )

    # ---- 1) 提交，直到拿到 progress URL ----
    progress_url = None
    limit_waits = 0
    post_retries = 0
    switch_retries = 0
    while progress_url is None:
        await _refresh_if_needed(session_manager, refresh_lock)
        try:
            async with session_manager.session.post(SIMULATIONS_URL, json=payload) as resp:
                location = resp.headers.get('Location')
                if location:
                    progress_url = location
                    inner_logger.print(f'{datetime.now()} Simulation progress URL: {location}')
                    break
                try:
                    body = await resp.json(content_type=None)
                except Exception:
                    body = {}
                detail = body.get('detail', 0) if isinstance(body, dict) else 0
                if detail == 'SIMULATION_LIMIT_EXCEEDED':
                    limit_waits += 1
                    if limit_waits > LIMIT_WAIT_MAX:
                        inner_logger.print(
                            f'{datetime.now()} 回测槽位持续已满（等待 {LIMIT_WAIT_MAX} 次仍未释放），放弃该任务。'
                            f'若开了多个终端，请让各任务 n_jobs 之和 <= {MAX_CONCURRENT_SIMULATIONS}'
                        )
                        return 'limit_exceeded'
                    wait = min(5 + limit_waits * 2, 30)
                    inner_logger.print(
                        f'{datetime.now()} 回测槽位已满（SIMULATION_LIMIT_EXCEEDED），{wait}s 后重试（非报错，可忽略此条）'
                    )
                    await asyncio.sleep(wait)
                else:
                    # 表达式已在平台存在 / 校验失败等不可重试情形，跳过该表达式（与旧实现一致，不写本地记录）
                    inner_logger.print(
                        f'{datetime.now()} 提交被拒绝，跳过该表达式（可能已在平台存在）。'
                        f'status={resp.status}, detail={detail}, body={body}'
                    )
                    return 'duplicate'
        except Exception as e:
            if _is_transient_session_error(e):
                switch_retries += 1
                if switch_retries > 20:
                    inner_logger.print(f'{datetime.now()} 等待新会话超时，放弃该任务: {e}')
                    return 'error'
                inner_logger.print(f'{datetime.now()} 会话正在被刷新，1s 后用新会话重试提交: {e}')
                await asyncio.sleep(1)
                continue
            post_retries += 1
            if post_retries >= POST_MAX_RETRIES:
                inner_logger.print(f'{datetime.now()} 提交阶段连续 {POST_MAX_RETRIES} 次异常，放弃该任务: {e}')
                return 'error'
            wait = min(10 * post_retries, 60)
            inner_logger.print(f'{datetime.now()} 提交异常（{post_retries}/{POST_MAX_RETRIES}）: {e}，{wait}s 后重试')
            await asyncio.sleep(wait)

    # ---- 2) 轮询进度 ----
    progress_errors = 0
    switch_progress = 0
    data = None
    while True:
        try:
            async with session_manager.session.get(progress_url) as resp:
                retry_after = resp.headers.get('Retry-After', 0)
                if retry_after:
                    # 平台明确告知下次查询时间（模拟进行中的常态），遵从平台节奏
                    await asyncio.sleep(float(retry_after))
                    continue
                data = await resp.json(content_type=None)
                status = data.get('status', 0)
                if status == 'COMPLETE':
                    inner_logger.print(f'{datetime.now()} Simulation completed: {progress_url}')
                    break
                elif status == 'ERROR':
                    inner_logger.print(f'{datetime.now()} Error in simulation: {progress_url}')
                    inner_logger.print(f'{datetime.now()} Error details: {data}')
                    return 'error'
                elif status in ('RUNNING', 'IN_PROGRESS', 'PENDING', 'QUEUED'):
                    inner_logger.print(
                        f'{datetime.now()} Simulation still running (status={status}): {progress_url}, waiting...'
                    )
                    await asyncio.sleep(10)
                else:
                    inner_logger.print(f'{datetime.now()} Simulation not complete (status={status}): {progress_url}')
                    try:
                        async with session_manager.session.delete(progress_url) as delete_resp:
                            delete_body = await delete_resp.json(content_type=None)
                            inner_logger.print(f'{datetime.now()} 已清理异常模拟: {delete_body}')
                    except Exception as e:
                        inner_logger.print(f'{datetime.now()} 清理异常模拟失败: {e}')
                    return 'error'
        except Exception as e:
            if _is_transient_session_error(e):
                switch_progress += 1
                if switch_progress > 20:
                    inner_logger.print(f'{datetime.now()} 等待新会话超时，放弃该任务的进度查询: {e}')
                    return 'progress_failed'
                inner_logger.print(f'{datetime.now()} 会话正在被刷新，1s 后用新会话继续轮询: {e}')
                await asyncio.sleep(1)
                continue
            progress_errors += 1
            if progress_errors >= PROGRESS_MAX_RETRIES:
                inner_logger.print(f'{datetime.now()} 进度查询连续 {PROGRESS_MAX_RETRIES} 次异常，放弃该任务: {e}')
                return 'progress_failed'
            inner_logger.print(
                f'{datetime.now()} Progress check error (attempt {progress_errors}/{PROGRESS_MAX_RETRIES}): {str(e)}'
            )
            await asyncio.sleep(30)

    # ---- 3) 取 alpha id（单个任务直接在进度对象里；兼容平台偶发的 children 结构） ----
    alpha_id = data.get('alpha')
    alpha_expr = data.get('regular') or expression
    if not alpha_id:
        children = data.get('children') or []
        if children:
            try:
                async with session_manager.session.get(f'{SIMULATIONS_URL}/{children[0]}') as child_resp:
                    child_data = await child_resp.json(content_type=None)
                    alpha_id = child_data.get('alpha')
                    alpha_expr = child_data.get('regular') or alpha_expr
            except Exception as e:
                inner_logger.print(f'{datetime.now()} 读取 child 模拟结果失败: {e}')
    if not alpha_id:
        inner_logger.print(f'{datetime.now()} 模拟完成但未能取得 alpha id: {data}')
        return 'error'

    # ---- 4) 改名打 tag + 写本地记录：后台并发执行，worker 立即去补下一个槽位 ----
    task = asyncio.create_task(_post_process(
        session_manager, alpha_id, alpha_expr, tags[0], tags,
        inner_logger, refresh_lock, record_lock, patch_semaphore
    ))
    post_tasks.add(task)
    task.add_done_callback(post_tasks.discard)
    return 'ok'


async def _run_pipeline(task_items, name, neut, maxTrade, n, inner_logger, instrumentType):
    """task_items: [(expression, region_info, decay, delay), ...]

    启动 n 个常驻 worker 并发回测，完成一个补一个；PATCH 改名/写记录后台并发。
    返回各类结果计数；连续失败达阈值则抛异常，交由上层重新登录后重试。
    """
    total = len(task_items)
    if total == 0:
        inner_logger.print(f'{datetime.now()} 没有需要回测的表达式，跳过。')
        return {}

    concurrency = max(1, min(int(n), MAX_CONCURRENT_SIMULATIONS))
    if int(n) > concurrency:
        inner_logger.print(
            f'{datetime.now()} n_jobs={n} 超过账号全局并发上限 {MAX_CONCURRENT_SIMULATIONS}，已按 {concurrency} 执行'
        )

    session = await async_login(inner_logger)
    session_manager = SessionManager(session, time.time(), SESSION_EXPIRY_TIME, inner_logger)

    queue = asyncio.Queue()
    for item in task_items:
        queue.put_nowait(item)

    refresh_lock = asyncio.Lock()
    record_lock = asyncio.Lock()
    patch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PATCH)
    post_tasks = set()
    counters = {'ok': 0, 'duplicate': 0, 'error': 0, 'progress_failed': 0, 'limit_exceeded': 0}
    state = {'consecutive_failures': 0, 'finished': 0}
    state_lock = asyncio.Lock()
    abort_event = asyncio.Event()

    inner_logger.print(
        f'{datetime.now()} 开始回测：共 {total} 个表达式，{concurrency} 个并发槽位'
    )

    async def worker(worker_id):
        while not abort_event.is_set():
            try:
                expression, region_info, decay, delay = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                rc = await simulate_one(
                    session_manager, expression, region_info, instrumentType,
                    decay, delay, neut, maxTrade, [name], inner_logger,
                    refresh_lock, record_lock, patch_semaphore, post_tasks
                )
            except Exception as e:
                inner_logger.print(f'{datetime.now()} worker-{worker_id} 未预期异常: {e}')
                rc = 'error'
            async with state_lock:
                counters[rc] = counters.get(rc, 0) + 1
                state['finished'] += 1
                if rc in ('ok', 'duplicate'):
                    state['consecutive_failures'] = 0
                else:
                    state['consecutive_failures'] += 1
                    if state['consecutive_failures'] >= CONSECUTIVE_FAILURE_ABORT:
                        abort_event.set()

    workers = [asyncio.create_task(worker(i + 1)) for i in range(concurrency)]
    await asyncio.gather(*workers, return_exceptions=True)

    # 收尾：等后台改名/写记录完成，避免丢 tag 与本地记录
    pending = list(post_tasks)
    if pending:
        inner_logger.print(f'{datetime.now()} 模拟全部结束，等待 {len(pending)} 个改名/写记录收尾...')
        _, still_pending = await asyncio.wait(pending, timeout=POST_PROCESS_GATHER_TIMEOUT)
        if still_pending:
            inner_logger.print(
                f'{datetime.now()} 警告：{len(still_pending)} 个改名/写记录在 {POST_PROCESS_GATHER_TIMEOUT}s 内未完成'
            )

    try:
        await session_manager.session.close()
    except Exception as e:
        inner_logger.print(f'{datetime.now()} Error closing session: {str(e)}')

    inner_logger.print(
        f'{datetime.now()} 流水线结束：成功 {counters["ok"]}，已存在跳过 {counters["duplicate"]}，'
        f'模拟失败 {counters["error"]}，进度失败 {counters["progress_failed"]}，槽位不足放弃 {counters["limit_exceeded"]}'
    )
    if abort_event.is_set():
        raise Exception(
            f'连续 {CONSECUTIVE_FAILURE_ABORT} 个任务失败，判定会话/网络异常，已关闭会话，将重新登录后重试'
        )
    return counters


async def simulate_multiple_tasks(alpha_list, region_list, decay_list, delay_list, name, neut, maxTrade, stone_bag, n, inner_logger, instrumentType='EQUITY'):
    """
    流水线回测 Alpha 表达式。

    参数 n = 并发槽位数（同时在跑的 Alpha 数），账号全局上限 8：
    单终端 n=8 即跑满全部槽位，无需多开；多开终端时各任务 n_jobs 之和应 <= 8。
    每个槽位完成一个 Alpha 立即提交下一个（非整批等待），改名/写记录在后台并发执行。
    """
    if len(alpha_list) == 0:
        inner_logger.print(f'{datetime.now()} 没有需要回测的表达式，跳过。')
        return {}
    task_items = list(zip(alpha_list, region_list, decay_list, delay_list))
    return await _run_pipeline(task_items, name, neut, maxTrade, n, inner_logger, instrumentType)


async def simulate_grouped_tasks(groups, name, neut, maxTrade, stone_bag, n, region, universe, delay, instrumentType, inner_logger):
    """
    一次登录、流水线回测多个 decay 分组，全程复用同一个 session。

    groups: [(decay, [alpha_expression, ...]), ...]
    所有表达式展平后统一进入并发槽位池，按各自 decay 提交，完成一个补一个。
    session 在有效期内只登录一次，避免每个 decay 组都新建事件循环 / 重新登录。
    """
    task_items = []
    for dec, exprs in groups:
        for expr in exprs:
            task_items.append((expr, (region, universe), dec, delay))
    if not task_items:
        inner_logger.print(f'{datetime.now()} 没有需要回测的表达式，跳过。')
        return {}
    return await _run_pipeline(task_items, name, neut, maxTrade, n, inner_logger, instrumentType)

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
