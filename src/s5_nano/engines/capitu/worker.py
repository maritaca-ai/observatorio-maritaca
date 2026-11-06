from s5_nano.runtime_config import POLICY, THINKING, WORKERS, MAX_TOKENS
"""CAPITU native generation/scoring, with durable turns and the modelo candidato preset."""
import concurrent.futures, dataclasses, fcntl, hashlib, json, os, sys, time, traceback
from pathlib import Path

R = Path(__file__).resolve().parent
CAMPAIGN = R.parent
SOURCE = R/'sources/capitu'
OUT = Path(os.environ['S5_NANO_RESULT_DIR'])/'capitu'
os.environ.setdefault('NLTK_DATA',str(R/'nltk_data'))
sys.path.insert(0, str(SOURCE))
import generate_responses as native_gen
import run_eval as native_eval
import evaluation_lib
from metrics import save_report_json
from s5_nano.auditing import OpenAI
from s5_nano.context_failures import POLICY_ID, is_context_limit_response
from s5_nano.runtime_config import PROFILE

MODEL = os.environ['S5_NANO_MODEL']
BASE = os.environ['S5_NANO_PROXY_URL']+'/capitu/v1'

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class DurableModel(native_gen.AssistantModel):
    def __init__(self, split, key):
        super().__init__(MODEL, BASE, os.environ.get('S5_NANO_MODEL_API_KEY',''))
        self.client = OpenAI(base_url=BASE, api_key=os.environ.get('S5_NANO_MODEL_API_KEY',''), timeout=21600, max_retries=2,
                             default_headers={'X-S5-Nano-Conversation-Id':f'capitu:{split}:{key}'})
        self.turn_root = OUT / 'turns' / split / str(key)
        self.turn_index = 0
        self.context_failure = None
        self.unanswered_turns = []

    def generate_response(self, messages, **kwargs):
        signature = hashlib.sha256(json.dumps({'messages': messages, 'system': self.system_prompt}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.turn_root / f'{self.turn_index + 1}.json'
        if path.exists():
            value = json.loads(path.read_text())
            assert value['signature'] == signature, 'Saved turn prompt changed'
        else:
            if self.context_failure:
                value = dict(signature=signature, content='', usage={}, time=time.time(),
                             generated=False, context_failure=self.context_failure,
                             not_attempted_reason='blocked_by_prior_context_limit')
            else:
                try:
                    content, usage = super().generate_response(messages, **kwargs)
                    value = dict(signature=signature, content=content or '', usage=usage, time=time.time(), generated=True)
                except Exception as exc:
                    if not is_context_limit_response(getattr(exc,'status_code',None),getattr(exc,'body',None),PROFILE['context_length']):
                        raise
                    failure=dict(policy=POLICY_ID,type='model_context_limit',body=exc.body)
                    value=dict(signature=signature,content='',usage={},time=time.time(),generated=False,context_failure=failure)
            save(path, value)
        if value.get('context_failure'):
            self.context_failure=value['context_failure'];self.unanswered_turns.append(self.turn_index+1)
        self.turn_index += 1
        return value['content'], value['usage']

def questions():
    manifest = json.loads((R / 'manifest.json').read_text())
    for name, expected in manifest['source_hashes'].items():
        assert sha(SOURCE / name) == expected, 'CAPITU source or data changed: ' + name
    single = native_gen.read_questions(str(SOURCE / 'data/input_questions.jsonl'))
    multi = native_gen.read_questions(str(SOURCE / 'data/input_questions_multiturn.jsonl'))
    assert len(single) == len({q['key'] for q in single}) == 200
    assert len(multi) == len({q['key'] for q in multi}) == 100
    assert all(len(q['turns']) == 3 for q in multi)
    return single, multi, manifest

def generate(split, q):
    path = OUT / 'responses' / f'{split}_{q["key"]}.json'
    if path.exists():
        return json.loads(path.read_text())
    model = DurableModel(split, q['key'])
    generator = native_gen.ResponseGenerator(model, MODEL)
    record = generator.generate_single_turn(q) if split == 'single' else generator.generate_multi_turn(q)
    value = dataclasses.asdict(record)
    if model.context_failure:
        value.update(model_context_failure=model.context_failure,unanswered_turns=model.unanswered_turns)
    if split == 'multi':
        assert len(value['turns']) == 3
    save(path, value)
    return value

def score(single, multi, records, target):
    target.mkdir(parents=True, exist_ok=True)
    reports = {}
    for split, qs in [('single', single), ('multi', multi)]:
        output = target / split
        output.mkdir(exist_ok=True)
        by_key = records[split]
        assert set(by_key) == {q['key'] for q in qs}
        if split == 'multi':
            assert all(len(by_key[q['key']]['turns']) == len(q['turns']) == 3 for q in qs)
        response_file = output / 'responses.jsonl'
        response_file.write_text(''.join(json.dumps(by_key[q['key']], ensure_ascii=False) + '\n' for q in qs))
        name = 'input_questions.jsonl' if split == 'single' else 'input_questions_multiturn.jsonl'
        cfg = native_eval.EvalConfig(input_data=str(SOURCE / 'data' / name), input_response_data=str(response_file), output_dir=str(output), book_context_path=str(SOURCE / 'data/book_context.json'), verbose=False)
        if split == 'single':
            book = evaluation_lib.load_book_context(cfg.book_context_path)
            report, strict, loose, scored = native_eval.evaluate_single_turn(qs, by_key, cfg, book, None, None, None)
            assert len(strict) == len(loose) == len(scored) == 200
            assert report.overall.prompts_all_correct == sum(x.follow_all_instructions for x in strict)
        else:
            report, results = native_eval.evaluate_multi_turn(qs, by_key, cfg)
            assert len(results) == 100 and all(len(x['turns']) == 3 for x in results)
            assert report.overall.prompts_all_correct == sum(x['all_instructions_followed'] for x in results)
        assert report.overall.total_prompts == len(qs)
        assert abs(report.overall.strict_accuracy - report.overall.prompts_all_correct / len(qs)) < 1e-12
        save_report_json(report, output / 'metrics_report.json')
        reports[split] = dataclasses.asdict(report)
        failed={q['key'] for q in qs if by_key[q['key']].get('model_context_failure')}
        successful=[x.follow_all_instructions for x in strict] if split=='single' else [x['all_instructions_followed'] for x in results]
        adjusted=sum(bool(passed) and q['key'] not in failed for q,passed in zip(qs,successful))
        reports[split]['context_failure_adjustment']=dict(policy=POLICY_ID,failed_cases=len(failed),correct=adjusted,n=len(qs),score=100*adjusted/len(qs))
    return reports

def main():
    os.umask(0o077)
    OUT.mkdir(parents=True, exist_ok=True)
    single, multi, manifest = questions()
    if '--preflight' in sys.argv:
        # Exercise every native checker and both full denominators, without model calls.
        fake = {'single': {q['key']: dict(key=q['key'], prompt=q['prompt'], response='', model_name=MODEL) for q in single},
                'multi': {q['key']: dict(key=q['key'], turns=[dict(turn=t['turn'], response='') for t in q['turns']], model_name=MODEL) for q in multi}}
        reports = score(single, multi, fake, R / 'preflight_outputs')
        assert reports['single']['overall']['strict_accuracy'] == 0
        assert reports['multi']['overall']['strict_accuracy'] == 0
        save(OUT / 'preflight.json', dict(passed=True, time=time.time(),single=200,multi=100,turns=500,judge=None))
        return
    with (OUT / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (OUT / 'verified.json').exists():
            return
        records = {'single': {}, 'multi': {}}
        jobs = [('single', q) for q in single] + [('multi', q) for q in multi]
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(generate, split, q): (split, q['key']) for split, q in jobs}
            for future in concurrent.futures.as_completed(futures):
                split, key = futures[future]
                records[split][key] = future.result()
                save(OUT / 'progress.json', dict(time=time.time(), single_completed=len(records['single']), single_expected=200, multi_completed=len(records['multi']), multi_expected=100, saved_turns=len(list((OUT/'turns').glob('*/*/*.json')))))
        from s5_nano.history_verification import verify_capitu_instances
        save(OUT / 'instance_history_verified.json',verify_capitu_instances(R.parent,records['multi'].values()))
        reports = score(single, multi, records, OUT / 'eval')
        audits = [json.loads(line) for line in (R/'effective_requests_secondary.jsonl').read_text().splitlines()]
        calls = [x for x in audits if x.get('status') == 'forwarding' and x.get('benchmark') == 'capitu']
        unanswered=sum(len(v.get('unanswered_turns',[])) for rows in records.values() for v in rows.values())
        imported = 0
        recovery = R.parent/'capitu_recovery_import.json'
        if recovery.exists():
            receipt = json.loads(recovery.read_text())
            for name, checksum in receipt['imported_files'].items():
                assert sha(R.parent/name) == checksum, 'Imported CAPITU evidence changed'
            imported = receipt['imported_responses']
            from s5_nano.history_verification import verify_capitu_history
            missing_history = sum(t-1 for row in records['multi'].values() for t in row.get('unanswered_turns',[]))
            save(OUT/'recovered_history_verified.json',verify_capitu_history(R,PROFILE,
                expected_responses=500-unanswered,expected_history_turns=300-missing_history))
        assert len(calls) + imported >= 500-unanswered
        expected_policy=POLICY
        for row in calls:
            assert row['applied']['enable_thinking'] is THINKING and row['applied']['max_tokens'] == MAX_TOKENS
            assert row['applied']['max_completion_tokens'] is None
            assert all(row['applied'][k] == v for k,v in expected_policy.items())
            h = row['history']
            assert h['assistant_turns'] == sum(h.get(k,0) for k in ['reasoning_from_request','reasoning_from_cache','existing_think_tags','reasoning_from_tool_call_ids','verified_empty_reasoning']), 'Reasoning missing in multi-turn history'
        responses = [json.loads(line) for line in (R/'response_audit.jsonl').read_text().splitlines()]
        responses = [x for x in responses if x.get('benchmark') == 'capitu']
        if imported:
            import gzip
            for name in receipt['imported_files']:
                if not name.startswith('runtime/raw_api/'):
                    continue
                row = json.loads(gzip.decompress((R.parent/name).read_bytes()))
                answer = row['answer']
                responses.append(dict(empty_final=not (answer.get('content') or '').strip(),
                    truncated=row['finish_reason']=='length',
                    reasoning_chars=len(answer.get('reasoning_content') or answer.get('reasoning') or '')))
        assert len(responses) >= 500-unanswered
        # Thinking enabled does not require the model to emit a nonempty trace
        # for every answer. Empty traces must still have an originating response
        # in the proxy cache; missing history is never accepted as empty.
        metric = dict(status='FINAL', score=reports['single']['context_failure_adjustment']['score'], n=200, metric_name='single_turn_strict_accuracy_percent',
            strict_accuracy=reports['single']['context_failure_adjustment']['score'], multi_turn_conversation_accuracy=reports['multi']['context_failure_adjustment']['score'],
            single_turn_n=200,multi_turn_n=100,total_turns=500,judge=None,source=manifest['source'],
            empty_finals=sum(x['empty_final'] for x in responses),length_finishes=sum(x['truncated'] for x in responses),
            responses_without_reasoning=sum(not x['reasoning_chars'] for x in responses),
            context_failure_policy=POLICY_ID,context_failed_conversations=reports['multi']['context_failure_adjustment']['failed_cases'],
            unanswered_turns=unanswered,generated_turns=500-unanswered,
            protocol='Native CAPITU prompts and scorers; explicit user sampling and output limit; reasoning history retained; final answers only')
        save(OUT/'reports.json',reports)
        save(OUT/'verified.json',dict(passed=True,time=time.time(),metric=metric,items_sha256=manifest['manifest_sha256'],all_requests_checked=True,final_answers_only=True,
            label='CAPITU · estrito e conversas',thinking=THINKING,lumi_reference=None,comparison_note='Native CAPITU task sets; user inference preset supersedes native 8000-token limit.'))

if __name__ == '__main__':
    try:
        main()
    except BaseException as e:
        save(OUT/'failure.json',dict(time=time.time(),error_type=type(e).__name__,detail=str(e),traceback=traceback.format_exc()))
        raise
