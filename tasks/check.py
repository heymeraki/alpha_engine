import time
import os
import numpy as np
from config import RECORDS_PATH, REGION_LIST, UNIVERSE_DICT
from machine_lib import *
from machine_lib2 import *
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading
import warnings
warnings.filterwarnings('ignore')

brain_api_url = os.environ.get('BRAIN_API_URL', 'https://api.worldquantbrain.com')
import requests
from typing import Tuple, List, Dict

lock = threading.Lock()

def wait_get(session, url, max_retries=3):
    retries = 0
    while retries < max_retries:
        response = session.get(url)
        retry_after = float(response.headers.get('Retry-After', 0))
        if retry_after > 0:
            time.sleep(retry_after)
            continue
        if response.status_code < 400:
            return response
        time.sleep(2 ** retries)
        retries += 1
    response.raise_for_status()
    return response

def get_alpha_region(session, alpha_id):
    url = f'https://api.worldquantbrain.com/alphas/{alpha_id}'
    alpha_info = wait_get(session, url).json()
    return alpha_info['settings']['region']

def get_region_alphas(session, region):
    offset = 0
    limit = 100
    alpha_ids = []
    while True:
        url = f'https://api.worldquantbrain.com/users/self/alphas?stage=OS&limit={limit}&offset={offset}&settings.region={region}&order=-dateSubmitted'
        res = wait_get(session, url).json()
        for alpha in res['results']:
            if alpha['settings']['region'] == region:
                alpha_ids.append(alpha['id'])
        if len(res['results']) < limit:
            break
        offset += limit
    return alpha_ids

def get_alpha_pnl(session, alpha_id, inner_logger):
    os.makedirs('alphas', exist_ok=True)
    csv_path = f'alphas/{alpha_id}.csv'
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
    else:
        url = f'https://api.worldquantbrain.com/alphas/{alpha_id}/recordsets/pnl'
        pnl_data = wait_get(session, url).json()
        columns = [p['name'] for p in pnl_data['schema']['properties'].values()]
        df = pd.DataFrame(pnl_data['records'], columns=columns).rename(columns={'date': 'Date', pnl_data['schema']['properties']['pnl']['name']: alpha_id})
        inner_logger.print(f'正在保存已提交的 alpha {alpha_id} 的 PnL 数据...')
        df[['Date', alpha_id]].to_csv(csv_path, index=False)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')
    return df

def calculate_correlation(target_rets, peer_rets, inner_logger):
    start_date = target_rets.index.max() - pd.DateOffset(years=4)
    target_rets = target_rets[target_rets.index > start_date]
    peer_rets = peer_rets[peer_rets.index > start_date]
    combined_rets = pd.concat([target_rets, peer_rets], axis=1, join='inner')
    if combined_rets.empty:
        return 0
    target_col = combined_rets.columns[0]
    corr_series = combined_rets.drop(target_col, axis=1).corrwith(combined_rets[target_col])
    max_corr = corr_series.max() if not corr_series.empty else 0
    if pd.isna(max_corr):
        inner_logger.print('好像遇到了厂字alpha, self corr改为0.9999')
        return 0.9999
    return max_corr

def get_self_corr_xin_plus(session, alpha_id, inner_logger):
    inner_logger.print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} 正在计算 alpha {alpha_id} 的本地自相关...')
    region = get_alpha_region(session, alpha_id)
    inner_logger.print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} 获取到 {alpha_id} 的region为 {region}')
    inner_logger.print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} 开始获取 {region} 区域的所有 alpha...(可能比较久)')
    peer_ids = [aid for aid in get_region_alphas(session, region) if aid != alpha_id]
    inner_logger.print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  {region} 已提交了 {len(peer_ids)} 个因子')
    if not peer_ids:
        return 0
    target_pnl = get_alpha_pnl(session, alpha_id, inner_logger=inner_logger)
    inner_logger.print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} 成功获取 {alpha_id} 的Pnl数据')
    peer_pnls = []
    for aid in peer_ids:
        try:
            peer_pnls.append(get_alpha_pnl(session, aid, inner_logger=inner_logger))
        except Exception:
            pass
    target_rets = target_pnl[alpha_id].ffill().pct_change().dropna()
    peer_rets_df = pd.concat(peer_pnls, axis=1).ffill()
    peer_rets_df = peer_rets_df.apply(lambda x: x.ffill().shift(1), axis=0)
    return calculate_correlation(target_rets, peer_rets_df, inner_logger)

def generate_date_periods(start_date_file, default_start_date, inner_logger):
    if default_start_date is not None:
        start_date_str = default_start_date
    else:
        try:
            with open(start_date_file, 'r') as f:
                start_date_str = f.read().strip()
        except FileNotFoundError:
            inner_logger.print("File start_date.txt not found. Use default start date: '2024-10-07'.")
            start_date_str = default_start_date
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    today = (datetime.now().date() + timedelta(days=1))
    periods = []
    current_date = start_date
    while current_date < today:
        next_date = current_date + timedelta(days=1)
        periods.append([current_date.strftime('%Y-%m-%d'), next_date.strftime('%Y-%m-%d')])
        current_date = next_date
    return periods

def get_self_corr(s, alpha_id):
    result = s.get(f'{brain_api_url}/alphas/{alpha_id}/correlations/self')
    if 'retry-after' in result.headers:
        time.sleep(float(result.headers['Retry-After']))
    if result.json().get('records', 0) == 0:
        return pd.DataFrame()
    records_len = len(result.json()['records'])
    if records_len == 0:
        return pd.DataFrame()
    columns = [dct['name'] for dct in result.json()['schema']['properties'].values()]
    self_corr_df = pd.DataFrame(result.json()['records'], columns=columns).assign(alpha_id=alpha_id)
    return self_corr_df

def get_prod_corr(s, alpha_id):
    result = s.get(f'{brain_api_url}/alphas/{alpha_id}/correlations/prod')
    if 'retry-after' in result.headers:
        time.sleep(float(result.headers['Retry-After']))
    if result.json().get('records', 0) == 0:
        return pd.DataFrame()
    columns = [dct['name'] for dct in result.json()['schema']['properties'].values()]
    prod_corr_df = pd.DataFrame(result.json()['records'], columns=columns).assign(alpha_id=alpha_id)
    return prod_corr_df

def check_self_corr_test(s, alpha_id, threshold=0.7):
    self_corr_df = get_self_corr(s, alpha_id)
    if self_corr_df.empty:
        result = [{'test': 'SELF_CORRELATION', 'result': 'PASS', 'limit': threshold, 'value': 0, 'alpha_id': alpha_id}]
    else:
        value = self_corr_df['correlation'].max()
        result = [{'test': 'SELF_CORRELATION', 'result': 'PASS' if value < threshold else 'FAIL', 'limit': threshold, 'value': value, 'alpha_id': alpha_id}]
    return pd.DataFrame(result)

def check_prod_corr_test(s, alpha_id, threshold=0.7):
    prod_corr_df = get_prod_corr(s, alpha_id)
    value = prod_corr_df[prod_corr_df['alphas'] > 0]['max'].max() if len(prod_corr_df) > 0 else 0
    result = [{'test': 'PROD_CORRELATION', 'result': 'PASS' if value <= threshold else 'FAIL', 'limit': threshold, 'value': value, 'alpha_id': alpha_id}]
    return pd.DataFrame(result)

def check_alpha_by_self_prod(s, alpha, submitable_alpha_file, mode, self_corr_mode, inner_logger):
    alpha_id = alpha['id']
    inner_logger.print(f'正在检查 alpha {alpha_id} ...')
    if mode == 'PPAC':
        sc_target = 0.5
    else:
        sc_target = 0.7
    try:
        now = time.time()
        if self_corr_mode == '本地自相关':
            self_corr = get_self_corr_xin_plus(s, alpha_id, inner_logger=inner_logger)
            self_res = pd.DataFrame([{'test': 'SELF_CORRELATION', 'result': 'PASS' if self_corr < sc_target else 'FAIL', 'limit': sc_target, 'value': self_corr, 'alpha_id': alpha_id}])
            inner_logger.print(f'{alpha_id} xin plus self corr use:{time.time() - now}')
            inner_logger.print(f'{alpha_id} self corr:{self_corr}')
            if self_res['result'].iloc[0] == 'FAIL':
                inner_logger.print(f'{alpha_id} self corr test failed.')
                set_alpha_properties(s, alpha_id, color='RED')
                return
        elif self_corr_mode == '官方自相关':
            self_res = check_self_corr_test(s, alpha_id, sc_target)
            inner_logger.print(f'{alpha_id} self corr use:{time.time() - now}')
            inner_logger.print(self_res)
            if self_res['result'].iloc[0] == 'FAIL':
                inner_logger.print(f'{alpha_id} self corr test failed.')
                set_alpha_properties(s, alpha_id, color='RED')
                return
        
        if mode != 'PPAC':
            now = time.time()
            prod_res = check_prod_corr_test(s, alpha_id, 0.7)
            inner_logger.print(prod_res)
            inner_logger.print(f'{alpha_id} prod corr use:{time.time() - now}')
            if prod_res['result'].iloc[0] == 'FAIL':
                inner_logger.print(f'{alpha_id} prod corr test failed.')
                set_alpha_properties(s, alpha_id, color='RED')
                return
        else:
            self_corr = self_res['value'].iloc[0]
        if mode != 'PPAC':
            prod_corr = prod_res['value'].iloc[0]
            alpha['prod_corr'] = prod_corr
        alpha_df = pd.DataFrame([alpha])
        inner_logger.print(alpha_df)
        with lock:
            if os.path.exists(submitable_alpha_file):
                try:
                    submit_df_old = pd.read_csv(submitable_alpha_file, dtype=str, keep_default_na=False)
                except (pd.errors.ParserError, ValueError) as e:
                    backup_file = f'{submitable_alpha_file}.bak'
                    if os.path.exists(backup_file):
                        os.remove(backup_file)
                    os.rename(submitable_alpha_file, backup_file)
                    submit_df_old = pd.DataFrame()
            else:
                submit_df_old = pd.DataFrame()
            alpha_df_str = alpha_df.astype(str)
            submit_df = pd.concat([submit_df_old, alpha_df_str], axis=0, join='outer', ignore_index=True)
            if 'id' in submit_df.columns:
                submit_df.drop_duplicates(subset=['id'], keep='last', inplace=True)
            else:
                inner_logger.print("Warning: 'id' column not found in submit_df, skipping deduplication")
            submit_df.to_csv(submitable_alpha_file, index=False)
        set_alpha_properties(s, alpha_id, color='GREEN')
        inner_logger.print(f'Successfully find {alpha_id} is a submitable alpha.')
    except Exception as e:
        inner_logger.print(f'some error happened when checking: {e} \nAlpha: {alpha_id}')

def run_task(mode, n_jobs, date, self_corr_mode, inner_logger):
    n_jobs = int(n_jobs)
    start_date_file = os.path.join(RECORDS_PATH, 'start_date.txt')
    submitable_alpha_file = os.path.join(RECORDS_PATH, 'submitable_alpha.csv')
    periods = generate_date_periods(start_date_file, date, inner_logger)
    for start_date, end_date in periods:
        inner_logger.print(start_date, end_date)
        for region in REGION_LIST:
            if mode == 'USER':
                sh_th = 1.25
                fit_th = 1
            elif mode == 'CONSULTANT':
                sh_th = 1.58
                fit_th = 1
            elif mode == 'PPAC':
                sh_th = 1
                fit_th = 0.5
            need_to_check_alpha = get_alphas(start_date, end_date, sh_th, fit_th, 10, 10, region, '', '', '', 9999, 'submit', '', 'RED', s, inner_logger)
            if len(need_to_check_alpha['check']) == 0:
                inner_logger.print(f'region: {region} universe: all No alpha to check.')
                continue
            inner_logger.print(f'看来有{len(need_to_check_alpha["check"])}个因子等着被check')
            split_sizes = np.array_split(need_to_check_alpha['check'], max(1, len(need_to_check_alpha['check']) // 10))
            chunks = [list(chunk) for chunk in split_sizes]
            for chunk in chunks:
                with ThreadPoolExecutor(max_workers=n_jobs) as executor:
                    for alpha in chunk:
                        executor.submit(check_alpha_by_self_prod, s, alpha, submitable_alpha_file, mode, self_corr_mode, inner_logger)
            if datetime.now().date() - timedelta(days=3) < datetime.strptime(end_date, '%Y-%m-%d').date():
                with open(start_date_file, 'w') as f:
                    f.write(end_date)
        if datetime.now().date() - timedelta(days=5) < datetime.strptime(end_date, '%Y-%m-%d').date():
            with open(start_date_file, 'w') as f:
                f.write(end_date)

run_task = while_true_try_decorator(run_task)