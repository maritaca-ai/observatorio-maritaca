"""Native LongBench-v2 full-context evaluation."""
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace


from .remaining_core import definitions, digest, save
from .runtime_config import PROFILE
from .longbench_context import input_budget, render_native_context




def longbench(run, preflight=False):
    native = definitions(run.root / 'sources/pred.py', ['query_llm', 'extract_answer'], dict(re=re, time=time))
    template = (run.root / 'inputs/prompts/0shot.txt').read_text()
    if len(run.rows) != 503:
        raise ValueError('LongBench v2 population changed')
    assert native.extract_answer('The correct answer is (D)') == 'D'
    assert native.extract_answer('D') is None
    assert all(key in template for key in ('$DOC$', '$Q$', '$C_A$', '$C_B$', '$C_C$', '$C_D$'))
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(os.environ['S5_NANO_TOKENIZER'], local_files_only=True)
    template_path = Path(os.environ['S5_NANO_CHAT_TEMPLATE'])
    tokenizer.chat_template = template_path.read_text()
    expected_template = PROFILE.get('chat_template_sha256')
    if expected_template:
        import hashlib
        if hashlib.sha256(template_path.read_bytes()).hexdigest() != expected_template:
            raise ValueError('LongBench chat template differs from the pinned profile')
    budget = input_budget(PROFILE, run.manifest['protocol']['context_policy'])
    prepared, evidence = {}, []
    # Validate the entire fixed population before any candidate dispatch.
    for row in run.rows:
        if row['_id'] in prepared:
            raise ValueError('LongBench duplicate case identity')
        prompt = template.replace('$DOC$', row['context'].strip()).replace('$Q$', row['question'].strip())
        for letter in 'ABCD':
            prompt = prompt.replace('$C_' + letter + '$', row['choice_' + letter].strip())
        request, context = render_native_context(native, prompt, tokenizer,
                                                run.identity['model'], PROFILE, budget)
        prepared[row['_id']] = (request, context)
        evidence.append(dict(id=row['_id'], **context))
    save(run.out / 'context_preflight_rows.json', evidence)
    save(run.out / 'context_policy.json', dict(passed=True, n=503, input_budget_tokens=budget,
        context_length=PROFILE['context_length'], max_tokens=PROFILE['max_tokens'],
        effective_prompt_tokens_max=max(r['effective_prompt_tokens'] for r in evidence),
        generation_space_min=min(r['generation_space'] for r in evidence),
        profile_sha256=digest(PROFILE), tokenizer_revision=PROFILE.get('revision'),
        method='native_middle_truncation', model_or_judge_calls=0))
    if preflight:
        save(run.out / 'preflight.json', dict(passed=True, n=503, model_or_judge_calls=0,
            all_serialized_contexts_validated=True))
        return
    def one(row):
        expected_request, context = prepared[row['_id']]
        prompt = template.replace('$DOC$', row['context'].strip()).replace('$Q$', row['question'].strip())
        for letter in 'ABCD':
            prompt = prompt.replace('$C_' + letter + '$', row['choice_' + letter].strip())
        errors = []
        def create(**request):
            try:
                if request != expected_request:
                    raise ValueError('LongBench request differs from offline preflight')
                response = run.ask(row['_id'], request['messages'], temperature=request['temperature'],
                                   max_tokens=request['max_tokens'])
            except Exception as exc:
                errors.append(exc)
                raise
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response['final']))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        # Preserve the historical native transport/retry behavior in this fix.
        final = native.query_llm(prompt, run.identity['model'], tokenizer, client,
                                 temperature=.1, max_new_tokens=128)
        if errors and final == '':
            raise errors[-1]
        answer = native.extract_answer(final.strip())
        return dict(id=row['_id'], prediction=answer, correct=answer == row['answer'],
                    **context, difficulty=row['difficulty'], length=row['length'])
    rows = run.parallel(one)
    slices = {}
    for field in ('difficulty', 'length'):
        slices[field] = {value: dict(n=len(group), score=100 * sum(r['correct'] for r in group) / len(group))
                        for value in sorted({r[field] for r in rows})
                        if (group := [r for r in rows if r[field] == value])}
    run.finish(dict(score=100 * sum(r['correct'] for r in rows) / 503, metric_name='accuracy',
                    truncated_cases=sum(r['truncated'] for r in rows), slices=slices, external_api_cost_usd=0), rows)
