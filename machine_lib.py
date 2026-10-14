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

class AutoRefreshSession(requests.Session):
    def __init__(self, logger=None, time_exp=1800, auth_file='user_info.txt'):
        super().__init__()
        self.logger = logger
        self.time_exp = time_exp
        self.auth_file = auth_file
        self.username = None
        self.password = None
        self._last_check_time = 0
        self._check_interval = 300
        self.first_login = True
        self._load_credentials()

    def _load_credentials(self):
        try:
            with open(self.auth_file, 'r', encoding='utf-8') as f:
                data = f.read().strip().split('\n')
            credentials = {line.split(': ')[0]: line.split(': ')[1] for line in data}
            self.username = credentials['username'][1:-1]
            self.password = credentials['password'][1:-1]
            self.auth = (self.username, self.password)
        except Exception as e:
            error_msg = f'加载认证信息失败: {str(e)}'
            if self.logger:
                self.logger.print(error_msg)
            else:
                print(error_msg)
            raise

    def _print_log(self, message):
        if self.logger:
            self.logger.print(message)
        else:
            print(message)

    def login(self):
        try:
            response = self.post('https://api.worldquantbrain.com/authentication')
            if 'API rate limit exceeded' in str(response.content):
                self._print_log('API速率限制 exceeded，登录失败')
                return False
            if response.status_code in (200, 201):
                self._print_log('登录成功')
                self._print_log(str(response.content))
                self.first_login = False
                return True
            else:
                self._print_log(f'登录失败，状态码: {response.status_code}')
                return False
        except Exception as e:
            self._print_log(f'登录过程中发生错误: {str(e)}')
            return False

    def check_session_status(self):
        try:
            current_time = time.time()
            if current_time - self._last_check_time < self._check_interval:
                return True
            self._last_check_time = current_time
            response = self.get('https://api.worldquantbrain.com/authentication')
            try:
                res_data = response.json()
            except Exception:
                self._print_log(f'{response.content}，无法解析JSON响应，需要重新登录')
                return False
            if 'token' in res_data and 'expiry' in res_data['token']:
                remaining_time = res_data['token']['expiry']
                if remaining_time < self.time_exp:
                    self._print_log(f'会话将在{remaining_time:.1f}秒后过期，需要刷新')
                    return False
                else:
                    self._print_log(f'会话状态正常，剩余有效时间: {remaining_time:.1f}秒')
                    return True
            else:
                self._print_log('无法获取会话过期信息，需要重新登录')
                return False
        except Exception as e:
            self._print_log(f'检查会话状态时发生错误: {str(e)}，需要重新登录')
            return False

    def refresh_if_needed(self):
        if self.first_login:
            return True
        if not self.check_session_status():
            return self.login()
        return True

    def request(self, method, url, **kwargs):
        if not self.refresh_if_needed():
            self._print_log('会话刷新失败，请求可能无法正常执行')
        return super().request(method, url, **kwargs)

    def restart(self):
        self.cookies.clear()
        self.headers.clear()
        self._print_log('会话已重启，cookies和headers已清除')
        return self.login()

pd.set_option('expand_frame_repr', False)
pd.set_option('display.max_rows', 1000)

brain_api_url = os.environ.get('BRAIN_API_URL', 'https://api.worldquantbrain.com')

basic_ops = ['log', 'sqrt', 'reverse', 'inverse', 'rank', 'zscore', 'log_diff', 's_log_1p', 'fraction', 'quantile', 'normalize', 'scale_down']

ts_ops = ['ts_rank', 'ts_zscore', 'ts_delta', 'ts_sum', 'ts_product', 'ts_ir', 'ts_std_dev', 'ts_mean', 'ts_arg_min', 'ts_arg_max', 'ts_min_diff', 'ts_max_diff', 'ts_returns', 'ts_scale', 'ts_skewness', 'ts_kurtosis', 'ts_quantile']

ts_not_use = ['ts_min', 'ts_max', 'ts_delay', 'ts_median']

arsenal = ['ts_moment', 'ts_entropy', 'ts_min_max_cps', 'ts_min_max_diff', 'inst_tvr', 'sigmoid', 'ts_decay_exp_window', 'ts_percentage', 'vector_neut', 'vector_proj', 'signed_power']

twin_field_ops = ['ts_corr', 'ts_covariance', 'ts_co_kurtosis', 'ts_co_skewness', 'ts_theilsen']

group_ops = ['group_neutralize', 'group_rank', 'group_normalize', 'group_scale', 'group_zscore']

group_ac_ops = ['group_sum', 'group_max', 'group_mean', 'group_median', 'group_min', 'group_std_dev']

vec_ops = ['vec_avg', 'vec_sum', 'vec_ir', 'vec_max', 'vec_count', 'vec_skewness', 'vec_stddev', 'vec_choose']

ops_set = basic_ops + ts_ops + arsenal + group_ops

s = None
print('正在尝试登录WQ平台...')
s = AutoRefreshSession()
result_login = s.login()
if result_login:
    print('登陆成功！')
else:
    raise Exception('登陆失败！重试中...(同时请检查网络环境和user_info.txt是否填写正确)')

res = s.get('https://api.worldquantbrain.com/operators')
aval = pd.DataFrame(res.json())['name'].tolist()
ts_ops = [op for op in ts_ops if op in aval]
basic_ops = [op for op in basic_ops if op in aval]
group_ops = [op for op in group_ops if op in aval]
twin_field_ops = [op for op in twin_field_ops if op in aval]
arsenal = [op for op in arsenal if op in aval]
vec_ops = [op for op in vec_ops if op in aval]
s.close()

def set_alpha_properties(s, alpha_id, name=None, color=None, selection_desc=None, combo_desc=None, tags=None):
    params = {'category': None, 'regular': {'description': None}}
    if color:
        params['color'] = color
    if name:
        params['name'] = name
    if tags:
        params['tags'] = tags
    if combo_desc:
        params['combo'] = {'description': combo_desc}
    if selection_desc:
        params['selection'] = {'description': selection_desc}
    response = s.patch(f'https://api.worldquantbrain.com/alphas/{alpha_id}', json=params)

def get_vec_fields(fields):
    vec_fields = []
    for field in fields:
        for vec_op in vec_ops:
            if vec_op == 'vec_choose':
                vec_fields.append(f'{vec_op}({field}, nth=-1)')
                vec_fields.append(f'{vec_op}({field}, nth=0)')
            else:
                vec_fields.append(f'{vec_op}({field})')
    return vec_fields

def get_datafields(s, instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000', dataset_id='', search=''):
    if len(search) == 0:
        url_template = f'https://api.worldquantbrain.com/data-fields?&instrumentType={instrument_type}&region={region}&delay={str(delay)}&universe={universe}&dataset.id={dataset_id}&limit=50&offset={{x}}'
        count = s.get(url_template.format(x=0)).json()['count']
    else:
        url_template = f'https://api.worldquantbrain.com/data-fields?&instrumentType={instrument_type}&region={region}&delay={str(delay)}&universe={universe}&limit=50&search={search}&offset={{x}}'
        count = 100
    datafields_list = []
    for x in range(0, count, 50):
        attemps = 0
        while attemps <= 5:
            try:
                datafields = s.get(url_template.format(x=x))
                datafields_list.append(datafields.json()['results'])
                time.sleep(1)
                break
            except Exception as e:
                attemps += 1
        else:
            print(f'Failed to get data fields at offset {x} after 5 attempts.')
    datafields_list_flat = [item for sublist in datafields_list for item in sublist]
    datafields_df = pd.DataFrame(datafields_list_flat)
    return datafields_df

def process_datafields(df, data_type):
    if data_type == 'matrix':
        datafields = df[df['type'] == 'MATRIX']['id'].tolist()
    elif data_type == 'vector':
        datafields = get_vec_fields(df[df['type'] == 'VECTOR']['id'].tolist())
    tb_fields = []
    for field in datafields:
        tb_fields.append(f'winsorize(ts_backfill({field}, 120), std=4)')
    return tb_fields

def get_alphas(start_date, end_date, sharpe_th, fitness_th, longCount_th, shortCount_th, region, universe, delay, instrumentType, alpha_num, usage, tag, color_exclude, s=None, inner_logger=None):
    if s is None:
        s = AutoRefreshSession(inner_logger)
        s.login()
    alpha_list = []
    next_alphas = []
    decay_alphas = []
    check_alphas = []
    i = 0
    url_e_template = f'https://api.worldquantbrain.com/users/self/alphas?limit=100&offset={{offset}}&tag%3D{tag}&is.longCount%3E={longCount_th}&is.shortCount%3E={shortCount_th}&settings.region={region}&is.sharpe%3E={sharpe_th}&is.fitness%3E={fitness_th}&settings.universe={universe}&status=UNSUBMITTED&dateCreated%3E={start_date}T00:00:00-04:00&dateCreated%3C{end_date}T00:00:00-04:00&type=REGULAR&color!={color_exclude}&settings.delay={delay}&settings.instrumentType={instrumentType}&order=-is.sharpe&hidden=false&type!=SUPER'
    try:
        while True:
            response = s.get(url_e_template.format(offset=i))
            resp_json = response.json()
            count = int(resp_json['count'])
            inner_logger.print(f'一共有{count}个因子等待被获取，已经获取了{i}个')
            alpha_list.extend(resp_json['results'])
            i += 100
            if i >= count or i == 9900:
                inner_logger.print(f'获取到的因子数量为{len(alpha_list)}, 现在开始进行剪枝去除一部分垃圾因子...')
                break
            time.sleep(10)
    except Exception as e:
        inner_logger.print(f'Failed to get alphas: {e}')
        i = max(0, i - 100)
        time.sleep(60)
        s = AutoRefreshSession(inner_logger)
        s.login()
        inner_logger.print(f'{i} finished re-login')
    if usage != 'submit':
        i = 0
        url_c_template = f'https://api.worldquantbrain.com/users/self/alphas?limit=100&offset={{offset}}&tag%3D{tag}&is.longCount%3E={longCount_th}&is.shortCount%3E={shortCount_th}&settings.region={region}&is.sharpe%3C=-{sharpe_th}&is.fitness%3C=-{fitness_th}&settings.universe={universe}&status=UNSUBMITTED&dateCreated%3E={start_date}T00:00:00-04:00&dateCreated%3C{end_date}T00:00:00-04:00&type=REGULAR&color!={color_exclude}&settings.delay={delay}&settings.instrumentType={instrumentType}&order=-is.sharpe&hidden=false&type!=SUPER'
        while True:
            try:
                response = s.get(url_c_template.format(offset=i))
                resp_json = response.json()
                count = resp_json['count']
                if i >= count or i == 9900:
                    break
                alpha_list.extend(resp_json['results'])
                i += 100
            except Exception as e:
                inner_logger.print(f'Failed to get alphas: {e}')
                time.sleep(10)
                s = AutoRefreshSession(inner_logger)
                s.login()
                inner_logger.print(f'{i} finished re-login')
    if len(alpha_list) == 0:
        if usage != 'submit':
            return {'next': [], 'decay': []}
        else:
            return {'check': []}
    if usage != 'submit':
        for j in range(len(alpha_list)):
            alpha_id = alpha_list[j]['id']
            name = alpha_list[j]['name']
            dateCreated = alpha_list[j]['dateCreated']
            sharpe = alpha_list[j]['is']['sharpe']
            fitness = alpha_list[j]['is']['fitness']
            turnover = alpha_list[j]['is']['turnover']
            margin = alpha_list[j]['is']['margin']
            longCount = alpha_list[j]['is']['longCount']
            shortCount = alpha_list[j]['is']['shortCount']
            decay = alpha_list[j]['settings']['decay']
            exp = alpha_list[j]['regular']['code']
            region = alpha_list[j]['settings']['region']
            concentrated_weight = next((check.get('value', 0) for check in alpha_list[j]['is']['checks'] if check['name'] == 'CONCENTRATED_WEIGHT'), 0)
            sub_universe_sharpe = next((check.get('value', 99) for check in alpha_list[j]['is']['checks'] if check['name'] == 'LOW_SUB_UNIVERSE_SHARPE'), 99)
            two_year_sharpe = next((check.get('value', 99) for check in alpha_list[j]['is']['checks'] if check['name'] == 'LOW_2Y_SHARPE'), 99)
            ladder_sharpe = next((check.get('value', 99) for check in alpha_list[j]['is']['checks'] if check['name'] == 'IS_LADDER_SHARPE'), 99)
            conditions = (longCount > 100 or shortCount > 100) and concentrated_weight < 0.2 and abs(sub_universe_sharpe) > sharpe_th / 1.66 and abs(two_year_sharpe) > sharpe_th and abs(ladder_sharpe) > sharpe_th
            if region == 'CHN':
                conditions = conditions and sharpe < 0
            if conditions:
                if sharpe < 0:
                    exp = f'-%s' % exp
                rec = [alpha_id, exp, sharpe, turnover, fitness, margin, longCount, shortCount, dateCreated, decay]
                if turnover > 0.7:
                    rec.append(decay * 4)
                    decay_alphas.append(rec)
                elif turnover > 0.6:
                    rec.append(decay * 3 + 3)
                    decay_alphas.append(rec)
                elif turnover > 0.5:
                    rec.append(decay * 3)
                    decay_alphas.append(rec)
                elif turnover > 0.4:
                    rec.append(decay * 2)
                    decay_alphas.append(rec)
                elif turnover > 0.35:
                    rec.append(decay + 4)
                    decay_alphas.append(rec)
                elif turnover > 0.3:
                    rec.append(decay + 2)
                    decay_alphas.append(rec)
                else:
                    next_alphas.append(rec)
            else:
                set_alpha_properties(s, alpha_id, color='RED')
        inner_logger.print(f'获取到了{len(next_alphas) + len(decay_alphas)}个因子')
        output_dict = {'next': next_alphas, 'decay': decay_alphas}
    else:
        for alpha_detail in alpha_list:
            id = alpha_detail['id']
            type = alpha_detail['type']
            author = alpha_detail['author']
            instrumentType = alpha_detail['settings']['instrumentType']
            region = alpha_detail['settings']['region']
            universe = alpha_detail['settings']['universe']
            delay = alpha_detail['settings']['delay']
            decay = alpha_detail['settings']['decay']
            neutralization = alpha_detail['settings']['neutralization']
            truncation = alpha_detail['settings']['truncation']
            pasteurization = alpha_detail['settings']['pasteurization']
            unitHandling = alpha_detail['settings']['unitHandling']
            nanHandling = alpha_detail['settings']['nanHandling']
            language = alpha_detail['settings']['language']
            visualization = alpha_detail['settings']['visualization']
            code = alpha_detail['regular']['code']
            description = alpha_detail['regular']['description']
            operatorCount = alpha_detail['regular']['operatorCount']
            dateCreated = alpha_detail['dateCreated']
            dateSubmitted = alpha_detail['dateSubmitted']
            dateModified = alpha_detail['dateModified']
            name = alpha_detail['name']
            favorite = alpha_detail['favorite']
            hidden = alpha_detail['hidden']
            color = alpha_detail['color']
            category = alpha_detail['category']
            tags = alpha_detail['tags']
            classifications = alpha_detail['classifications']
            grade = alpha_detail['grade']
            stage = alpha_detail['stage']
            status = alpha_detail['status']
            pnl = alpha_detail['is']['pnl']
            bookSize = alpha_detail['is']['bookSize']
            longCount = alpha_detail['is']['longCount']
            shortCount = alpha_detail['is']['shortCount']
            turnover = alpha_detail['is']['turnover']
            returns = alpha_detail['is']['returns']
            drawdown = alpha_detail['is']['drawdown']
            margin = alpha_detail['is']['margin']
            fitness = alpha_detail['is']['fitness']
            sharpe = alpha_detail['is']['sharpe']
            startDate = alpha_detail['is']['startDate']
            checks = alpha_detail['is']['checks']
            os = alpha_detail['os']
            train = alpha_detail['train']
            test = alpha_detail['test']
            prod = alpha_detail['prod']
            competitions = alpha_detail['competitions']
            themes = alpha_detail['themes']
            team = alpha_detail['team']
            checks_df = pd.DataFrame(checks)
            pyramids = next(([y['name'] for y in item['pyramids']] for item in checks if item['name'] == 'MATCHES_PYRAMID'), None)
            concentrated_weight = next((check.get('value', 0) for check in checks if check['name'] == 'CONCENTRATED_WEIGHT'), 0)
            sub_universe_sharpe = next((check.get('value', 99) for check in checks if check['name'] == 'LOW_SUB_UNIVERSE_SHARPE'), 99)
            two_year_sharpe = next((check.get('value', 99) for check in checks if check['name'] == 'LOW_2Y_SHARPE'), 99)
            ladder_sharpe = next((check.get('value', 99) for check in checks if check['name'] == 'IS_LADDER_SHARPE'), 99)
            if any(checks_df['result'] == 'FAIL') or two_year_sharpe == 0:
                set_alpha_properties(s, id, color='RED')
                continue
            rec = {
                'id': id, 'type': type, 'author': author, 'instrumentType': instrumentType, 'region': region, 'universe': universe, 'delay': delay, 'decay': decay,
                'neutralization': neutralization, 'truncation': truncation, 'pasteurization': pasteurization, 'unitHandling': unitHandling, 'nanHandling': nanHandling,
                'language': language, 'visualization': visualization, 'code': code, 'description': description, 'operatorCount': operatorCount, 'dateCreated': dateCreated,
                'dateSubmitted': dateSubmitted, 'dateModified': dateModified, 'name': name, 'favorite': favorite, 'hidden': hidden, 'color': color, 'category': category,
                'tags': tags, 'classifications': classifications, 'grade': grade, 'stage': stage, 'status': status, 'pnl': pnl, 'bookSize': bookSize,
                'longCount': longCount, 'shortCount': shortCount, 'turnover': turnover, 'returns': returns, 'drawdown': drawdown, 'margin': margin, 'fitness': fitness,
                'sharpe': sharpe, 'startDate': startDate, 'checks': checks, 'os': os, 'train': train, 'test': test, 'prod': prod, 'competitions': competitions,
                'themes': themes, 'team': team, 'pyramids': pyramids
            }
            check_alphas.append(rec)
        output_dict = {'check': check_alphas}
    if usage == 'submit' and count >= 9900 and len(output_dict['check']) < len(alpha_list):
        output_dict = get_alphas(start_date, end_date, sharpe_th, fitness_th, longCount_th, shortCount_th, region, universe, delay, instrumentType, alpha_num, usage, tag, color_exclude, s, inner_logger)
    return output_dict

def ts_comp_factory(op, field, factor, paras):
    output = []
    l1, l2 = (5, 22, 66, 120, 240), paras
    comb = list(product(l1, l2))
    for day, para in comb:
        if type(para) == float:
            alpha = f'{op}({field}, {day}, {factor}={para:.1f})'
        elif type(para) == int:
            alpha = f'{op}({field}, {day}, {factor}={para})'
        output.append(alpha)
    return output

def first_order_factory(fields, ops_set):
    alpha_set = []
    for field in fields:
        alpha_set.append(field)
        for op in ops_set:
            if op == 'ts_percentage':
                alpha_set += ts_comp_factory(op, field, 'percentage', [0.2, 0.5, 0.8])
            elif op == 'ts_decay_exp_window':
                alpha_set += ts_comp_factory(op, field, 'factor', [0.5])
            elif op == 'ts_moment':
                alpha_set += ts_comp_factory(op, field, 'k', [2, 3, 4])
            elif op == 'ts_entropy':
                alpha_set += ts_comp_factory(op, field, 'buckets', [10])
            elif op.startswith('ts_') or op == 'inst_tvr':
                alpha_set += ts_factory(op, field)
            elif op.startswith('group_'):
                alpha_set += group_factory(op, field, [])
            elif op == 'signed_power':
                alpha = f'{op}({field}, 2)'
                alpha_set.append(alpha)
            else:
                alpha = f'{op}({field})'
                alpha_set.append(alpha)
    return alpha_set

def get_group_second_order_factory(first_order, group_ops, group_fields):
    second_order = []
    for fo in first_order:
        for group_op in group_ops:
            second_order += group_factory(group_op, fo, group_fields)
    return second_order

def trade_when_factory(op, field, region, delay):
    output = []
    open_events = [
        'ts_arg_max(volume, 5) == 0', 'ts_corr(close, volume, 252) <= 0', 'ts_corr(close, volume, 20) < 0',
        'ts_corr(close, volume, 5) < 0', 'ts_mean(volume, 10) > ts_mean(volume, 60)', 'ts_mean(volume, 10) <= ts_mean(volume, 60)',
        'group_rank(ts_std_dev(returns, 60), sector) > 0.7', 'ts_zscore(returns, 60) > 2', 'ts_arg_min(volume, 5) > 3',
        'ts_arg_min(volume, 10) >= 5', 'ts_std_dev(returns, 5) > ts_std_dev(returns, 20)', 'ts_arg_max(close, 5) == 0',
        'ts_arg_max(close, 20) == 0', 'ts_corr(close, volume, 5) > 0', 'ts_corr(close, volume, 5) > 0.3',
        'ts_corr(close, volume, 5) > 0.5', 'ts_corr(close, volume, 5) > 0.7', 'ts_corr(close, volume, 5) > 0.9',
        'ts_corr(close, volume, 5) < 0', 'ts_corr(close, volume, 5) < 0.3', 'ts_corr(close, volume, 5) < 0.5',
        'ts_corr(close, volume, 5) < 0.7', 'ts_corr(close, volume, 5) < 0.9', 'ts_corr(close, volume, 20) > 0',
        'ts_corr(close, volume, 20) > 0.3', 'ts_corr(close, volume, 20) > 0.5', 'ts_corr(close, volume, 20) < 0',
        'ts_corr(close, volume, 20) < 0.3', 'ts_corr(close, volume, 20) < 0.5', f'ts_regression(returns, {field}, 5, lag = 0, rettype = 2) > 0',
        f'ts_regression(returns, {field}, 20, lag = 0, rettype = 2) > 0', 'ts_regression(returns, ts_step(20), 20, lag = 0, rettype = 2) > 0',
        'ts_regression(returns, ts_step(5), 5, lag = 0, rettype = 2) > 0'
    ]
    if delay == 1:
        exit_events = ['abs(returns) > 0.1', '-1', 'days_from_last_change(ern3_pre_reptime) > 20']
    else:
        exit_events = ['abs(returns) > 0.1', '-1']
    for oe in open_events:
        for ee in exit_events:
            alpha = f'{op}({oe}, {field}, {ee})'
            output.append(alpha)
    return output

def ts_factory(op, field):
    output = []
    days = (3, 5, 11, 22, 66, 122, 252, 504)
    for day in days:
        alpha = f'{op}({field}, {day})'
        output.append(alpha)
    return output

def group_factory(op, field, group_fields):
    output = []
    vectors = ['cap']
    cap_group = "bucket(rank(cap), range='0.1, 1, 0.1')"
    sector_cap_group = "bucket(group_rank(cap,sector),range='0,1,0.1')"
    vol_group = "bucket(rank(ts_std_dev(returns,240)),range = '0.1,1,0.1')"
    volatility_group = "bucket(rank(ts_std_dev(returns,20)),range = '0.1, 1, 0.1')"
    liquidity_group = "bucket(rank(close*volume),range = '0.1, 1, 0.1')"
    turnover_group = "bucket(rank(close*volume/cap),range='0.1, 1, 0.1')"
    dividend_yield_group = "bucket(rank(dividend/close), range='0.1, 1, 0.1')"
    adv20_group = "bucket(rank(adv20), range='0.1, 1, 0.1')"
    sector_asset_group = "bucket(group_rank(assets, sector),range='0.1, 1, 0.1')"
    bps_group = "bucket(rank(fnd28_value_05480/close), range='0.2, 1, 0.2')"
    pb_group = "bucket(rank(fnd28_value_05480/bookvalue_ps), range='0.1, 1, 0.1')"
    debt_to_equity_group = "bucket(rank(liabilities/assets), range='0.1, 1, 0.1')"
    fnd23_net_income_group = "bucket(rank(fnd23_net_income/assets), range='0.1, 1, 0.1')"
    fnd23_net_debt_group = "bucket(rank(fnd23_net_debt/assets), range='0.1, 1, 0.1')"
    anl14_buy_group = "bucket(rank(anl14_buy), range='0.1, 1, 0.1')"
    anl15_bps_gr_12_m_1m_chg_group = "bucket(rank(anl15_bps_gr_12_m_1m_chg), range='0.1, 1, 0.1')"
    anl15_salgics_gr_18_m_pe_group = "bucket(rank(anl15_salgics_gr_18_m_pe), range='0.1, 1, 0.1')"
    anl4_adjusted_netincome_ft_group = "bucket(rank(anl4_adjusted_netincome_ft), range='0.1, 1, 0.1')"
    call_breakeven_10_group = "bucket(rank(call_breakeven_10), range='0.1, 1, 0.1')"
    correlation_last_60_days_spy_group = "bucket(rank(correlation_last_60_days_spy), range='0.1, 1, 0.1')"
    est_12m_eps_num_28d_group = "bucket(rank(est_12m_eps_num_28d), range='0.1, 1, 0.1')"
    base_group = ['market', 'sector', 'industry', 'subindustry', 'country']
    experts_group = [bps_group, cap_group, sector_cap_group, turnover_group, volatility_group, liquidity_group, sector_asset_group, pb_group, debt_to_equity_group, dividend_yield_group, adv20_group]
    if 'ts_returns' in aval:
        experts_group.append(vol_group)
    if group_fields == []:
        group_fields += base_group
    for group in group_fields:
        if op.startswith('group_vector'):
            for vector in vectors:
                alpha = f'{op}({field},{vector},densify({group}))'
                output.append(alpha)
        elif op.startswith('group_percentage'):
            alpha = f'{op}({field},densify({group}),percentage=0.5)'
            output.append(alpha)
        else:
            alpha = f'{op}({field},densify({group}))'
            output.append(alpha)
    return output

def template_factory(field, region):
    output = []
    output.append(f'divide(rank({field}), rank(returns))')
    output.append(f'signed_power({field}, 0.5)')
    output.append(f'signed_power({field}, 2)')
    output.append(f'hump(zscore({field}), hump=0.01)')
    output.append(f'last_diff_value({field}, 22)')
    output.append(f'ts_regression({field}, returns, 252, lag=0, rettype=0)')
    output.append(f"\n    my_group = market;\n    my_group2 = bucket(rank(cap),range='0,1,0.1');\n    alpha=rank(group_rank(ts_decay_linear(volume/ts_sum(volume,252),10),my_group)*group_rank(ts_rank({field}, 22),my_group)*group_rank(-ts_delta(close,5),my_group));\n    trade_when(volume>adv20,group_neutralize(alpha,my_group2),-1)\n    ")
    output.append(f'\n    ts_mean({field}, 252) / ts_std_dev({field}, 252)\n    ')
    output.append(f'ts_mean({field}, 252) + ts_std_dev({field}, 252)')
    output.append(f'ts_mean({field}, 22) + ts_std_dev({field}, 22)')
    output.append(f'ts_mean({field}, 22) * ts_std_dev({field}, 22)')
    output.append(f'ts_regression(ts_zscore(ts_mean({field}, 252),500), ts_zscore(ts_std_dev({field}, 252),500),500)')
    output.append(f'1 / ts_std_dev(ts_regression(ts_zscore(ts_mean({field}, 252),500), ts_zscore(ts_std_dev({field}, 252),500),500), 500)')
    output.append(f'\n    residual = ts_regression(ts_zscore(ts_mean({field}, 252),500), ts_zscore(ts_std_dev({field}, 252), 500), 500);\n    residual/ts_std_dev(residual, 500)\n    ')
    return output

def while_true_try_decorator(func):
    def wrapper(*args, **kwargs):
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f'发生错误: {e}. 正在重试...')
                time.sleep(2)
    return wrapper