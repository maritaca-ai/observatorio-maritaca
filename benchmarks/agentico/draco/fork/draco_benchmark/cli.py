from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .api import ORIGINS, resolve_base_url, resolve_key
from .comparison import compare
from .core import (DEFAULT_CACHE, DEFAULT_JUDGE_EFFORT, DEFAULT_JUDGE_MODEL, DEFAULT_JUDGE_PROVIDER, ROOT, digest,
                   freeze, load_dataset, safe_name, select_cases, summarize, write_json)
from .runner import generate, import_reports, judge


def parser():
    p = argparse.ArgumentParser(description='DRACO: native research or imported reports; one binary grade per criterion.')
    p.add_argument('--phase', choices=['all', 'generate', 'import', 'judge', 'score', 'compare'], default='all')
    p.add_argument('--run-id', required=True)
    p.add_argument('--output-root', type=Path, default=ROOT.parents[3]/'.runs/draco')
    p.add_argument('--dataset', type=Path, default=DEFAULT_CACHE)
    p.add_argument('--selection', choices=['full', 'per-domain'], default='full')
    p.add_argument('--selection-seed', default='draco-per-domain-v1:')
    p.add_argument('--responses', type=Path, help='JSONL: case_id, generator, text, optional flags/provenance')
    p.add_argument('--model')
    p.add_argument('--provider', choices=list(ORIGINS), default='maritaca')
    p.add_argument('--base-url', help='Candidate API base URL, including /v1 when required; mandatory for openai')
    p.add_argument('--openrouter-provider', help='Pin an OpenRouter endpoint provider slug; recorded in generation configuration')
    p.add_argument('--reasoning-effort', default='medium')
    p.add_argument('--research', choices=['native', 'serper', 'none'], default='native', help='serper runs an explicit search/read tool loop; none is closed-book')
    p.add_argument('--search-api-key-env', default='SERPER_API_KEY', help='Credential for --research serper; no implicit credential fallback')
    p.add_argument('--max-tokens', type=int, default=32768)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--api-key-env', help='Default: provider-specific env; value is never a CLI argument')
    p.add_argument('--judge-model', default=DEFAULT_JUDGE_MODEL)
    p.add_argument('--judge-provider', choices=['openrouter', 'maritaca'], default=DEFAULT_JUDGE_PROVIDER)
    p.add_argument('--judge-effort', default=DEFAULT_JUDGE_EFFORT)
    p.add_argument('--judge-label', help='Default: s5-xhigh for the default judge; derived from model/effort otherwise')
    p.add_argument('--judge-max-tokens', type=int, default=8192)
    p.add_argument('--judge-workers', type=int, default=16)
    p.add_argument('--allow-new-reports', action='store_true',
                   help='Allow new immutable reports to be added on judge resume; incomplete scores remain unpublished')
    p.add_argument('--judge-api-key-env')
    p.add_argument('--timeout', type=float, default=1200)
    p.add_argument('--compare-judges', nargs='+')
    p.add_argument('--bootstrap', type=int, default=10000)
    p.add_argument('--exclude-flagged', action='store_true', help='Sensitivity only; retain primary all-output comparison')
    p.add_argument('--wandb', action='store_true', help='Upload complete aggregate scores only')
    p.add_argument('--wandb-entity', default=None)
    p.add_argument('--wandb-project', default=None)
    return p


def canonical_protocol(summary, selection):
    generations = summary['generation_configs']
    return (selection == 'full' and len(summary['by_generator']) == 1
        and not summary['imported'] and len(generations) == 1 and generations[0]['research']
        and generations[0].get('research_backend', 'native') == 'native'
        and summary['config']['model'] == DEFAULT_JUDGE_MODEL
        and summary['config']['effort'] == DEFAULT_JUDGE_EFFORT
        and summary['config']['provider'] == DEFAULT_JUDGE_PROVIDER
        and summary['config']['max_tokens'] == 8192
        and 'base_url' not in generations[0])


def upload(summary, args, manifest):
    if not summary['complete']:
        raise ValueError('Refusing to publish incomplete scores')
    import wandb
    canonical = canonical_protocol(summary, args.selection)
    name = f'{args.run_id}_draco' if canonical else f'{args.run_id}_draco_{args.selection}_{args.judge_label}'
    run = wandb.init(entity=args.wandb_entity, project=args.wandb_project,
        id=name, name=name,
        resume='allow', config={'benchmark': 'draco', 'dataset': manifest, 'selection': args.selection,
            'judge': summary['config'], 'generation': summary['generation_configs'],
            'imported': summary['imported'], 'grades_per_criterion': 1})
    for generator, values in summary['by_generator'].items():
        namespace = 'draco' if len(summary['by_generator']) == 1 else f'draco/{generator}'
        run.summary[f'{namespace}/score'] = values['mean_score']/100
        run.summary[f'{namespace}/n_scored'] = values['n_scored']
    run.summary['draco/judge_model'] = summary['config']['model']
    run.summary['draco/judge_effort'] = summary['config']['effort']
    run.finish()


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.wandb and not (args.wandb_entity and args.wandb_project):
        p.error("--wandb requires explicit --wandb-entity and --wandb-project")
    if args.judge_label is None:
        default_judge = (args.judge_provider, args.judge_model, args.judge_effort) == (DEFAULT_JUDGE_PROVIDER, DEFAULT_JUDGE_MODEL, DEFAULT_JUDGE_EFFORT)
        args.judge_label = 's5-xhigh' if default_judge else f'judge-{digest([args.judge_provider, args.judge_model, args.judge_effort])[:12]}'
    if min(args.workers, args.judge_workers, args.max_tokens, args.judge_max_tokens) <= 0 or args.bootstrap < 0 or args.timeout <= 0:
        p.error('Workers, token limits and timeout must be positive; bootstrap must be nonnegative')
    run_dir = args.output_root/safe_name(args.run_id)
    safe_name(args.judge_label)
    cases, manifest = load_dataset(args.dataset)
    cases = select_cases(cases, args.selection, args.selection_seed)
    freeze(run_dir/'dataset.json', {'manifest': manifest, 'selection': args.selection,
        'selection_seed': args.selection_seed, 'cases_sha256': digest(cases), 'case_ids': [c['id'] for c in cases]})
    freeze(run_dir/'selected_cases.json', cases)
    if args.phase == 'import':
        if not args.responses:
            p.error('--responses is required for import')
        import_reports(run_dir, cases, args.responses)
        return
    if args.phase in ('all', 'generate'):
        if not args.model:
            p.error('--model is required for generation')
        if args.research == 'serper' and args.provider not in ('openrouter', 'openai'):
            p.error('--research serper requires --provider openrouter or openai')
        if args.provider == 'openai' and args.research == 'native':
            p.error('--provider openai requires --research serper or none')
        if args.openrouter_provider and args.provider != 'openrouter':
            p.error('--openrouter-provider requires --provider openrouter')
        key = resolve_key(args.provider, args.api_key_env)
        config = {'model': args.model, 'provider': args.provider, 'effort': args.reasoning_effort,
                  'max_tokens': args.max_tokens, 'research': args.research != 'none'}
        endpoint_url = resolve_base_url(args.provider, args.base_url)
        if args.base_url is not None:
            config['base_url'] = endpoint_url
        if args.openrouter_provider:
            config['openrouter_provider'] = args.openrouter_provider
        search_key = None
        if args.research == 'serper':
            from .research import PROTOCOL
            config.update(research_backend='serper', research_protocol=PROTOCOL)
            search_key = resolve_key('openrouter', env_name=args.search_api_key_env)
        asyncio.run(generate(run_dir, cases, config, key, args.workers, args.timeout, search_key))
        del search_key
        del key
    if args.phase in ('all', 'judge'):
        key = resolve_key(args.judge_provider, args.judge_api_key_env)
        config = {'model': args.judge_model, 'provider': args.judge_provider, 'effort': args.judge_effort,
                  'max_tokens': args.judge_max_tokens}
        asyncio.run(judge(run_dir, cases, config, args.judge_label, key, args.judge_workers, args.timeout,
                          allow_new_reports=args.allow_new_reports))
        del key
    if args.phase in ('all', 'judge', 'score'):
        summary = summarize(run_dir, cases, args.judge_label)
        print(summary['by_generator'])
        if not summary['complete']:
            raise SystemExit('Incomplete run; no aggregate benchmark score published')
        if args.wandb:
            upload(summary, args, manifest)
    if args.phase == 'compare':
        if not args.compare_judges or len(args.compare_judges) < 2 or len(set(args.compare_judges)) != len(args.compare_judges):
            p.error('--compare-judges requires at least two distinct labels')
        summaries = [summarize(run_dir, cases, label) for label in args.compare_judges]
        result = compare(summaries, bootstrap=args.bootstrap, exclude_flags=args.exclude_flagged)
        suffix = '_excluding_flagged' if args.exclude_flagged else ''
        destination = run_dir/f'comparison{suffix}.json'
        write_json(destination, result)
        for pair in result:
            print(pair['judge_a'], pair['judge_b'], pair['binary'], pair['scores'])
        print(destination)
