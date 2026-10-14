import time
from datetime import datetime
import pandas as pd
from machine_lib import s

def submit_alpha(session, alpha_id, inner_logger):
    submit_url = f'https://api.worldquantbrain.com/alphas/{alpha_id}/submit'
    attempts = 0
    while attempts < 5:
        attempts += 1
        inner_logger.print(f'Attempt {attempts} to submit {alpha_id}.')
        res = session.post(submit_url)
        if res.status_code == 201:
            inner_logger.print(f'Alpha {alpha_id} POST Status 201. Start submitting...')
            break
        elif res.status_code == 400:
            inner_logger.print(f'Alpha {alpha_id} POST Status {res.status_code}.')
            inner_logger.print(f'Alpha {alpha_id} Already POST.')
            inner_logger.print(res.content)
            break
        elif res.status_code == 403:
            inner_logger.print(f'Alpha {alpha_id} POST Status {res.status_code}.')
            try:
                inner_logger.print(pd.DataFrame(res.json()['is']['checks'])[['name', 'value', 'result']])
            except KeyError:
                try:
                    inner_logger.print(pd.DataFrame(res.json()['is']['checks'])[['name', 'result']])
                except Exception:
                    inner_logger.print(res.text)
            return res.status_code
        else:
            inner_logger.print(f'Alpha {alpha_id} POST Status {res.status_code}.')
            inner_logger.print(res.content)
            time.sleep(3)
    
    count = 0
    s_t = datetime.now()
    while True:
        res = session.get(submit_url)
        if res.status_code == 200:
            retry = res.headers.get('Retry-After', 0)
            if retry:
                count += 1
                time.sleep(float(retry))
                if count % 75 == 0:
                    inner_logger.print(f'Alpha {alpha_id} GET Status 200. Waiting... {datetime.now() - s_t}.')
                continue
            else:
                inner_logger.print(f'Alpha {alpha_id} was submitted successfully.')
                return res.status_code
        elif res.status_code == 403:
            inner_logger.print(f'Alpha {alpha_id} GET Status {res.status_code}.')
            inner_logger.print(f'Alpha {alpha_id} submit failed. Need Improvement.')
            try:
                inner_logger.print(pd.DataFrame(res.json()['is']['checks'])[['name', 'value', 'result']])
            except KeyError:
                try:
                    inner_logger.print(pd.DataFrame(res.json()['is']['checks'])[['name', 'result']])
                except Exception:
                    inner_logger.print(res.text)
            return res.status_code
        elif res.status_code == 404:
            inner_logger.print(f'Alpha {alpha_id} GET Status {res.status_code}.')
            inner_logger.print(f'Alpha {alpha_id} submit failed. Time Out.')
            return 404
        else:
            inner_logger.print(f'Alpha {alpha_id} GET Status {res.status_code}.')
            inner_logger.print(f'Alpha {alpha_id} submit failed. Time Out.')
            inner_logger.print(res.headers)
            inner_logger.print(res.content)
            return res.status_code
    return 404

def run_task(alpha_id, inner_logger):
    inner_logger.print(datetime.now(), '=================提交Alpha任务==================')
    inner_logger.print(datetime.now(), f'Alpha ID: {alpha_id}')
    inner_logger.print(datetime.now(), f'开始时间: {datetime.now()}')
    inner_logger.print(datetime.now(), '=============================================')
    time.sleep(1)
    status_code = submit_alpha(s, alpha_id, inner_logger)
    inner_logger.print(datetime.now(), '=================任务完成==================')
    inner_logger.print(datetime.now(), f'Alpha ID: {alpha_id}')
    inner_logger.print(datetime.now(), f'最终状态码: {status_code}')
    inner_logger.print(datetime.now(), f'结束时间: {datetime.now()}')
    inner_logger.print(datetime.now(), '===========================================')
