"""CondutaBench subset with the frozen authors' prompt, parser and scorer."""
import json
import os

from .auditing import OpenAI
from .remaining_core import definitions, save


def native_modules(source):
    providers = definitions(source / 'providers.py',
        ['PROVIDERS', 'APIError', 'prepare', 'extract'])
    evaluator = definitions(source / 'evaluate.py',
        ['EvaluationError', 'validate_hits', 'score', 'request', 'parse_judgment', 'summarize'],
        dict(json=json))
    return providers, evaluator


def evaluate(run, preflight=False):
    providers, native = native_modules(run.root / 'sources')
    with (run.root / 'inputs/data/rubrics.jsonl').open() as stream:
        rubrics = {r['id']: r for r in map(json.loads, stream)}
    settings = run.manifest['protocol']['judge']
    if (settings['model'], settings['temperature'], settings['max_tokens'], settings['service_tier']) != (
            'sabia-4-thinking', 0, 8000, 'auto'):
        raise ValueError('Conduta native judge settings changed')
    if len(run.rows) != 140 or len({r['guideline_id'] for r in run.rows}) != 14:
        raise ValueError('Conduta requires the pinned 140-question, 14-guideline subset')

    def request(row, answer):
        return providers.prepare('maritaca', settings['model'],
            native.request(row, rubrics[row['id']], answer, settings['model'])['messages'],
            settings['max_tokens'], settings['temperature'])

    if preflight:
        for row in run.rows:
            rubric = rubrics[row['id']]
            request(row, 'Synthetic final answer')
            hits = {str(i): c['weight'] > 0 for i, c in enumerate(rubric['criteria'])}
            assert native.score(rubric['criteria'], hits)['score'] == 100
        save(run.out / 'preflight.json', dict(passed=True, n=140, guidelines=14,
            full_population=715, model_or_judge_calls=0, native_judge=settings['model']))
        return

    # Check availability before candidate generation; credentials never enter artifacts.
    if run.judge_client is None:
        run.judge_client = OpenAI(base_url='https://chat.maritaca.ai/api',
            api_key=os.environ['MARITACA_API_KEY'], timeout=300, max_retries=0)

    def one(row):
        qid = row['id']
        # Exact public run.py message, with the campaign profile enforced at transport.
        final = run.ask(qid, [dict(role='user',
            content=f"{row['scenario']}\n\n{row['question']}")])['final']
        payload = request(row, final)
        size = len(rubrics[qid]['criteria'])

        def produce():
            raw = run.judge_client.chat.completions.create(**payload['body']).model_dump(mode='json')
            if raw.get('model') != settings['model']:
                raise ValueError('Conduta judge model identity differs; raw response preserved for audit')
            # The authors reject truncation, refusals and malformed criterion coverage.
            text = providers.extract('maritaca', raw)['text']
            hits = native.parse_judgment(text, size)
            return dict(hits=hits, judgment=text, raw=raw)

        def valid(result):
            if not isinstance(result, dict):
                return False
            try:
                native.validate_hits(result.get('hits'), size)
            except (ValueError, TypeError):
                return False
            return True

        verdict = run.judgment(qid, dict(payload=payload), produce, valid)
        return dict(id=qid, guideline_id=row['guideline_id'],
            metrics=native.score(rubrics[qid]['criteria'], verdict['hits']))

    rows = sorted(run.parallel(one), key=lambda r: r['id'])
    summary = native.summarize(rows)
    save(run.out / 'native_summary.json', dict(summary, expected_questions=715,
        coverage_pct=100 * len(rows) / 715, judgment_source=settings['model'],
        judge_provider='maritaca', judge_settings=settings))
    run.finish(dict(summary['overall'], by_guideline=summary['by_guideline'],
        full_population=715, coverage_pct=100 * len(rows) / 715,
        sampled=True, metric_name='native_conduta_score_140',
        judge=settings['model'], judge_max_tokens=8000, judge_temperature=0), rows)
