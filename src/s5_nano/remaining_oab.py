"""Native OAB generation conversation, structured judge and exam aggregation."""
from collections import defaultdict
import dataclasses
import importlib.util
import json
import os
import re
import sys
import time
from typing import List

import openai
from pydantic import BaseModel, Field

from .remaining_core import definitions, digest, save


def evaluate(run, preflight=False):
    if run.task in {'oab_bench_full', 'oab_bench_3941'}:
        from .remaining_legal import evaluate as legal
        return legal(run, preflight)
    source = run.root / 'sources'
    spec = importlib.util.spec_from_file_location('oab_conversation', source / 'conversation.py')
    conv = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = conv
    spec.loader.exec_module(conv)
    names = ['API_MAX_RETRY', 'API_RETRY_SLEEP', 'API_ERROR_OUTPUT', 'OAB_CATS', 'temperature_config',
             'ItemEvaluation', 'JudgmentResult', 'Judge', 'MatchSingle', '_turn_content',
             'run_judge_single_structured', 'play_a_match_single', 'chat_completion_openai_structured']
    native = definitions(source / 'common.py', names, dict(dataclasses=dataclasses, BaseModel=BaseModel,
        Field=Field, List=List, re=re, os=os, json=json, time=time, openai=openai,
        get_conversation_template=conv.get_conv_template))
    matches = definitions(source / 'gen_judgment.py', ['make_match_single', 'make_judge_single'],
                          dict(Judge=native.Judge, MatchSingle=native.MatchSingle, OAB_CATS=native.OAB_CATS))
    prompts = {r['name']: r for r in map(json.loads, (run.root / 'inputs/data/judge_prompts.jsonl').open())}
    references = {r['question_id']: r for r in map(json.loads,
        (run.root / 'inputs/data/oab_bench/reference_answer/guidelines.jsonl').open())}
    judge = matches.make_judge_single('gpt-5.2', prompts)['oab-structured']
    exams = defaultdict(list)
    for row in run.rows:
        exams['_'.join(row['question_id'].split('_')[:-2])].append(row)
    expected = run.manifest['protocol']['selection']['selected_rows']
    if (expected not in (105, 210) or len(run.rows) != expected or len(exams) != expected // 5
            or any(len(v) != 5 or abs(sum(sum(r['values']) for r in v)-10) > 1e-6 for v in exams.values())):
        raise ValueError('OAB selection must contain complete exam/area blocks')
    def make_match(row, turns):
        answer = dict(answer_id=digest([run.identity, row['question_id']]), choices=[dict(index=0, turns=turns)])
        return matches.make_match_single([row], [run.identity['model']],
            {run.identity['model']: {row['question_id']: answer}}, judge,
            ref_answers={'guidelines': references})[0]
    if preflight:
        for row in run.rows:
            match = make_match(row, ['Synthetic answer'] * len(row['turns']))
            assert len(match.question['turns']) == len(match.answer['choices'][0]['turns']) == 1
            assert match.question['values'][0] == sum(row['values'])
        save(run.out / 'preflight.json', dict(passed=True, n=expected, complete_exams=len(exams), model_or_judge_calls=0))
        return
    def one(row):
        conversation = conv.get_conv_template('chatgpt')
        if 'system' in row:
            conversation.set_system_message(row['system'])
        turns = []
        for index, question in enumerate(row['turns']):
            if index == 0 and 'statement' in row:
                question = row['statement'] + '\n' + question
            conversation.append_message(conversation.roles[0], question)
            conversation.append_message(conversation.roles[1], None)
            answer = run.ask(row['question_id'], conversation.to_openai_api_messages(), turn=index,
                temperature=row.get('required_temperature', native.temperature_config.get(row['category'], .7)),
                max_tokens=1024)
            conversation.update_last_message(answer['final'])
            turns.append(dict(content=answer['final'], usage=(answer.get('raw') or {}).get('usage')))
        match = make_match(row, turns)
        details = dict(question=match.question, turns=turns, reference=match.ref_answer, judge=run.manifest['protocol']['judge'])
        result = run.judgment(row['question_id'], details,
            lambda: native.play_a_match_single(match, output_file=None, client=run.paid_client()),
            lambda x: type(x.get('score')) in (int, float) and 0 <= x['score'] <= sum(row['values']),
            required_model='gpt-5.2')
        return result
    rows = run.parallel(one)
    totals = {key: sum(row['score'] for row in rows if '_'.join(row['question_id'].split('_')[:-2]) == key) for key in exams}
    raw_score = sum(totals.values()) / len(totals)
    run.finish(dict(score=raw_score * 10, native_score_out_of_10=raw_score,
        exam_scores=totals, approved_exams=sum(v >= 6 for v in totals.values()), complete_exams=len(exams),
        metric_name='native_mean_exam_score', judge='gpt-5.2', judge_reasoning_effort='high'), rows)
