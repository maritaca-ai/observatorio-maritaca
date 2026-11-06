"""Public Prosa with its frozen filter and native valid-verdict aggregation."""
import concurrent.futures
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

from s5_nano.auditing import OpenAI
from s5_nano.runtime_config import POLICY, THINKING, WORKERS, MAX_TOKENS, PROFILE

R = Path(__file__).resolve().parent
TASK = 'prosa_pt'
AGGREGATION = 'native_first_judgment_valid_verdicts_v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def native(source):
    sys.path.insert(0, str(source / 'Prosa-benchmark'))
    return tuple(importlib.import_module('prosa.' + name)
                 for name in ['gen_score', 'show_score', 'conversation', 'prosa_utils'])


def messages(question, conversation):
    conv = conversation.get_conv_template('zero_shot')
    for item in question['conversation_input']:
        assert item['role'] in ('user', 'assistant')
        conv.append_message(conv.roles[item['role'] == 'assistant'], item['content'])
    rendered = conv.to_openai_api_messages()
    assert rendered[1:] == question['conversation_input']
    return rendered


def validate_questions(questions, grading, conversation):
    assert len(questions) == 1000
    assert len({q['conversation_hash'] for q in questions}) == 1000
    included = []
    for q in questions:
        assert q['conversation_input'][-1]['role'] == 'user'
        assert q['conversation_input'][-1]['content'] == q['last_query']
        messages(q, conversation)
        rubrics = grading.parse_checklist(q['checklist'])
        indices = q['checklist_filtered_indices']
        assert len(indices) == len(set(indices))
        assert all(type(i) is int and 0 <= i < len(rubrics) for i in indices)
        if not q['question_excluded']:
            assert indices
            included.append(q)
    assert len(included) == 981
    assert sum(len(q['checklist_filtered_indices']) for q in included) == 8408
    return included


def aggregate(questions, entries, scoring):
    expected = {q['conversation_hash']: q for q in questions if not q['question_excluded']}
    assert len(entries) == len(expected)
    assert {e['conversation_hash'] for e in entries} == set(expected)
    grouped = {('candidate', 'judge'): json.loads(json.dumps(entries))}
    scoring.recompute_filtered_scores(grouped, {q['conversation_hash']: q for q in questions})
    filtered = grouped[('candidate', 'judge')]
    total = sum(e['n_valid'] for e in filtered)
    passed = sum(e['n_passed'] for e in filtered)
    denominator = sum(len(q['checklist_filtered_indices']) for q in expected.values())
    assert 0 < total <= denominator, 'No valid selected verdicts: native score is undefined'
    micro = scoring.adjusted(scoring.micro_mean(filtered))
    macro = scoring.adjusted(scoring.macro_mean(filtered))
    valid_conversations = [e for e in filtered if e['n_valid']]
    assert abs(micro - 100 * passed / total) < 1e-10
    assert abs(macro - sum(100 * e['n_passed'] / e['n_valid'] for e in valid_conversations) / len(valid_conversations)) < 1e-10
    return dict(score=micro, macro_score=macro, n=len(filtered), passed_rubrics=passed,
                scored_rubrics=total, eligible_rubrics=denominator,
                missing_verdicts=denominator-total, rubric_coverage=total/denominator,
                valid_conversations=len(valid_conversations), aggregation_policy=AGGREGATION,
                metric_name='micro_filtered_rubric_pass_rate_percent')


def judgment(question, answer, grading, client, out, protocol):
    identifier = question['conversation_hash']
    rubrics = grading.parse_checklist(question['checklist'])
    prompt = grading.build_score_rubric_prompt(question.get('history_text', ''),
        question['last_query'], answer['content'], rubrics)
    args = dict(model=protocol['judge'], messages=[dict(role='user', content=prompt)],
                temperature=protocol['judge_temperature'], max_tokens=protocol['judge_max_tokens'], n=1)
    signature = digest(args)
    path = out / 'judgments' / (identifier + '.json')
    if path.exists():
        value = json.loads(path.read_text())
        assert value['request_sha256'] == signature
        assert value.get('aggregation_policy') == AGGREGATION, 'Rescore old judgments into a new run'
        return value
    for attempt in range(3):
        raw_path = out / 'judge_raw' / identifier / (str(attempt) + '.json')
        if raw_path.exists():
            receipt = json.loads(raw_path.read_text())
            assert receipt['request_sha256'] == signature
        else:
            try:
                raw = client.chat.completions.create(**args).model_dump(mode='json')
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
                continue
            receipt = dict(request_sha256=signature, request=args, raw=raw)
            save(raw_path, receipt)
        text = receipt['raw']['choices'][0]['message'].get('content') or ''
        evaluations = grading.parse_evaluations(text, len(rubrics))
        value = dict(conversation_hash=identifier, evaluations=evaluations,
                     request_sha256=signature, aggregation_policy=AGGREGATION,
                     judge_attempt=attempt, **grading.compute_score(evaluations))
        save(path, value)
        return value


def main():
    os.umask(0o077)
    out = Path(os.environ['S5_NANO_RESULT_DIR']) / TASK
    out.mkdir(parents=True, exist_ok=True)
    inputs = Path(os.environ.get('S5_NANO_PROSA_INPUTS', str(R)))
    source = inputs / 'sources/Prosa'
    manifest = json.loads((inputs / 'manifest.json').read_text())
    body = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
    assert hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() == manifest['manifest_sha256']
    for name, checksum in manifest['files'].items():
        assert hashlib.sha256((source / name).read_bytes()).hexdigest() == checksum, name
    grading, scoring, conversation, loaders = native(source)
    questions = loaders.load_prosa_questions(str(source / 'Prosa-benchmark/prosa/data/prosa/question.jsonl'))
    included = validate_questions(questions, grading, conversation)
    protocol = json.loads((R/'run_manifest.json').read_text())['benchmark']['protocol']
    for name in ['judge','judge_temperature','judge_max_tokens','judge_reasoning_effort']:
        assert protocol[name] == manifest['protocol'][name], 'Judge parameters changed'
    if '--preflight' in sys.argv:
        golden = [dict(conversation_hash=q['conversation_hash'],
                       evaluations=['YES'] * len(grading.parse_checklist(q['checklist']))) for q in included]
        result = aggregate(questions, golden, scoring)
        assert result['score'] == result['macro_score'] == 100
        save(out / 'preflight.json', dict(passed=True, time=time.time(), n=1000,
             scored_conversations=981, filtered_rubrics=8408, native_messages_verified=True,
             golden_score=100, model_or_judge_calls=0))
        return
    with (out / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        model = os.environ['S5_NANO_MODEL']
        identity = dict(model=model, policy=POLICY, thinking=THINKING, max_tokens=MAX_TOKENS,
                        manifest_sha256=manifest['manifest_sha256'],
                        worker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        frozen = out / 'run_identity.json'
        if frozen.exists():
            assert json.loads(frozen.read_text()) == identity, 'Run identity changed'
        else:
            save(frozen, identity)
        if (out / 'verified.json').exists():
            return
        save(out / 'started.json', dict(time=time.time(), pid=os.getpid(), thinking=THINKING, n=1000))
        candidate = OpenAI(base_url=os.environ['S5_NANO_PROXY_URL'] + '/' + TASK + '/v1',
            api_key=os.environ.get('S5_NANO_MODEL_API_KEY', ''), timeout=21600, max_retries=2)
        judge = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=1800, max_retries=2)

        def one(q):
            path = out / 'responses' / (q['conversation_hash'] + '.json')
            msg = messages(q, conversation)
            request_hash = digest(dict(messages=msg, **identity))
            if path.exists():
                answer = json.loads(path.read_text())
                assert answer['request_sha256'] == request_hash
            else:
                params = dict(POLICY)
                temperature, top_p = params.pop('temperature'), params.pop('top_p')
                raw = candidate.chat.completions.create(model=model, messages=msg,
                    temperature=temperature, top_p=top_p, max_tokens=MAX_TOKENS, n=1,
                    extra_body=dict(params, chat_template_kwargs={'enable_thinking': THINKING})).model_dump(mode='json')
                choice = raw['choices'][0]
                answer = dict(conversation_hash=q['conversation_hash'], request_sha256=request_hash,
                    content=choice['message'].get('content') or '', finish_reason=choice['finish_reason'], raw=raw)
                save(path, answer)
            message = answer['raw']['choices'][0]['message']
            reasoning = message.get('reasoning') or message.get('reasoning_content') or ''
            entry = None if q['question_excluded'] else judgment(q, answer, grading, judge, out, protocol)
            return dict(id=q['conversation_hash'], entry=entry, empty_final=not answer['content'].strip(),
                        truncated=answer['finish_reason'] == 'length', reasoning_present=bool(reasoning))

        rows = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for future in concurrent.futures.as_completed([pool.submit(one, q) for q in questions]):
                rows.append(future.result())
                save(out / 'progress.json', dict(time=time.time(), completed=len(rows), expected=1000))
        assert len(rows) == 1000 and {x['id'] for x in rows} == {q['conversation_hash'] for q in questions}
        metric = aggregate(questions, [x['entry'] for x in rows if x['entry'] is not None], scoring)
        checked = 0
        with (R / 'effective_requests_secondary.jsonl').open() as stream:
            for line in stream:
                audit = json.loads(line)
                if audit.get('status') != 'forwarding' or audit.get('benchmark') != TASK:
                    continue
                assert all(audit['applied'][k] == v for k, v in POLICY.items())
                assert audit['applied']['enable_thinking'] is THINKING
                assert audit['applied']['max_tokens'] == MAX_TOKENS and audit['applied']['stop'] == PROFILE.get('generation_stop')
                assert audit['native_budget_fields'].get('reasoning_effort') is None
                checked += 1
        assert checked >= 1000
        metric.update(status='FINAL', generated_n=1000, fixed_excluded_n=19, judge=protocol['judge'],
            judge_errors=0, empty_final=sum(r['empty_final'] for r in rows),
            truncated=sum(r['truncated'] for r in rows), reasoning_responses=sum(r['reasoning_present'] for r in rows),
            audited_requests=checked, protocol=protocol, public_benchmark_sources=True,
            sources={'Prosa': manifest['source']})
        save(out / 'scored_rows.json', rows)
        save(out / 'verified.json', dict(passed=True, time=time.time(), metric=metric, thinking=THINKING,
             all_requests_checked=True, final_answers_only=True, independent_aggregation_checked=True,
             items_sha256=manifest['manifest_sha256'], label='Prosa-PT · rubricas filtradas · micro',
             lumi_reference=None, comparison_note='Official frozen rubric filter; GPT-4.1 judge; campaign sampling. Macro also reported.'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        save(Path(os.environ['S5_NANO_RESULT_DIR']) / TASK / 'failure.json',
             dict(time=time.time(), error_type=type(exc).__name__, detail=str(exc)[-500:]))
        raise
