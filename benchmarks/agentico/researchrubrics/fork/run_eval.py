#!/usr/bin/env python3
"""Original ResearchRubrics: pinned 101 cases, Serper research, S5 instruct judge."""
import argparse
import asyncio
import fcntl
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'draco'/'fork'))
from draco_benchmark.api import resolve_base_url, Client, make_body, resolve_key, response_text
from draco_benchmark.core import GENERATOR_SYSTEM, digest, freeze, read_json, write_json, safe_name
from draco_benchmark.runner import freeze_judge_inputs, run_jobs
from research import PROTOCOL, Serper, research

DEFAULT_JUDGE = {'provider': 'maritaca', 'model': 'S5', 'effort': 'none', 'max_tokens': 50000}


def load_inputs(cache):
    manifest = read_json(HERE/'upstream_manifest.json')
    for name, entry in manifest['sources'].items():
        path = cache/name
        if not path.exists():
            with urlopen(entry['url'], timeout=120) as response:
                raw = response.read()
            if digest(raw) != entry['sha256']:
                raise ValueError(f'Upstream checksum mismatch: {name}')
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix+'.partial')
            tmp.write_bytes(raw)
            tmp.replace(path)
        if digest(path.read_bytes()) != entry['sha256']:
            raise ValueError(f'Cached checksum mismatch: {name}')
    cases = [json.loads(line) for line in (cache/'processed_data.jsonl').read_text().splitlines() if line.strip()]
    if len(cases) != 101 or len({c['sample_id'] for c in cases}) != 101:
        raise ValueError('Expected the full 101 unique released questions')
    if sum(len(c['rubrics']) for c in cases) != 2593:
        raise ValueError('Expected 2593 original human criteria')
    for case in cases:
        if not case['prompt'].strip() or not any(c['weight'] > 0 for c in case['rubrics']):
            raise ValueError('Invalid query or rubric denominator')
    return cases, manifest


def parse_grade(text):
    # Preserve a single full Markdown wrapper and illegal literal LaTeX escapes.
    fenced = re.fullmatch(r'\s*```(?:json)?\s*\n(.*?)\n```\s*', text, re.S | re.I)
    value = fenced.group(1) if fenced else text
    for _ in range(len(value)+1):
        try:
            result = json.loads(value)
            break
        except json.JSONDecodeError as error:
            if error.msg != 'Invalid \\escape' or value[error.pos] != '\\':
                raise
            value = value[:error.pos]+'\\'+value[error.pos:]
    if (not isinstance(result, dict) or type(result.get('score')) not in (int, float)
            or result['score'] not in (0, 1)
            or result.get('verdict') != ('Satisfied' if result['score'] else 'Not Satisfied')
            or not isinstance(result.get('reasoning'), str) or not result['reasoning'].strip()
            or type(result.get('confidence')) not in (int, float) or not 0 <= result['confidence'] <= 1):
        raise ValueError('Invalid binary judgment')
    return result


def question_score(criteria, grades):
    if len(grades) != len(criteria) or any(type(v) not in (int, float) or v not in (0, 1) for v in grades):
        raise ValueError('Incomplete or invalid grades')
    denominator = sum(c['weight'] for c in criteria if c['weight'] > 0)
    if denominator <= 0:
        raise ValueError('No positive rubric weights')
    # Official signed-weight score: do not clip negatives or reweight questions.
    return 100*sum(c['weight']*v for c, v in zip(criteria, grades))/denominator


def messages(cache, criterion, report):
    folder = cache/'src/prompts'
    return [dict(role='system', content=(folder/'system_prompt.txt').read_text()),
            dict(role='user', content=(folder/'user_prompt.txt').read_text().format(
                document_content=report, rubric_title=criterion['criterion'],
                rubric_category=criterion['axis'], rubric_weight=criterion['weight']))]


def body_for(spec, prompt):
    endpoint, body = make_body(spec['provider'], spec['model'], spec['effort'], prompt, spec['max_tokens'])
    if spec.get('openrouter_provider'):
        body['provider']['only'] = [spec['openrouter_provider']]
    body['response_format'] = {'type': 'json_object'}
    return endpoint, body


def check_vote(row, spec, prompt, parser=parse_grade):
    _, body = body_for(spec, prompt)
    if row['request_sha256'] != digest(body) or row['spec'] != spec:
        raise ValueError('Judgment input/configuration changed')
    if row['text_sha256'] != digest(row['text']) or parser(row['text']) != row['parsed']:
        raise ValueError('Judgment text/grade changed')
    receipt = read_json(row['attempt'])
    actual = dict(receipt['request'])
    if digest(actual) != row['actual_request_sha256']:
        raise ValueError('Judgment receipt changed')
    if not spec['max_tokens'] <= actual['max_tokens'] <= 65536:
        raise ValueError('Unexpected judge output limit')
    actual['max_tokens'] = body['max_tokens']
    if 'response_format' not in actual and row.get('json_transport_fallback'):
        actual['response_format'] = {'type': 'json_object'}
    response = receipt['response']
    if (actual != body or response['model'] != spec['model']
            or response['choices'][0]['finish_reason'] != 'stop'
            or response_text(response) != row['text']):
        raise ValueError('Judgment does not match its provider receipt')
    return row['parsed']


async def saved_grade(client, spec, prompt, path, parser=parse_grade):
    if path.exists():
        row = read_json(path)
        check_vote(row, spec, prompt, parser)
        return row
    if client is None:
        raise ValueError(f'Missing judgment: {path}; run --phase judge first')
    endpoint, body = body_for(spec, prompt)
    attempts = path.parent/'attempts'/path.stem
    recovered = None
    for prior in sorted(attempts.glob('[0-9][0-9][0-9][0-9].json')):
        receipt = read_json(prior)
        actual = dict(receipt['request'])
        actual['max_tokens'] = body['max_tokens']
        actual.setdefault('response_format', {'type': 'json_object'})
        response = receipt.get('response')
        if actual != body or not response or response['choices'][0]['finish_reason'] != 'stop':
            continue
        try:
            parsed = parser(response_text(response))
        except (ValueError, KeyError, TypeError):
            continue
        recovered = parsed, response, str(prior), receipt['seconds']
        break
    if recovered is None:
        parsed, data, attempt, seconds = await client.request(endpoint, body, attempts, parser)
    else:
        parsed, data, attempt, seconds = recovered
    actual = read_json(attempt)['request']
    row = dict(spec=spec, text=response_text(data), text_sha256=digest(response_text(data)), parsed=parsed,
               request_sha256=digest(body), actual_request_sha256=digest(actual),
               json_transport_fallback='response_format' not in actual,
               usage=data.get('usage'), attempt=attempt, seconds=seconds)
    check_vote(row, spec, prompt, parser)
    write_json(path, row)
    return row


def chunk_prompts(cache, criterion, report):
    # Match the official large-document path and threshold (characters / 4).
    folder = cache/'src/prompts'
    chunks, chunk = [], ''
    for paragraph in report.split('\n\n'):
        if len(chunk)+len(paragraph) < 400000:
            chunk += paragraph+'\n\n'
        else:
            if chunk:
                chunks.append(chunk.strip())
            chunk = paragraph+'\n\n'
    if chunk:
        chunks.append(chunk.strip())
    for i, chunk in enumerate(chunks, 1):
        yield [dict(role='system', content='You are evaluating document chunks for rubric criteria.'),
               dict(role='user', content=(folder/'chunk_prompt_template.txt').read_text().format(
                   chunk_num=i, total_chunks=len(chunks), context_summary='Previous chunks evaluated' if i > 1 else 'First chunk',
                   chunk_content=chunk, rubric_title=criterion['criterion'], rubric_category=criterion['axis']))]


def parse_chunk(text):
    value = json.loads(text)
    if not isinstance(value.get('relevant_evidence'), list):
        raise ValueError('Missing chunk evidence')
    return value


async def grade_report(client, spec, cache, criterion, text, path):
    if len(text)//4 <= 200000:
        return await saved_grade(client, spec, messages(cache, criterion, text), path)
    evidence = []
    for i, prompt in enumerate(chunk_prompts(cache, criterion, text)):
        row = await saved_grade(client, spec, prompt, path.parent/'chunks'/path.stem/f'{i:03d}.json', parse_chunk)
        evidence.extend(row['parsed']['relevant_evidence'])
    folder = cache/'src/prompts'
    prompt = [dict(role='system', content=(folder/'system_prompt.txt').read_text()),
              dict(role='user', content=(folder/'synthesis_prompt_template.txt').read_text().format(
                  all_evidence=json.dumps(evidence, indent=2), rubric_title=criterion['criterion'], rubric_category=criterion['axis']))]
    return await saved_grade(client, spec, prompt, path)


def answer_path(run, case):
    return run/'answers'/f'{case["sample_id"]}.json'


def check_answer(answer, case):
    if (answer['case_id'] != case['sample_id'] or answer['query_sha256'] != digest(case['prompt'])
            or not answer['text'].strip() or answer['text_sha256'] != digest(answer['text'])):
        raise ValueError('Answer identity/query/text changed')


def store_answer(run, case, text, **metadata):
    row = dict(metadata, case_id=case['sample_id'], query_sha256=digest(case['prompt']), text=text, text_sha256=digest(text))
    check_answer(row, case)
    freeze(answer_path(run, case), row)


def import_answers(run, cases, path):
    data = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    by_id = {c['sample_id']: c for c in cases}
    if not data or len({r['case_id'] for r in data}) != len(data):
        raise ValueError('Empty or duplicate imported answers')
    for row in data:
        if row['case_id'] not in by_id or not row['text'].strip():
            raise ValueError('Unknown/empty imported answer')
        if 'text_sha256' in row and row['text_sha256'] != digest(row['text']):
            raise ValueError('Imported answer hash mismatch')
    freeze(run/'import.json', dict(sha256=digest(path.read_bytes()), reports=len(data)))
    for row in data:
        store_answer(run, by_id[row['case_id']], row['text'], imported=True, source=row.get('source'))


def generation_config(args):
    if args.context_length <= 0 or args.max_tokens <= 0 or args.context_reserve < 0:
        raise ValueError('Context/output limits must be positive; context reserve must be nonnegative')
    if args.openrouter_provider and args.provider != 'openrouter':
        raise ValueError('--openrouter-provider requires --provider openrouter')
    spec = dict(model=args.model, effort=args.reasoning_effort, provider=args.provider, max_tokens=args.max_tokens,
                output_ceiling=args.max_tokens, openrouter_provider=args.openrouter_provider,
                research_protocol=PROTOCOL, input_byte_budget=min(500000, args.context_length-args.max_tokens-args.context_reserve))
    if spec['input_byte_budget'] <= 0:
        raise ValueError('Context must exceed max-tokens + context-reserve')
    # Preserve the configuration identity of existing runs using the old default.
    if args.context_reserve != 4096:
        spec.update(context_reserve=args.context_reserve, context_length=args.context_length)
    endpoint_url = resolve_base_url(args.provider, args.base_url)
    if args.base_url is not None:
        spec['base_url'] = endpoint_url
    return spec


async def generate(args, run, cases):
    spec = generation_config(args)
    freeze(run/'generation.json', dict(spec, system_sha256=digest(GENERATOR_SYSTEM)))
    client = Client(args.provider, credential(args, args.provider, False), args.timeout, output_ceiling=args.max_tokens, base_url=spec.get('base_url'))
    search_key = os.environ.get(args.search_api_key_env)
    if not search_key:
        await client.close()
        raise ValueError(f'Missing search credential: {args.search_api_key_env}')
    search = Serper(search_key)
    async def one(case):
        path = answer_path(run, case)
        if path.exists():
            row = read_json(path)
            check_answer(row, case)
            if row.get('generation_sha256') != digest(spec):
                raise ValueError('Cannot reuse a different generation protocol')
            return
        text, data, attempt, seconds = await research(client, search, run, case['sample_id'], spec, case['prompt'])
        store_answer(run, case, text, generation_sha256=digest(spec), usage=data['usage'], attempt=attempt,
                     seconds=seconds, output_limit_reached=data.get('output_limit_reached', False))
    try:
        await run_jobs([(c['sample_id'], lambda c=c: one(c)) for c in cases], args.workers, run/'generation_status.json')
    finally:
        await client.close()
        await search.close()


def credential(args, provider, judge):
    return resolve_key(provider, env_name=args.judge_api_key_env if judge else args.api_key_env)


async def judge_and_score(args, run, cases, spec, online):
    folder = run/'judgments'
    freeze(folder/'config.json', spec)
    answers = {c['sample_id']: read_json(answer_path(run, c)) for c in cases if answer_path(run, c).exists()}
    for c in cases:
        if c['sample_id'] in answers:
            check_answer(answers[c['sample_id']], c)
    if not answers:
        raise ValueError('No answers to evaluate')
    freeze_judge_inputs(folder/'inputs.json', {k: digest(v) for k, v in answers.items()}, allow_new_reports=True)
    client = Client(spec['provider'], credential(args, spec['provider'], True), args.timeout,
                    output_ceiling=65536, json_fallback=True) if online else None
    scores, votes = {}, {}
    async def one(case, i, criterion):
        cid = case['sample_id']; text = answers[cid]['text']; path = folder/cid/f'{i:03d}.json'
        # saved_grade validates every cached response/receipt even when offline.
        row = await grade_report(client, spec, args.cache, criterion, text, path)
        votes.setdefault(cid, {})[i] = row['parsed']['score']
    jobs = [(f'{c["sample_id"]}/{i}', lambda c=c, i=i, r=r: one(c, i, r))
            for c in cases if c['sample_id'] in answers for i, r in enumerate(c['rubrics'])]
    try:
        await run_jobs(jobs, args.judge_workers, folder/'status.json')
    finally:
        if client:
            await client.close()
    for case in cases:
        cid = case['sample_id']
        if len(votes.get(cid, {})) == len(case['rubrics']):
            scores[cid] = question_score(case['rubrics'], [votes[cid][i] for i in range(len(case['rubrics']))])
    complete = len(scores) == 101
    result = dict(complete=complete, n_scored=len(scores), questions=101, criteria=2593, judge=spec,
                  question_scores=scores, score=sum(scores.values())/101 if complete else None)
    write_json(run/'results.json', result)
    if not complete:
        raise RuntimeError(f'Only {len(scores)}/101 questions complete; no benchmark score published')
    print(json.dumps(result), flush=True)
    if args.wandb:
        publish(args, run, result)


def publish(args, run, result):
    import wandb
    canonical = result['judge'] == DEFAULT_JUDGE
    suffix = 'researchrubrics' if canonical else 'researchrubrics_'+digest(result['judge'])[:10]
    wb = wandb.init(project=args.wandb_project, entity=args.wandb_entity, id=f'{args.run_id}_{suffix}', name=f'{args.run_id}_{suffix}', resume='allow',
                    config=dict(benchmark='ResearchRubrics original', judge=result['judge'],
                                protocol=read_json(run/'protocol.json'), candidate=read_json(run/'candidate.json'),
                                generation=read_json(run/'generation.json') if (run/'generation.json').exists() else None))
    wb.summary.update({'researchrubrics/score': result['score'], 'researchrubrics/n_scored': 101,
                       'results_sha256': digest(result)})
    artifact = wandb.Artifact(f'{args.run_id}-{suffix}', type='benchmark-results')
    for name in ['results.json', 'protocol.json', 'candidate.json']:
        artifact.add_file(str(run/name), name=name)
    if (run/'generation.json').exists():
        artifact.add_file(str(run/'generation.json'), name='generation.json')
    for name in ['answers', 'judgments', 'research_sessions', 'generation_attempts', 'tool_attempts']:
        if (run/name).exists():
            artifact.add_dir(str(run/name), name=name)
    wb.log_artifact(artifact).wait(); wb.finish()
    remote = wandb.Api().run(f'{wb.entity}/{wb.project}/{wb.id}')
    if remote.summary.get('results_sha256') != digest(result):
        raise RuntimeError('W&B publication not confirmed')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id', required=True)
    p.add_argument('--phase', choices=['all', 'generate', 'import', 'judge', 'score'], default='all')
    p.add_argument('--output', type=Path, default=HERE.parents[3]/'.runs/researchrubrics')
    p.add_argument('--cache', type=Path, default=Path.home()/'.cache/observatorio-maritaca/researchrubrics')
    p.add_argument('--model', default='S5'); p.add_argument('--provider', choices=['maritaca', 'openrouter', 'openai'], default='maritaca')
    p.add_argument('--reasoning-effort', default='xhigh'); p.add_argument('--openrouter-provider')
    p.add_argument('--max-tokens', type=int, default=65536); p.add_argument('--context-length', type=int, default=1000000)
    p.add_argument('--context-reserve', type=int, default=4096, help='Extra context margin, beyond max-tokens; nonnegative, default 4096')
    p.add_argument('--base-url', help='Candidate API base URL; mandatory for openai')
    p.add_argument('--judge-model', default='S5'); p.add_argument('--judge-effort', default='none')
    p.add_argument('--workers', type=int, default=6); p.add_argument('--judge-workers', type=int, default=48)
    p.add_argument('--timeout', type=float, default=3600); p.add_argument('--responses', type=Path)
    p.add_argument('--api-key-env'); p.add_argument('--judge-api-key-env', default='MARITACA_API_KEY')
    p.add_argument('--search-api-key-env', default='SERPER_API_KEY')
    p.add_argument('--wandb', action='store_true'); p.add_argument('--wandb-project'); p.add_argument('--wandb-entity')
    return p


def main():
    p = parser()
    args = p.parse_args()
    if args.wandb and not (args.wandb_entity and args.wandb_project):
        p.error('--wandb requires explicit --wandb-entity and --wandb-project')
    if min(args.workers, args.judge_workers, args.max_tokens) < 1 or args.timeout <= 0:
        raise ValueError('Workers, tokens and timeout must be positive')
    run = args.output.resolve()/safe_name(args.run_id); run.mkdir(parents=True, exist_ok=True)
    lock = (run/'run.lock').open('w'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cases, manifest = load_inputs(args.cache)
    freeze(run/'protocol.json', dict(upstream=manifest, question_count=101, criteria_count=2593,
                                    scoring='Macro mean of signed-weight binary compliance, without clipping'))
    if args.phase in ['all', 'generate', 'import']:
        freeze(run/'candidate.json', dict(model=args.model, provider=args.provider, effort=args.reasoning_effort))
    if args.phase == 'import':
        if not args.responses:
            raise ValueError('--responses is required for import')
        import_answers(run, cases, args.responses)
    if args.phase in ['all', 'generate']:
        asyncio.run(generate(args, run, cases))
    if args.phase in ['all', 'judge', 'score']:
        spec = dict(DEFAULT_JUDGE, model=args.judge_model, effort=args.judge_effort)
        asyncio.run(judge_and_score(args, run, cases, spec, args.phase != 'score'))


if __name__ == '__main__':
    main()
