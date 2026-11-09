"""Resumable generation and blind, one-criterion grading."""
from __future__ import annotations

import asyncio
import json

from .api import Client, make_body
from .core import (GENERATOR_SYSTEM, JUDGE_SYSTEM, checked_grade, criteria, digest, freeze,
                   judge_messages, parse_grade, read_json, report_id, reports, safe_name,
                   store_report, write_json)


async def run_jobs(jobs, workers, status_path):
    if workers < 1:
        raise ValueError('workers must be positive')
    semaphore = asyncio.Semaphore(workers)
    counts = {'completed': 0, 'failed': 0, 'errors': []}

    async def invoke(key, job):
        async with semaphore:
            try:
                await job()
                counts['completed'] += 1
            except Exception as error:
                counts['failed'] += 1
                counts['errors'].append({'item': key, 'error': str(error)})
            write_json(status_path, counts)
            if (counts['completed']+counts['failed']) % 25 == 0:
                print(json.dumps({k: counts[k] for k in ('completed', 'failed')}), flush=True)

    await asyncio.gather(*(invoke(key, job) for key, job in jobs))
    write_json(status_path, counts)
    if counts['failed']:
        raise RuntimeError(f'{counts["failed"]} failed items; resume to retry only those. See {status_path}')


async def generate(run_dir, cases, config, key, workers=4, timeout=1200, search_key=None):
    generator = config['model']
    freeze(run_dir/'generation_configs'/f'{digest(generator)[:16]}.json',
           dict(config, system_sha256=digest(GENERATOR_SYSTEM)))
    client = Client(config['provider'], key, timeout, base_url=config.get('base_url'))
    search = None
    if config.get('research_backend') == 'serper':
        from .research import Serper
        if not search_key or config['provider'] not in ('openrouter', 'openai'):
            raise ValueError('Serper research requires its own credential and an OpenRouter or OpenAI-compatible candidate')
        search = Serper(search_key)

    async def one(case):
        rid = report_id(case['id'], generator)
        if (run_dir/'answers'/f'{rid}.json').exists():
            row = read_json(run_dir/'answers'/f'{rid}.json')
            if row.get('generation_config_sha256') != digest(config) or row['text_sha256'] != digest(row['text']):
                raise ValueError('Existing generation does not match configuration')
            return
        # Only the query is sent: no rubric, weights, task ID, or other outputs.
        endpoint, body = make_body(config['provider'], generator, config['effort'],
            [{'role': 'system', 'content': GENERATOR_SYSTEM}, {'role': 'user', 'content': case['problem']}],
            config['max_tokens'], research=config['research'] and search is None)
        if config.get('openrouter_provider'):
            body['provider']['only'] = [config['openrouter_provider']]

        def parse(text):
            if not text.strip():
                raise ValueError('Empty model response')
            return text

        if search is not None:
            from .research import research
            text, data, attempt, seconds = await research(client, search, run_dir, rid, config, case['problem'])
        else:
            text, data, attempt, seconds = await client.request(endpoint, body, run_dir/'generation_attempts'/rid, parse)
        store_report(run_dir, case['id'], generator, text, generation_config_sha256=digest(config),
            usage=data.get('usage'), seconds=seconds, attempt=attempt,
            flags=['short_output_under_300_chars'] if len(text.strip()) < 300 else [])

    try:
        await run_jobs([(c['id'], lambda c=c: one(c)) for c in cases], workers, run_dir/'generation_status.json')
    finally:
        await client.close()
        if search is not None:
            await search.close()


def import_reports(run_dir, cases, path):
    case_ids = {c['id'] for c in cases}
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    seen = set()
    for row in rows:
        if row['case_id'] not in case_ids:
            raise ValueError('Imported task does not belong to this selection')
        rid = report_id(row['case_id'], row['generator'])
        if rid in seen:
            raise ValueError('Duplicate imported report')
        seen.add(rid)
        if 'text_sha256' in row and row['text_sha256'] != digest(row['text']):
            raise ValueError('Imported text hash mismatch')
    if not rows:
        raise ValueError('No imported reports')
    # Freeze the whole input before writing any answers, including provenance/flags.
    freeze(run_dir/'import_manifest.json', {'sha256': digest(path.read_bytes()), 'reports': len(rows)})
    for row in rows:
        metadata = {k: v for k, v in row.items() if k not in ('case_id', 'generator', 'text', 'text_sha256', 'report_id')}
        store_report(run_dir, row['case_id'], row['generator'], row['text'], **metadata)


def freeze_judge_inputs(path, inputs, allow_new_reports=False):
    """Optionally append new reports while keeping every prior input immutable."""
    if not allow_new_reports:
        freeze(path, inputs)
        return
    if path.exists():
        previous = read_json(path)
        if any(inputs.get(rid) != sha for rid, sha in previous.items()):
            raise ValueError('Previously judged reports were removed or changed')
        if previous == inputs:
            return
        freeze(path.parent/'input_history'/digest(previous)/'inputs.json', previous)
    write_json(path, inputs)


async def judge(run_dir, cases, config, label, key, workers=16, timeout=1200, allow_new_reports=False):
    folder = run_dir/'judgments'/safe_name(label)
    config = dict(config, judge_system_sha256=digest(JUDGE_SYSTEM), grades_per_criterion=1,
                  web_search=False, temperature='provider default')
    freeze(folder/'config.json', config)
    case_map = {c['id']: c for c in cases}
    rows = reports(run_dir, cases)
    if not rows:
        raise ValueError('No reports to judge; generate or import first')
    freeze_judge_inputs(folder/'inputs.json',
        {r['report_id']: r['text_sha256'] for r in rows}, allow_new_reports)
    client = Client(config['provider'], key, timeout)

    async def one(row, index, item):
        case = case_map[row['case_id']]
        final = folder/row['report_id']/f'{index:03d}.json'
        if final.exists():
            checked_grade(final, case, row, index, config)
            return
        messages = judge_messages(case, row['text'], item)
        endpoint, body = make_body(config['provider'], config['model'], config['effort'], messages, config['max_tokens'])
        parsed, data, attempt, seconds = await client.request(endpoint, body,
            folder/'attempts'/row['report_id']/f'{index:03d}', parse_grade)
        write_json(final, dict(parsed, report_id=row['report_id'], report_sha256=row['text_sha256'],
            criterion_index=index, criterion=item, config_sha256=digest(config),
            messages_sha256=digest(messages), usage=data.get('usage'), attempt=attempt, seconds=seconds))

    jobs = [(f'{r["report_id"]}/{i}', lambda r=r, i=i, c=c: one(r, i, c))
            for r in rows for i, c in enumerate(criteria(case_map[r['case_id']]))]
    try:
        await run_jobs(jobs, workers, folder/'status.json')
    finally:
        await client.close()
