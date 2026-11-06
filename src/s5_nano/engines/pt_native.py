"""Load the pinned public prompt/scoring definitions without optional harness backends."""
import abc
import ast
import collections
from functools import lru_cache
from enum import Enum
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import string
import sys
import types
from typing import Dict, Iterable, List

import numpy as np
from sklearn.metrics import f1_score

R = Path(__file__).resolve().parent
POETA = R / 'sources/PoETaV2'


def definitions(path, names, scope):
    nodes = []
    found = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            nodes.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            nodes.append(node)
            found.update(t.id for t in node.targets if isinstance(t, ast.Name) and t.id in names)
    assert found == names, (str(path), names-found)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)


def load():
    spec = importlib.util.spec_from_file_location('pt_public_conversation', POETA/'conversation.py')
    conversation = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = conversation
    spec.loader.exec_module(conversation)
    scope = dict(__name__='pt_public_native', abc=abc, abstractmethod=abc.abstractmethod,
        collections=collections, Enum=Enum, Iterable=Iterable, np=np, random=random,
        re=re, os=os, json=json, string=string, f1_score=f1_score,
        mean=lambda values: sum(values)/len(values),
        utils=types.SimpleNamespace(positional_deprecated=lambda fn: fn),
        get_conv_template=conversation.get_conv_template)
    definitions(POETA/'lm_eval/base.py', {'ModelCategory','Task','PromptSelectionTask','MultipleChoicePromptSelectionTask'}, scope)
    definitions(POETA/'lm_eval/tasks/assin.py', {'_manual_examples','ASSIN_RTE','ASSIN_RTE_GREEDY'}, scope)
    definitions(POETA/'lm_eval/tasks/big_bench/bigbench_task_base.py', {'BigBenchJsonTaskBase','BigBenchTaskBaseGreedy'}, scope)
    definitions(POETA/'lm_eval/tasks/big_bench/bigbench_tasks.py', {'BroverbsHistoryToProverbTaskGreedy','BroverbsProverbToHistoryTaskGreedy'}, scope)
    return types.SimpleNamespace(**scope)


@lru_cache(maxsize=1)
def math_functions():
    root = R/'sources/MATH-PT'
    cells = json.loads((root/'create_prompts.ipynb').read_text())['cells']
    scope = dict(Dict=Dict, List=List, re=re, prompt_language='ptbr')
    found = []
    for cell in cells:
        if cell['cell_type'] != 'code': continue
        try: tree = ast.parse(''.join(cell['source']))
        except SyntaxError: continue
        found.extend(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_prompt')
    assert len(found) == 1
    exec(compile(ast.Module(body=found, type_ignores=[]), str(root/'create_prompts.ipynb'), 'exec'), scope)
    grade_cells = json.loads((root/'evaluate-multiple-choice-answers.ipynb').read_text())['cells']
    selected = [''.join(c['source']) for c in grade_cells if c['cell_type']=='code'
                and 'm = re.search' in ''.join(c['source']) and "response['final_answer']" in ''.join(c['source'])]
    assert len(selected) == 1
    code = compile(selected[0], str(root/'evaluate-multiple-choice-answers.ipynb'), 'exec')

    def extract(text):
        responses = {'candidate': [{'raw_response': {'choice.message.content': text}}]}
        exec(code, dict(models=['candidate'], responses=responses))
        return responses['candidate'][0]['final_answer']
    return scope['build_prompt'], extract


def score_case(task, row, text, native):
    if task == 'math_pt_br_mc':
        _, extract = math_functions()
        prediction = extract(text)
        return dict(correct=prediction is not None and prediction.strip().upper()==row['doc']['answer'].strip().upper(),
                    prediction=prediction, gold=row['doc']['answer'], level=row['doc']['level'])
    if task == 'broverbs':
        obj = object.__new__(native.BigBenchTaskBaseGreedy)
        result = obj.process_results(row['doc'], [text])
        return dict(correct=bool(result['acc']), direction=row['direction'], **result)
    if task == 'assin_rte':
        obj = object.__new__(native.ASSIN_RTE_GREEDY)
        return obj.process_results(row['doc'], [text])
    raise ValueError(task)


def aggregate(task, rows, native):
    if task == 'math_pt_br_mc':
        correct = sum(x['correct'] for x in rows)
        levels = {}
        for level in sorted({x['level'] for x in rows}):
            selected = [x for x in rows if x['level']==level]
            levels[str(level)] = dict(n=len(selected), correct=sum(x['correct'] for x in selected),
                                     accuracy=100*sum(x['correct'] for x in selected)/len(selected))
        return dict(score=100*correct/len(rows), correct=correct, metric_name='accuracy_percent', by_level=levels)
    if task == 'broverbs':
        modes = {}
        for direction in ('history_to_proverb', 'proverb_to_history'):
            selected = [x for x in rows if x['direction']==direction]
            modes[direction] = dict(n=len(selected), correct=sum(x['correct'] for x in selected),
                                    score=100*sum(x['correct'] for x in selected)/len(selected))
        return dict(score=sum(v['score'] for v in modes.values())/2, metric_name='mean_direction_accuracy_percent',
                    directions=modes, correct=sum(x['correct'] for x in rows))
    if task == 'assin_rte':
        return dict(score=native.ASSIN_RTE_GREEDY.macro_f1([x['f1'] for x in rows]), metric_name='macro_f1_percent',
                    accuracy=sum(x['acc'] for x in rows)/len(rows),
                    unknown_predictions=sum(x['f1'][0] not in ('sim','não') for x in rows))
    raise ValueError(task)
