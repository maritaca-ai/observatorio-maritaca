"""Prepare only the explicitly selected remaining benchmark; preserve native code."""
import csv
import fcntl
import json
import os
from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor

from .prepare import REPO, fetch, save, sha
from .remaining_selection import checked_bytes, require, select, read_rows


def read_plan(benchmark=None):
    plan=json.loads((REPO / 'profiles/benchmarks.json').read_text())
    plan['sampling_seed']=plan['sampling_seeds'][benchmark]
    return plan


def prepare(benchmark, cache):
    plan = read_plan(benchmark)
    require(benchmark in plan['benchmarks'] and benchmark not in plan['excluded_benchmarks'],
            'Benchmark is outside the remaining campaign')
    spec = plan['benchmarks'][benchmark]
    root = Path(cache) / 'remaining' / benchmark
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'prepare.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        lock_path = REPO / spec['upstream_lock']
        lock = json.loads(checked_bytes(lock_path, spec['upstream_lock_sha256']))
        files = {}
        for rel, item in lock['files'].items():
            source = lock_path.parent / 'fork' / rel
            checked_bytes(source, item['sha256'])
            target = root / 'sources' / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                checked_bytes(target, item['sha256'])
            else:
                shutil.copyfile(source, target)
            files[str(target.relative_to(root))] = item['sha256']
        selection = spec['selection']
        inputs = {x['path']: x for x in selection['inputs']}
        if benchmark in ('oab_bench', 'oab_bench_3941', 'oab_bench_full', 'magis_bench', 'arena_hard_v2', 'longbench_v2'):
            inputs.update(lock['runtime_inputs'])
        def fetch_input(pair):
            rel, item = pair
            target = root / 'inputs' / rel
            reused = Path(os.environ.get('S5_NANO_PUBLIC_INPUT_CACHE', str(Path(cache) / 'remaining-inputs'))) / benchmark / rel
            if not target.exists() and reused.is_file():
                checked_bytes(reused, item['sha256'])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(reused, target)
            fetch(item['url'], target, item['sha256'])
            return str(target.relative_to(root)), item['sha256']
        with ThreadPoolExecutor(max_workers=12) as pool:
            files.update(pool.map(fetch_input, inputs.items()))
        rows = []
        for item in selection['inputs']:
            path = root / 'inputs' / item['path']
            rows.extend(read_rows(path, item))
        rows = select(rows, selection, benchmark, plan['sampling_seed'])
        additional = {}
        if benchmark == 'conduta_bench':
            additional = {'data/rubrics.jsonl': lock['runtime_inputs']['data/rubrics.jsonl']}
        elif benchmark == 'harmbench':
            required = ['data/copyright_classifier_hashes/' + row['BehaviorID'] + '.pkl'
                        for row in rows if 'hash_check' in row['Tags'].split(', ')]
            additional = {rel: lock['runtime_inputs'][rel] for rel in required}
        with ThreadPoolExecutor(max_workers=12) as pool:
            files.update(pool.map(fetch_input, additional.items()))
        target = root / 'data' / 'selected.jsonl'
        target.parent.mkdir(exist_ok=True)
        data = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
        if target.exists():
            require(target.read_text() == data, 'Prepared population changed')
        else:
            target.write_text(data)
        files[str(target.relative_to(root))] = sha(target)
        body = dict(benchmark=benchmark, protocol=spec, sources=lock['sources'],
                    count=len(rows), files=files, selection_sha256=selection['selected_ids_sha256'])
        save(root / 'manifest.json', body)
        save(root / 'prepared.json', dict(manifest_sha256=sha(root / 'manifest.json'), model_or_judge_calls=0))
    return root
