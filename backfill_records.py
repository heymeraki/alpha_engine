#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性全量回填脚本
====================
把当前 WQ 账号在【平台上回测过的全部 Alpha】拉取下来，按其 tag 写入本地
    records/{tag}_simulated_alpha_expression.txt
文件为纯表达式格式（每行一个表达式），与当前挖掘/去重逻辑一致。

运行方式（在项目根目录）：
    python backfill_records.py

行为：
    - 分别拉取 hidden=false 与 hidden=true 的全部 Alpha（不限状态），隐藏的也不遗漏。
    - 仅归档带项目阶段 tag（以 _step1~_step4 结尾）且含 regular 表达式的 Alpha。
    - 目标文件【不存在则新建；已存在则合并】：读取本地已有表达式，与平台表达式
      取并集去重后写回，不会删除或覆盖本地已有记录，可安全重复运行。
"""

import os
import time

from machine_lib import s
from config import RECORDS_PATH

BASE_URL = 'https://api.worldquantbrain.com/users/self/alphas'
PAGE_LIMIT = 100
STEP_SUFFIXES = ('_step1', '_step2', '_step3', '_step4')


def pick_step_tag(tags):
    """从 Alpha 的 tags 列表中挑出项目阶段 tag（以 _stepN 结尾）。"""
    cleaned = []
    for t in tags or []:
        if isinstance(t, dict):
            t = t.get('name') or t.get('tag')
        if isinstance(t, str):
            cleaned.append(t)
    for t in cleaned:
        if t.endswith(STEP_SUFFIXES):
            return t
    return None


def get_with_retry(url, max_attempts=5):
    """带 Retry-After / 指数退避的 GET。"""
    for attempt in range(1, max_attempts + 1):
        resp = s.get(url)
        retry_after = resp.headers.get('Retry-After')
        if retry_after:
            print(f'    限流，等待 {retry_after}s ...')
            time.sleep(float(retry_after))
            continue
        if resp.status_code < 400:
            return resp
        wait = min(2 ** attempt, 30)
        print(f'    请求返回 {resp.status_code}，第 {attempt}/{max_attempts} 次重试，{wait}s 后继续')
        time.sleep(wait)
    raise RuntimeError(f'多次请求仍失败: {url}')


def fetch_all_alphas():
    """拉取全部（含隐藏）Alpha，按 tag 聚合为表达式集合。"""
    by_tag = {}
    stats = {'seen': 0, 'no_expression': 0, 'no_tag': 0}

    for hidden in ('false', 'true'):
        offset = 0
        total = None
        print(f'\n>>> 开始拉取 hidden={hidden} 的 Alpha')
        while True:
            url = (
                f'{BASE_URL}?limit={PAGE_LIMIT}&offset={offset}'
                f'&hidden={hidden}&order=-dateCreated'
            )
            resp = get_with_retry(url)
            data = resp.json()
            if total is None:
                total = int(data.get('count', 0))
                print(f'    该集合总数: {total}')

            results = data.get('results', [])
            for alpha in results:
                stats['seen'] += 1
                expression = (alpha.get('regular') or {}).get('code')
                if not expression:
                    stats['no_expression'] += 1
                    continue
                tag = pick_step_tag(alpha.get('tags', []))
                if not tag:
                    stats['no_tag'] += 1
                    continue
                by_tag.setdefault(tag, set()).add(expression.strip())

            got = len(results)
            offset += got
            print(f'    进度: {min(offset, total)}/{total}，已归档 tag 数: {len(by_tag)}')

            if got < PAGE_LIMIT or offset >= total:
                break
            time.sleep(0.5)

    return by_tag, stats


def merge_and_write(tag, platform_expressions):
    """
    把平台表达式合并进 {tag} 文件：
    文件不存在 -> 新建；已存在 -> 读取已有表达式取并集，去重后写回。
    返回 (合并前数量, 合并后数量, 本次新增数量)。
    """
    os.makedirs(RECORDS_PATH, exist_ok=True)
    file_path = os.path.join(RECORDS_PATH, f'{tag}_simulated_alpha_expression.txt')

    existing = set()
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    existing.add(line)

    before = len(existing)
    merged = existing | set(platform_expressions)
    after = len(merged)

    with open(file_path, 'w', encoding='utf-8') as f:
        for expression in sorted(merged):
            f.write(expression + '\n')

    return before, after, after - before


def main():
    print('=' * 60)
    print('WorldQuant Alpha 全量回填（平台 -> 本地 records）')
    print('=' * 60)

    by_tag, stats = fetch_all_alphas()

    print('\n>>> 合并写入本地记录文件')
    total_after = 0
    new_files = 0
    for tag in sorted(by_tag.keys()):
        file_path = os.path.join(RECORDS_PATH, f'{tag}_simulated_alpha_expression.txt')
        existed = os.path.exists(file_path)
        before, after, added = merge_and_write(tag, by_tag[tag])
        total_after += after
        if not existed:
            new_files += 1
        state = '新建' if not existed else '合并'
        print(f'    [{state}] {tag}: 原有 {before}，新增 {added}，现有 {after}')

    print('\n' + '=' * 60)
    print('回填完成')
    print(f'  扫描 Alpha 总数 : {stats["seen"]}')
    print(f'  覆盖 tag 数量   : {len(by_tag)}（其中新建文件 {new_files} 个）')
    print(f'  写入表达式总数  : {total_after}（去重后）')
    print(f'  跳过-无表达式   : {stats["no_expression"]}')
    print(f'  跳过-无阶段tag  : {stats["no_tag"]}')
    print('=' * 60)


if __name__ == '__main__':
    main()
