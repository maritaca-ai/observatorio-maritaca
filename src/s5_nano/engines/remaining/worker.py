"""Run a pinned native evaluator with the selected population and audited transport."""
import fcntl
import json
from pathlib import Path
import sys
import time
import traceback

from s5_nano.remaining_core import Run, save
from s5_nano.remaining_cultural import evaluate as cultural
from s5_nano.remaining_knowledge import longbench
from s5_nano.remaining_sob import evaluate as sob
from s5_nano.remaining_oab import evaluate as oab
from s5_nano.remaining_magis import evaluate as magis
from s5_nano.remaining_arena import evaluate as arena
from s5_nano.remaining_harm import evaluate as harm
from s5_nano.remaining_conduta import evaluate as conduta


def ifbench(run, preflight=False):
    sys.path.insert(0, str(run.root / 'sources'))
    import evaluation_lib as native
    inputs = native.read_prompt_list(str(run.root / 'data/selected.jsonl'))
    if len(inputs) != 300 or len({i.prompt for i in inputs}) != 300:
        raise ValueError('IFBench public test population changed')
    if preflight:
        empty = {i.prompt: '' for i in inputs}
        for item in inputs:
            native.test_instruction_following_strict(item, empty)
            native.test_instruction_following_loose(item, empty)
        save(run.out / 'preflight.json', dict(passed=True, n=300, model_or_judge_calls=0))
        return
    results = run.parallel(lambda row: dict(key=row['key'], prompt=row['prompt'],
        response=run.ask(row['key'], [{'role': 'user', 'content': row['prompt']}],
                         temperature=0.6, max_tokens=4096, seed=42)['final']))
    answers = {r['prompt']: r['response'] for r in results}
    strict = [native.test_instruction_following_strict(item, answers) for item in inputs]
    loose = [native.test_instruction_following_loose(item, answers) for item in inputs]
    rows = [dict(key=item.key, strict=s.follow_all_instructions, loose=l.follow_all_instructions,
                 strict_instructions=s.follow_instruction_list, loose_instructions=l.follow_instruction_list)
            for item, s, l in zip(inputs, strict, loose)]
    run.finish(dict(score=100 * sum(r['strict'] for r in rows) / len(rows),
                    prompt_loose=100 * sum(r['loose'] for r in rows) / len(rows),
                    metric_name='prompt_strict', external_api_cost_usd=0), rows)


def main():
    task = sys.argv[1]
    run = Run(Path(__file__).resolve().parent, task)
    with (run.out / 'worker.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            {'ifbench': ifbench, 'culturalbench': cultural, 'sob': sob,
             'longbench_v2': longbench,
             'oab_bench': oab, 'oab_bench_3941': oab, 'oab_bench_full': oab,
             'magis_bench': magis, 'arena_hard_v2': arena,
             'harmbench': harm, 'conduta_bench': conduta}[task](run, '--preflight' in sys.argv)
        except BaseException as exc:
            save(run.out / 'failure.json', dict(time=time.time(), error_type=type(exc).__name__,
                                               traceback=traceback.format_exc()))
            raise


if __name__ == '__main__':
    main()
