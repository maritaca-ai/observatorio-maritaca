"""Pinned native MAGIS/OAB-full protocols with independent GPU and judge phases."""
from collections import defaultdict
import copy
import dataclasses
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
from typing import List

import openai
from pydantic import BaseModel, Field

from .auditing import OpenAI
from .remaining_core import definitions, digest, save

TASKS = {'magis_bench': ('magis_bench', 'MAGIS_CATS', 74, 24, 'anthropic/claude-opus-4.6'),
         'oab_bench_full': ('oab_bench', 'OAB_CATS', 210, 42, 'gpt-5.2'),
         'oab_bench_3941': ('oab_bench', 'OAB_CATS', 105, 21, 'gpt-5.2')}


def load_native(root, task):
    dataset, cats, _, _, model = TASKS[task]
    source = Path(root) / 'sources'
    spec = importlib.util.spec_from_file_location('legal_conversation_' + task, source / 'conversation.py')
    conv = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = conv
    spec.loader.exec_module(conv)
    names = ['API_MAX_RETRY', 'API_RETRY_SLEEP', 'API_ERROR_OUTPUT', cats, 'temperature_config',
             'ItemEvaluation', 'JudgmentResult', 'Judge', 'MatchSingle', '_turn_content',
             'run_judge_single_structured', 'play_a_match_single', 'chat_completion_openai_structured']
    native = definitions(source / 'common.py', names, dict(dataclasses=dataclasses, BaseModel=BaseModel,
        Field=Field, List=List, re=re, os=os, json=json, time=time, openai=openai,
        get_conversation_template=conv.get_conv_template))
    # Operational fail-stop: no native/SDK retry may repeat an uncertain HTTP call.
    native.API_MAX_RETRY = 1
    matches = definitions(source / 'gen_judgment.py', ['make_match_single', 'make_judge_single'],
        dict(Judge=native.Judge, MatchSingle=native.MatchSingle, **{cats: getattr(native, cats)}))
    prompts = {r['name']: r for r in map(json.loads, (Path(root) / 'inputs/data/judge_prompts.jsonl').open())}
    references = {r['question_id']: r for r in map(json.loads,
        (Path(root) / f'inputs/data/{dataset}/reference_answer/guidelines.jsonl').open())}
    judge = matches.make_judge_single(model, prompts)[dataset.split('_')[0] + '-structured']
    return conv, native, matches, references, judge


def conversation_requests(conv, native, row, task, ask):
    """Mirror the original CLI preprocessing AND the sequential answer loop."""
    conversation = conv.get_conv_template('chatgpt')
    if 'system' in row:
        conversation.set_system_message(row['system'])
    turns = []
    for index, text in enumerate(row['turns']):
        if index == 0:
            if 'statement' in row:
                text = row['statement'] + '\n' + text
            if task == 'magis_bench' and 'rows' in row:
                text += f"\n\nMáximo de {row['rows']} linhas."
        conversation.append_message(conversation.roles[0], text)
        conversation.append_message(conversation.roles[1], None)
        # The campaign proxy enforces the explicit profile, including null output
        # cap; these OAB request defaults also preserve historical cache identity.
        answer = ask(row['question_id'], conversation.to_openai_api_messages(), turn=index,
            temperature=row.get('required_temperature', native.temperature_config.get(row['category'], .7)),
            max_tokens=1024 if task != 'magis_bench' else None)
        conversation.update_last_message(answer['final'])
        turns.append(dict(content=answer['final'], usage=(answer.get('raw') or {}).get('usage')))
    return turns


def judge_client(run):
    if run.judge_client is None:
        if run.task == 'magis_bench':
            run.judge_client = OpenAI(base_url='https://openrouter.ai/api/v1',
                api_key=os.environ['OPENROUTER_API_KEY'], max_retries=0, timeout=1800)
        else:
            run.paid_client()
    def parse(**kwargs):
        try:
            result = run.judge_client.beta.chat.completions.parse(**kwargs)
            if not result.choices:
                raise ValueError('Judge returned no choices')
            return result
        except Exception as exc:
            # Native functions catch OpenAIError/TypeError and retry. Escaping as
            # RuntimeError lets Run.judgment preserve the attempt and stop.
            raise RuntimeError('Legal judge call failed; audit required') from exc
    return SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))))


def evaluate(run, preflight=False):
    phase = os.environ.get('S5_NANO_LEGAL_PHASE', 'all')
    if phase not in {'all', 'generate', 'judge'}:
        raise ValueError('Unknown legal phase')
    dataset, _, count, sections, model = TASKS[run.task]
    conv, native, matches, references, judge = load_native(run.root, run.task)
    exams = defaultdict(list)
    for row in run.rows:
        exams['_'.join(row['question_id'].split('_')[:-2])].append(row)
    if (len(run.rows) != count or len({r['question_id'] for r in run.rows}) != count or
            len(exams) != sections or any(abs(sum(sum(r['values']) for r in v) - 10) > 1e-6 for v in exams.values())):
        raise ValueError('Legal population or exam sections changed')
    def make_match(row, turns):
        answer = dict(answer_id=digest([run.identity, row['question_id']]), choices=[dict(index=0, turns=turns)])
        return matches.make_match_single([row], [run.identity['model']],
            {run.identity['model']: {row['question_id']: answer}}, judge,
            ref_answers={'guidelines': references})[0]
    if preflight:
        for row in run.rows:
            requests = []
            def synthetic(identifier, messages, **kwargs):
                requests.append(copy.deepcopy(messages))
                return dict(final='Synthetic answer', raw={})
            turns = conversation_requests(conv, native, row, run.task, synthetic)
            match = make_match(row, turns)
            assert len(requests) == len(row['turns'])
            assert row['statement'] in requests[0][-1]['content']
            assert len(match.question['turns']) == len(match.answer['choices'][0]['turns']) == 1
            assert match.question['values'][0] == sum(row['values'])
        save(run.out / 'preflight.json', dict(passed=True, n=count, complete_exams=sections,
            generation_turns=sum(len(r['turns']) for r in run.rows), model_or_judge_calls=0,
            context_validation='requires model tokenizer and actual generated history'))
        return
    if phase == 'judge':
        receipt = json.loads((run.out / 'generation_ready.json').read_text())
        if receipt['identity'] != run.identity or receipt['n'] != count:
            raise ValueError('Generation identity or population differs')
        for relative, expected in receipt['files'].items():
            from .prepare import sha
            if sha(run.out / relative) != expected:
                raise ValueError('Frozen generation changed')
    def ask(identifier, messages, **options):
        if phase == 'judge':
            from .model_identity import expected_model
            request = dict(model=expected_model(run.identity), messages=messages, **options)
            turn = request.pop('turn', 0)
            key = digest(dict(case=str(identifier), turn=turn, request=request, run=run.identity))
            if not (run.out / 'responses' / (key + '.json')).exists():
                raise RuntimeError('Judge-only requires every saved candidate; generation forbidden')
        answer = run.ask(identifier, messages, **options)
        if answer.get('model_context_exhausted'):
            raise RuntimeError('Candidate exceeded approved context; preserved as pending, not scored')
        return answer
    # Verify all frozen turn identities before making ANY paid judgment.
    if phase == 'judge':
        for row in run.rows:
            conversation_requests(conv, native, row, run.task, ask)
    def one(row):
        turns = conversation_requests(conv, native, row, run.task, ask)
        if phase == 'generate':
            return dict(question_id=row['question_id'], turns=len(turns))
        match = make_match(row, turns)
        details = dict(question=match.question, turns=turns, reference=match.ref_answer,
                       judge=run.manifest['protocol']['judge'])
        return run.judgment(row['question_id'], details,
            lambda: native.play_a_match_single(match, output_file=None, client=judge_client(run)),
            lambda x: type(x.get('score')) in (int, float) and math.isfinite(x['score'])
                and 0 <= x['score'] <= sum(row['values']), required_model=model)
    if phase != 'generate':
        judge_client(run)
    rows = run.parallel(one)
    if phase == 'generate':
        from .prepare import sha
        files = {str(p.relative_to(run.out)): sha(p) for p in sorted((run.out / 'responses').glob('*.json'))}
        if len(files) != sum(len(r['turns']) for r in run.rows):
            raise ValueError('Incomplete generated turn population')
        save(run.out / 'generation_ready.json', dict(status='GENERATION_COMPLETE', identity=run.identity,
            n=count, turns=len(files), files=files, judge_calls=0))
        return
    totals = {key: sum(r['score'] for r in rows if '_'.join(r['question_id'].split('_')[:-2]) == key) for key in exams}
    raw_score = sum(totals.values()) / sections
    run.finish(dict(score=raw_score * 10, native_score_out_of_10=raw_score,
        exam_scores=totals, approved_exams=sum(v >= 6 for v in totals.values()), complete_exams=sections,
        metric_name='native_mean_exam_section_score' if run.task == 'magis_bench' else 'native_mean_exam_score',
        judge=model, judge_reasoning_effort='high'), rows)
