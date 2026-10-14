import os
import sys
import requests
import time
import json
import pandas as pd
from itertools import product
from collections import defaultdict
from datetime import datetime, timedelta
import aiofiles
import re
from config import ROOT_PATH
import logging

def query_payment(s):
    payment_url = 'https://api.worldquantbrain.com/users/self/activities/base-payment'
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        response = s.get(payment_url, headers={'accept': 'application/json;version=3.0'}, timeout=10)
        if not response.ok:
            raise Exception(f'请求失败：{response.status_code} {response.reason}')
        data = response.json()
        base_records = data.get('records', {}).get('records', [])
        if base_records:
            today_record = base_records[-1]
            day = today_record[0]
            regular = today_record[1]
            super_payment = today_record[2] if len(today_record) > 2 else '无数据'
            result = {'status': 'success', 'data': {'day': day, 'regular': regular, 'super_payment': super_payment, 'has_super': len(today_record) > 2}}
        else:
            result = {'status': 'success', 'message': f'今日({today})暂无收入记录'}
        return result
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

def query_backtest_count(s):
    utc_now = datetime.utcnow()
    china_time = utc_now + timedelta(hours=8)
    target_time = china_time - timedelta(hours=13)
    date = target_time.strftime('%Y-%m-%d')
    next_date = (target_time + timedelta(days=1)).strftime('%Y-%m-%d')
    api_url = f'https://api.worldquantbrain.com/users/self/alphas?limit=100&offset=0&status=UNSUBMITTED%1FIS_FAIL&dateCreated%3E={date}T00:00:00-05:00&dateCreated%3C={next_date}T00:00:00-05:00&order=-dateCreated&hidden=false'
    try:
        response = s.get(api_url, headers={'accept': 'application/json;version=3.0'}, timeout=10)
        if not response.ok:
            raise Exception(f'请求失败：{response.status_code} {response.reason}')
        data = response.json()
        count = data.get('count', 0)
        return {'status': 'success', 'data': {'count': count, 'date': date}}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

def get_group_fields(region, delay, universe, inner_logger):
    group_path = f'{ROOT_PATH}/groups.txt'
    try:
        with open(group_path, 'r', encoding='utf-8') as file:
            content = file.read()
        groups_dict = json.loads(content)
        key = f'{region}_{delay}_{universe}'
        return groups_dict.get(key, [])
    except FileNotFoundError:
        inner_logger.print(f'错误：文件 {group_path} 未找到')
        return []
    except json.JSONDecodeError:
        inner_logger.print(f'错误：文件 {group_path} 内容不是有效的JSON格式')
        return []
    except Exception as e:
        inner_logger.print(f'处理文件时发生错误：{str(e)}')
        return []

def get_cached_genius_leaderboard():
    now = datetime.now()
    month = now.month
    if month < 4:
        CURRENT_SEASON = f'{now.year}-01-01'
    elif month < 7:
        CURRENT_SEASON = f'{now.year}-04-01'
    elif month < 10:
        CURRENT_SEASON = f'{now.year}-07-01'
    else:
        CURRENT_SEASON = f'{now.year}-10-01'
    genius_cache_path = os.path.join(ROOT_PATH, 'records', 'genius', f'genius_leaderboard_{CURRENT_SEASON}.pkl')
    if os.path.exists(genius_cache_path):
        df = pd.read_pickle(genius_cache_path)
        return df.to_dict('records')
    return None

def get_raw_consultant_data_path():
    now = datetime.now()
    month = now.month
    if month < 4:
        CURRENT_SEASON = f'{now.year}-01-01'
    elif month < 7:
        CURRENT_SEASON = f'{now.year}-04-01'
    elif month < 10:
        CURRENT_SEASON = f'{now.year}-07-01'
    else:
        CURRENT_SEASON = f'{now.year}-10-01'
    return os.path.join(ROOT_PATH, 'records', 'consultant', f'consultant_data_{CURRENT_SEASON}.pkl')

def get_raw_genius_data_path():
    now = datetime.now()
    month = now.month
    if month < 4:
        CURRENT_SEASON = f'{now.year}-01-01'
    elif month < 7:
        CURRENT_SEASON = f'{now.year}-04-01'
    elif month < 10:
        CURRENT_SEASON = f'{now.year}-07-01'
    else:
        CURRENT_SEASON = f'{now.year}-10-01'
    return os.path.join(ROOT_PATH, 'records', 'genius', f'raw_genius_data_{CURRENT_SEASON}.pkl')

def fetch_all_data_sync_with_progress(s, base_url, base_params):
    params = {**base_params, 'limit': 1, 'offset': 0}
    try:
        initial_response = s.get(base_url, params=params, timeout=10)
        initial_response.raise_for_status()
        count = initial_response.json().get('count', 0)
    except requests.RequestException as e:
        yield {'type': 'error', 'message': str(e)}
        return
    if count == 0:
        yield {'type': 'count', 'total': 0, 'total_pages': 0}
        return
    total_pages = (count + 99) // 100
    yield {'type': 'count', 'total': count, 'total_pages': total_pages}
    all_data = []
    limit = 100
    for i, offset in enumerate(range(0, count, limit)):
        page_params = {**base_params, 'limit': limit, 'offset': offset}
        try:
            response = s.get(base_url, params=page_params, timeout=10)
            response.raise_for_status()
            page_data = response.json().get('results', [])
            all_data.extend(page_data)
            yield {'type': 'page', 'processed_pages': i + 1, 'total_pages': total_pages, 'processed_records': len(all_data), 'total_records': count}
        except requests.RequestException as e:
            yield {'type': 'error', 'message': str(e)}
    yield {'type': 'finished', 'data': all_data}

def get_genius_leaderboard_streaming(s):
    now = datetime.now()
    month = now.month
    if month < 4:
        CURRENT_SEASON = f'{now.year}-01-01'
    elif month < 7:
        CURRENT_SEASON = f'{now.year}-04-01'
    elif month < 10:
        CURRENT_SEASON = f'{now.year}-07-01'
    else:
        CURRENT_SEASON = f'{now.year}-10-01'
    genius_params = {'user': {'date': CURRENT_SEASON, 'aggregate': CURRENT_SEASON}}
    GENIUS_API_URL = 'https://api.worldquantbrain.com/consultant/boards/genius'
    genius_data = []
    total_genius_pages = 0
    yield json.dumps({'status': 'progress', 'message': '开始获取 Genius 数据...', 'stage': 'genius_fetch', 'progress': 0}) + '\n'
    fetcher = fetch_all_data_sync_with_progress(s, GENIUS_API_URL, genius_params)
    for update in fetcher:
        if update['type'] == 'count':
            total_genius_pages = update['total_pages']
        elif update['type'] == 'page':
            progress = (update['processed_pages'] / total_genius_pages * 100) if total_genius_pages > 0 else 100
            yield json.dumps({'status': 'progress', 'message': f'正在获取 Genius 数据... ({update["processed_pages"]}/{total_genius_pages} 页)', 'stage': 'genius_fetch', 'progress': progress}) + '\n'
        elif update['type'] == 'finished':
            genius_data = update['data']
        elif update['type'] == 'error':
            yield json.dumps({'status': 'error', 'message': update['message']}) + '\n'
            return
    yield json.dumps({'status': 'progress', 'message': '数据整合与排名计算中...', 'stage': 'processing', 'progress': 100}) + '\n'
    raw_genius_cache_path = get_raw_genius_data_path()
    pd.DataFrame(genius_data).to_pickle(raw_genius_cache_path)
    consultant_cache_dir = os.path.join(ROOT_PATH, 'records', 'consultant')
    consultant_cache_path = os.path.join(consultant_cache_dir, f'consultant_data_{CURRENT_SEASON}.pkl')
    leader_data = []
    if os.path.exists(consultant_cache_path):
        leader_data = pd.read_pickle(consultant_cache_path).to_dict('records')
    leader_data_map = {user['user']: user for user in leader_data}
    merged_data = []
    for user in genius_data:
        leader_info = leader_data_map.get(user['user'])
        if leader_info:
            user.update(leader_info)
        merged_data.append(user)
    processed_data = [user for user in merged_data if user.get('alphaCount', 0) > 0]
    df = pd.DataFrame(processed_data)
    combined_fields = ['combinedAlphaPerformance', 'combinedPowerPoolAlphaPerformance', 'combinedSelectedAlphaPerformance']
    existing_combined_fields = [col for col in combined_fields if col in df.columns]
    if len(existing_combined_fields) > 1:
        df['combinedAlphaPerformance'] = df[existing_combined_fields].max(axis=1, skipna=True)
        df['combinedAlphaPerformance'] = df['combinedAlphaPerformance'].fillna(0)
    elif len(existing_combined_fields) == 1:
        df['combinedAlphaPerformance'] = df[existing_combined_fields[0]].fillna(0)
    else:
        df['combinedAlphaPerformance'] = 0
    all_metrics = ['operatorCount', 'fieldCount', 'communityActivity', 'maxSimulationStreak', 'operatorAvg', 'fieldAvg']
    for metric in all_metrics:
        if metric not in df.columns:
            df[metric] = 0
    df[all_metrics] = df[all_metrics].fillna(0)
    LEVEL_CRITERIA = {
        'expert': {'alphaCount': 10, 'pyramidCount': 10, 'combinedAlphaPerformance': 0.5},
        'master': {'alphaCount': 120, 'pyramidCount': 30, 'combinedAlphaPerformance': 1},
        'grandmaster': {'alphaCount': 220, 'pyramidCount': 60, 'combinedAlphaPerformance': 2}
    }
    HIGHER_IS_BETTER_METRICS = ['operatorCount', 'fieldCount', 'communityActivity', 'maxSimulationStreak']
    LOWER_IS_BETTER_METRICS = ['operatorAvg', 'fieldAvg']
    ALL_METRICS = HIGHER_IS_BETTER_METRICS + LOWER_IS_BETTER_METRICS
    for level in ['gold', 'expert', 'master', 'grandmaster']:
        if level == 'gold':
            candidate_mask = pd.Series(True, index=df.index)
        else:
            criteria = LEVEL_CRITERIA[level]
            candidate_mask = pd.Series(True, index=df.index)
            for k, v in criteria.items():
                candidate_mask &= (df[k].fillna(0) >= v)
        candidate_indices = df[candidate_mask].index
        for metric in ALL_METRICS:
            ascending = metric in LOWER_IS_BETTER_METRICS
            ranks = df.loc[candidate_indices, metric].rank(method='min', ascending=ascending)
            df.loc[candidate_indices, f'{level}{metric}Rank'] = ranks
    for level in ['gold', 'expert', 'master', 'grandmaster']:
        level_rank_cols = [f'{level}{metric}Rank' for metric in ALL_METRICS if f'{level}{metric}Rank' in df.columns]
        df[f'{level}TotalRank'] = df[level_rank_cols].fillna(0).sum(axis=1)
        if level != 'gold':
            criteria = LEVEL_CRITERIA[level]
            candidate_mask = pd.Series(True, index=df.index)
            for k, v in criteria.items():
                candidate_mask &= (df[k].fillna(0) >= v)
            df.loc[~candidate_mask, f'{level}TotalRank'] = float('inf')
    df['achievedLevel'] = 'gold'
    expert_mask = (df['alphaCount'].fillna(0) >= 10) & (df['pyramidCount'].fillna(0) >= 10) & (df['combinedAlphaPerformance'].fillna(0) >= 0.5)
    df.loc[expert_mask, 'achievedLevel'] = 'expert'
    master_mask = (df['alphaCount'].fillna(0) >= 120) & (df['pyramidCount'].fillna(0) >= 30) & (df['combinedAlphaPerformance'].fillna(0) >= 1)
    df.loc[master_mask, 'achievedLevel'] = 'master'
    grandmaster_mask = (df['alphaCount'].fillna(0) >= 220) & (df['pyramidCount'].fillna(0) >= 60) & (df['combinedAlphaPerformance'].fillna(0) >= 2)
    df.loc[grandmaster_mask, 'achievedLevel'] = 'grandmaster'
    df['finalLevel'] = 'gold'
    base_count = len(df[df['alphaCount'].fillna(0) >= 10])
    QUOTAS = {
        'grandmaster': int(base_count * 0.02),
        'master': int(base_count * 0.08),
        'expert': int(base_count * 0.2)
    }
    levels_to_assign = {
        'expert': ['expert', 'master', 'grandmaster'],
        'master': ['master', 'grandmaster'],
        'grandmaster': ['grandmaster']
    }
    quota_map = {
        'expert': QUOTAS['expert'] + QUOTAS['master'] + QUOTAS['grandmaster'],
        'master': QUOTAS['master'] + QUOTAS['grandmaster'],
        'grandmaster': QUOTAS['grandmaster']
    }
    df = df.sort_index()
    for level in ['expert', 'master', 'grandmaster']:
        df = df.sort_values(by=f'{level}TotalRank', kind='mergesort')
        candidates_df = df.head(quota_map[level])
        achieved_mask = candidates_df['achievedLevel'].isin(levels_to_assign[level])
        df.loc[candidates_df[achieved_mask].index, 'finalLevel'] = level
    def calculate_show_rank(row):
        level = row['finalLevel']
        total_rank = row.get(f'{level}TotalRank', 0)
        if total_rank == float('inf'):
            total_rank = 999999
        if level == 'grandmaster':
            return 300000 - total_rank
        elif level == 'master':
            return 200000 - total_rank
        elif level == 'expert':
            return 100000 - total_rank
        else:
            return -total_rank
    df['showRank'] = df.apply(calculate_show_rank, axis=1)
    df = df.sort_values(by='showRank', ascending=False).reset_index()
    df['finalRank'] = df.index + 1
    df = df.rename(columns={'finalRank': 'rank', 'user': 'username', 'finalLevel': 'level'})
    output = df[['rank', 'username', 'level', 'alphaCount', 'pyramidCount', 'combinedAlphaPerformance', 'showRank']].to_dict('records')
    genius_cache_dir = os.path.join(ROOT_PATH, 'records', 'genius')
    os.makedirs(genius_cache_dir, exist_ok=True)
    genius_cache_path = os.path.join(genius_cache_dir, f'genius_leaderboard_{CURRENT_SEASON}.pkl')
    pd.DataFrame(output).to_pickle(genius_cache_path)
    yield json.dumps({'status': 'completed', 'data': output}) + '\n'

def get_consultant_data_streaming(s):
    now = datetime.now()
    month = now.month
    if month < 4:
        CURRENT_SEASON = f'{now.year}-01-01'
    elif month < 7:
        CURRENT_SEASON = f'{now.year}-04-01'
    elif month < 10:
        CURRENT_SEASON = f'{now.year}-07-01'
    else:
        CURRENT_SEASON = f'{now.year}-10-01'
    leader_params = {'aggregate': CURRENT_SEASON, 'user': CURRENT_SEASON}
    LEADER_API_URL = 'https://api.worldquantbrain.com/consultant/boards/leader'
    leader_data = []
    total_leader_pages = 0
    yield json.dumps({'status': 'progress', 'message': '开始获取 Consultant 数据...', 'stage': 'leader_fetch', 'progress': 0}) + '\n'
    fetcher = fetch_all_data_sync_with_progress(s, LEADER_API_URL, leader_params)
    for update in fetcher:
        if update['type'] == 'count':
            total_leader_pages = update['total_pages']
        elif update['type'] == 'page':
            progress = (update['processed_pages'] / total_leader_pages * 100) if total_leader_pages > 0 else 100
            yield json.dumps({'status': 'progress', 'message': f'正在获取 Consultant 数据... ({update["processed_pages"]}/{total_leader_pages} 页)', 'stage': 'leader_fetch', 'progress': progress}) + '\n'
        elif update['type'] == 'finished':
            leader_data = update['data']
        elif update['type'] == 'error':
            yield json.dumps({'status': 'error', 'message': update['message']}) + '\n'
            return
    consultant_cache_dir = os.path.join(ROOT_PATH, 'records', 'consultant')
    os.makedirs(consultant_cache_dir, exist_ok=True)
    consultant_cache_path = os.path.join(consultant_cache_dir, f'consultant_data_{CURRENT_SEASON}.pkl')
    pd.DataFrame(leader_data).to_pickle(consultant_cache_path)
    yield json.dumps({'status': 'completed', 'message': f'Consultant 数据已成功获取并缓存 ({len(leader_data)} 条记录).'}) + '\n'

def get_consultant_analysis():
    now = datetime.now()
    month = now.month
    if month < 4:
        CURRENT_SEASON = f'{now.year}-01-01'
    elif month < 7:
        CURRENT_SEASON = f'{now.year}-04-01'
    elif month < 10:
        CURRENT_SEASON = f'{now.year}-07-01'
    else:
        CURRENT_SEASON = f'{now.year}-10-01'
    genius_cache_path = os.path.join(ROOT_PATH, 'records', 'genius', f'raw_genius_data_{CURRENT_SEASON}.pkl')
    consultant_cache_path = os.path.join(ROOT_PATH, 'records', 'consultant', f'consultant_data_{CURRENT_SEASON}.pkl')
    if not os.path.exists(genius_cache_path) or not os.path.exists(consultant_cache_path):
        return None
    genius_df = pd.read_pickle(genius_cache_path)
    consultant_df = pd.read_pickle(consultant_cache_path)
    merged_df = pd.merge(consultant_df, genius_df[['user', 'geniusLevel']], on='user', how='inner')
    level_order = ['GOLD', 'EXPERT', 'MASTER', 'GRANDMASTER']
    merged_df['geniusLevel'] = pd.Categorical(merged_df['geniusLevel'], categories=level_order, ordered=True)
    analysis_results = []
    for level in level_order:
        level_data = merged_df[merged_df['geniusLevel'] == level]
        if len(level_data) == 0:
            continue
        weight_stats = {
            'metric': 'weightFactor',
            'count': len(level_data),
            'mean': level_data['weightFactor'].mean(),
            'median': level_data['weightFactor'].median(),
            'std': level_data['weightFactor'].std(),
            'min': level_data['weightFactor'].min(),
            'max': level_data['weightFactor'].max(),
            'q25': level_data['weightFactor'].quantile(0.25),
            'q75': level_data['weightFactor'].quantile(0.75)
        }
        value_stats = {
            'metric': 'valueFactor',
            'count': len(level_data),
            'mean': level_data['valueFactor'].mean(),
            'median': level_data['valueFactor'].median(),
            'std': level_data['valueFactor'].std(),
            'min': level_data['valueFactor'].min(),
            'max': level_data['valueFactor'].max(),
            'q25': level_data['valueFactor'].quantile(0.25),
            'q75': level_data['valueFactor'].quantile(0.75)
        }
        analysis_results.append({
            'level': level,
            'userCount': len(level_data),
            'weightFactor': weight_stats,
            'valueFactor': value_stats
        })
    return analysis_results

def _alpha_cache_paths():
    cache_dir = os.path.join(ROOT_PATH, 'records', 'alpha_metrics')
    os.makedirs(cache_dir, exist_ok=True)
    data_path = os.path.join(cache_dir, 'alphas.pkl')
    meta_path = os.path.join(cache_dir, 'meta.json')
    return cache_dir, data_path, meta_path

def _read_alpha_cache():
    _, data_path, meta_path = _alpha_cache_paths()
    df = pd.read_pickle(data_path) if os.path.exists(data_path) else None
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            meta = {}
    return df, meta

def _write_alpha_cache(df, meta):
    _, data_path, meta_path = _alpha_cache_paths()
    if df is not None:
        df.to_pickle(data_path)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)

def _get_initial_start_date(logger):
    default_start_date = '2024-01-01'
    logger.info(f'首次拉取个人评分数据，使用默认起始日期: {default_start_date}')
    return default_start_date

def _fetch_alpha_metrics_page(s, start_date, end_date, limit, offset):
    url = f'https://api.worldquantbrain.com/users/self/alphas?limit={limit}&offset={offset}&status!=UNSUBMITTED%1FIS_FAIL&dateSubmitted%3E={start_date}T00:00:00-04:00&dateSubmitted%3C={end_date}T00:00:00-04:00&order=-is.sharpe&hidden=false&type!=SA'
    resp = s.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()

def refresh_alpha_metrics_streaming(s):
    logger = logging.getLogger('app')
    cache_df, meta = _read_alpha_cache()
    last_end = meta.get('last_end_date')
    if last_end:
        start_date = (datetime.strptime(last_end, '%Y-%m-%d') - timedelta(days=3)).strftime('%Y-%m-%d')
    else:
        start_date = _get_initial_start_date(logger)
    end_date = (datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d')
    try:
        head = _fetch_alpha_metrics_page(s, start_date, end_date, 1, 0)
        count = head.get('count', 0)
    except Exception as e:
        yield json.dumps({'status': 'error', 'message': f'预检失败: {str(e)}'}) + '\n'
        return
    if count == 0:
        yield json.dumps({'status': 'completed', 'message': '没有新的因子提交数据可更新'}) + '\n'
        meta['last_end_date'] = end_date
        _write_alpha_cache(cache_df, meta)
        return
    limit = 100
    total_pages = (count + limit - 1) // limit
    yield json.dumps({'status': 'progress', 'message': f'开始拉取因子数据 {start_date} ~ {end_date}，共{count}条', 'stage': 'alpha_fetch', 'progress': 0}) + '\n'
    rows = []
    for i, offset in enumerate(range(0, count, limit), start=1):
        try:
            data = _fetch_alpha_metrics_page(s, start_date, end_date, limit, offset)
            results = data.get('results', [])
            for alpha in results:
                alpha_is = alpha.get('is', {})
                numeric_is = {k: v for k, v in alpha_is.items() if isinstance(v, (int, float))}
                row = {
                    'alphaId': alpha.get('id'),
                    'dateSubmitted': (alpha.get('dateSubmitted') or '')[:10],
                    'type': alpha.get('type')
                }
                row.update(numeric_is)
                rows.append(row)
        except Exception as e:
            yield json.dumps({'status': 'error', 'message': f'拉取失败: {str(e)}'}) + '\n'
            return
        yield json.dumps({'status': 'progress', 'message': f'正在拉取第{i}/{total_pages}页', 'stage': 'alpha_fetch', 'progress': round(i / total_pages * 100, 2)}) + '\n'
    new_df = pd.DataFrame(rows)
    if not new_df.empty:
        if cache_df is not None and not cache_df.empty:
            all_df = pd.concat([cache_df, new_df], ignore_index=True)
        else:
            all_df = new_df
        if 'alphaId' in all_df.columns:
            all_df = all_df.drop_duplicates(subset=['alphaId'], keep='last')
        if 'dateSubmitted' in all_df.columns:
            all_df['dateSubmitted'] = pd.to_datetime(all_df['dateSubmitted'], errors='coerce')
        meta['last_end_date'] = end_date
        _write_alpha_cache(all_df, meta)
        yield json.dumps({'status': 'completed', 'message': f'已更新 {len(new_df)} 条因子指标，累计 {len(all_df)} 条'}) + '\n'
    else:
        meta['last_end_date'] = end_date
        _write_alpha_cache(cache_df, meta)
        yield json.dumps({'status': 'completed', 'message': '无新增数据'}) + '\n'

def _current_quarter_start(today):
    m = today.month
    if m < 4:
        return datetime(today.year, 1, 1)
    elif m < 7:
        return datetime(today.year, 4, 1)
    elif m < 10:
        return datetime(today.year, 7, 1)
    else:
        return datetime(today.year, 10, 1)

def get_personal_scores():
    df, _ = _read_alpha_cache()
    if df is None or df.empty:
        return None
    if 'dateSubmitted' not in df.columns or 'type' not in df.columns:
        return {'status': 'error', 'message': '缓存数据格式过时，请点击“刷新因子提交数据”以更新。'}
    df = df.copy()
    df['dateSubmitted'] = pd.to_datetime(df['dateSubmitted'], errors='coerce')
    df = df.dropna(subset=['dateSubmitted'])
    numeric_cols = [c for c in df.columns if c not in ('alphaId', 'dateSubmitted', 'type') and pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return None
    today = datetime.utcnow()
    last_30_start = today - timedelta(days=30)
    q_start = _current_quarter_start(today)
    def _avg(series):
        return float(series.mean()) if len(series) > 0 else None
    def _build_avg(sub_df):
        return {col: _avg(sub_df[col].dropna()) for col in numeric_cols}
    scores = {}
    for alpha_type in ['REGULAR', 'SUPER']:
        type_df = df[df['type'] == alpha_type]
        last_30_df = type_df[type_df['dateSubmitted'] >= last_30_start]
        quarter_df = type_df[type_df['dateSubmitted'] >= q_start]
        scores[alpha_type] = {
            'last30d': _build_avg(last_30_df),
            'thisQuarter': _build_avg(quarter_df),
            'overall': _build_avg(type_df)
        }
    return {'scores': scores, 'metrics': numeric_cols}

def get_submittable_alphas():
    df, _ = _read_alpha_cache()
    if df is None or df.empty:
        return None
    required_cols = ['alphaId', 'sharpe']
    if not all(col in df.columns for col in required_cols):
        return None
    submittable = df[df['sharpe'] >= 1.0].copy()
    if submittable.empty:
        return []
    submittable = submittable.sort_values('sharpe', ascending=False)
    cols_to_return = ['alphaId', 'sharpe', 'fitness', 'turnover', 'returns', 'longCount', 'shortCount', 'dateSubmitted']
    optional_cols = ['region', 'universe', 'delay', 'decay', 'neutralization']
    for col in optional_cols:
        if col in submittable.columns:
            cols_to_return.append(col)
    cols_to_return = [col for col in cols_to_return if col in submittable.columns]
    result = submittable[cols_to_return].to_dict('records')
    return result