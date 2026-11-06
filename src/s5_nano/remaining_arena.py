"""Native Arena-Hard-v2 prompts, two orders and weighted bootstrap report."""
import contextlib
import io
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .remaining_core import definitions, save

LABELS = {'A>B', 'A>>B', 'A=B', 'A<<B', 'A<B', 'B>A', 'B>>A', 'B=A', 'B<<A', 'B<A'}


def evaluate(run, preflight=False):
    source = run.root / 'sources'
    settings = definitions(source / 'utils/judge_utils.py', ['OG_ARENA_HARD_PROMPT', 'JUDGE_SETTINGS']).JUDGE_SETTINGS
    config = yaml.safe_load((source / 'config/arena-hard-v2.0.yaml').read_text())
    config['judge_model'] = 'gpt-6-luna'
    baselines = {}
    for model in {settings[r['category']]['baseline'] for r in run.rows}:
        baselines[model] = {r['uid']: r for r in map(json.loads,
            (run.root / 'inputs/data/arena-hard-v2.0/model_answer' / (model + '.jsonl')).open())}
    def complete(**kwargs):
        if preflight:
            return {'answer': '[[A=B]]'}
        result = run.paid_client().responses.create(model='gpt-6-luna', input=kwargs['messages'],
            reasoning={'effort': 'medium', 'summary': 'detailed'}, max_output_tokens=kwargs['max_tokens'])
        if result.status != 'completed':
            raise RuntimeError('Incomplete Arena judgment; attempt remains pending')
        return dict(answer=result.output_text, raw=result.model_dump(mode='json'))
    native = definitions(source / 'gen_judgment.py', ['get_score', 'pairwise_judgment'],
        dict(JUDGE_SETTINGS=settings, get_endpoint=lambda _: None, registered_api_completion={'local_audited': complete}))
    if len(run.rows) != 150 or sum(row['category'] == 'hard_prompt' for row in run.rows) != 100:
        raise ValueError('Arena selected category counts changed')
    def one(row):
        final = 'Synthetic answer' if preflight else run.ask(row['uid'], [{'role': 'user', 'content': row['prompt']}])['final']
        answer = dict(model=run.identity['model'], messages=[dict(role='assistant', content={'answer': final})])
        baseline = baselines[settings[row['category']]['baseline']][row['uid']]
        games = []
        for order, (a, b) in enumerate(((baseline, answer), (answer, baseline))):
            produce = lambda: native.pairwise_judgment(row, a, b, None, config,
                                                       dict(api_type='local_audited', endpoints=[]))
            game = produce() if preflight else run.judgment(str(row['uid']) + ':' + str(order),
                dict(answer_a=a, answer_b=b, config=config, judge=run.manifest['protocol']['judge']),
                produce, lambda x: isinstance(x, dict) and x.get('score') in LABELS,
                required_model='gpt-6-luna')
            games.append(game)
        return dict(uid=row['uid'], category=row['category'], model=run.identity['model'],
                    judge='gpt-6-luna', baseline=baseline['model'], games=games)
    if preflight:
        assert all(one(row)['games'][0]['score'] == 'A=B' for row in run.rows)
        save(run.out / 'preflight.json', dict(passed=True, n=150, judgments=300, model_or_judge_calls=0))
        return
    rows = sorted(run.parallel(one), key=lambda x: str(x['uid']))
    path = run.out / 'native_judgments.jsonl'
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    report = definitions(source / 'show_result.py',
        ['load_judgments', 'format_confidence_interval', 'print_leaderboard'],
        dict(pd=pd, os=os, glob=lambda _: [str(path)], tqdm=lambda rows: rows, JUDGE_SETTINGS=settings))
    captured = {}
    original_format = report.format_confidence_interval
    def capture(mean, lower, upper, baseline):
        captured[baseline] = dict(mean=mean.to_dict('records'), lower=lower.to_dict('records'), upper=upper.to_dict('records'))
        return original_format(mean, lower, upper, baseline)
    report.format_confidence_interval = capture
    with contextlib.redirect_stdout(io.StringIO()) as output:
        battles = report.load_judgments(['gpt-6-luna'], 'arena-hard-v2.0', weight=3)
        for category in ('hard_prompt', 'creative_writing'):
            np.random.seed(42)
            report.print_leaderboard(battles[battles.category == category].reset_index(drop=True), category)
    (run.out / 'native_leaderboard.txt').write_text(output.getvalue())
    scores = {category: 100 * captured[settings[category]['baseline']]['mean'][0]['scores']
              for category in ('hard_prompt', 'creative_writing')}
    run.finish(dict(score=scores['hard_prompt'], creative_writing_score=scores['creative_writing'],
        metric_name='native_hard_prompt_weighted_bootstrap', primary_cases=100, creative_cases=50,
        judge='gpt-6-luna', judge_reasoning_effort='medium', bootstrap_seed=42,
        native_bootstrap_statistics=captured), rows)
