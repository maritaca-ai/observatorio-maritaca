"""Native BrowseComp-Plus val100, with persistent turns and a fixed denominator."""
import concurrent.futures
import fcntl
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import sys
import threading
import time
import types

from s5_nano.auditing import OpenAI
from s5_nano import plus_judge
from openai.types.chat import ChatCompletion
from transformers import AutoTokenizer
from s5_nano.runtime_config import POLICY, THINKING, WORKERS, MAX_TOKENS

R = Path(__file__).resolve().parent
INPUTS = Path(os.environ.get('S5_NANO_PLUS_INPUTS', R))
OUT = Path(os.environ['S5_NANO_RESULT_DIR']) / 'browsecomp_plus'
AUDIT = Path(os.environ.get('S5_NANO_AUDIT_DIR', R))
TASK = 'browsecomp_plus'
MODEL = os.environ['S5_NANO_MODEL']
JUDGE_PROFILE = plus_judge.profile()
JUDGE = JUDGE_PROFILE['model']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + str(threading.get_ident()) + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def cached(directory, key, function):
    path = Path(directory) / (digest(key) + '.json')
    if path.exists():
        return json.loads(path.read_text())
    value = function()
    save(path, value)
    return value


def load_native():
    sys.path.insert(0, str(INPUTS / 'native'))
    import native_client
    import grader
    import prompts
    from retrieval.bm25_searcher import BM25Searcher
    searcher = BM25Searcher(types.SimpleNamespace(index_path=str(INPUTS / 'index')))
    # The native snippet tokenizer is separate from the candidate tokenizer.
    handler = native_client.SearchToolHandler(searcher, snippet_max_tokens=None,
                                             k=5, include_get_document=True)
    handler.snippet_max_tokens = 512
    handler.tokenizer = AutoTokenizer.from_pretrained(INPUTS / 'snippet_tokenizer', local_files_only=True)
    return native_client, grader, prompts, handler


class DurableCompletions:
    def __init__(self, client, directory):
        self.client, self.directory, self.calls = client, directory, []

    def create(self, **kwargs):
        number = len(self.calls)
        key = dict(turn=number, request=kwargs)
        value = cached(self.directory, key, lambda: self.client.chat.completions.create(**kwargs).model_dump(mode='json'))
        self.calls.append(value)
        return ChatCompletion.model_validate(value)


class DurableTools:
    def __init__(self, handler, directory):
        self.handler, self.directory = handler, directory

    def execute_tool(self, name, arguments):
        return cached(self.directory, dict(name=name, arguments=arguments),
                      lambda: dict(output=self.handler.execute_tool(name, arguments)))['output']


def generate(job, client, native, prompts, handler):
    def run():
        qid = job['query_id']
        folder = OUT / 'turn_cache' / str(qid)
        transport = DurableCompletions(client, folder / 'model')
        wrapped = types.SimpleNamespace(chat=types.SimpleNamespace(completions=transport))
        messages = [dict(role='user', content=prompts.format_query(job['query'], 'QUERY_TEMPLATE'))]
        status, error, counts, outputs = 'completed', None, {}, {}
        try:
            messages, counts, outputs, status = native.run_conversation_with_tools(
                wrapped, MODEL, messages, handler.get_tool_definitions(),
                DurableTools(handler, folder / 'tools'), max_iterations=100,
                temperature=None, reasoning_effort=None)
        except Exception as exc:
            # Match the native single-pass policy; successful turns remain cached.
            status = 'failed'
            error = dict(type=type(exc).__name__, message=str(exc)[:500])
        final = '\n'.join(m.get('content', '') for m in messages
                          if m.get('role') == 'assistant' and not m.get('tool_calls')
                          and m.get('content'))
        if status != 'completed':
            final = ''
        calls = [tc for m in messages if m.get('role') == 'assistant' for tc in m.get('tool_calls', [])]
        usage = {k: sum((x.get('usage') or {}).get(k, 0) or 0 for x in transport.calls)
                 for k in ['prompt_tokens', 'completion_tokens', 'total_tokens']}
        return dict(query_id=qid, status=status, error=error, final=final,
                    messages=messages, tool_call_counts=counts, tool_outputs=outputs,
                    iterations=len(transport.calls), usage=usage,
                    finish_reasons=[x['choices'][0].get('finish_reason') for x in transport.calls],
                    invented_tool_calls=sum(tc['function']['name'] not in ['search', 'get_document'] for tc in calls))
    return cached(OUT / 'responses', job['query_id'], run)


def judge_response(job, record, client, native):
    return plus_judge.judge_response(job, record, client, native, OUT, JUDGE_PROFILE,
        retry_failed=os.environ.get('S5_NANO_RETRY_FAILED_JUDGMENTS')=='1')


def summarize(rows):
    return plus_judge.summarize(rows, JUDGE_PROFILE)


def verify_requests():
    count = 0
    for line in (AUDIT / 'effective_requests_secondary.jsonl').read_text().splitlines():
        row = json.loads(line)
        if row.get('status') != 'forwarding' or row.get('benchmark') != TASK:
            continue
        applied = row['applied']
        assert applied['enable_thinking'] is THINKING and applied['max_tokens'] == MAX_TOKENS
        assert all(applied[k] == v for k, v in POLICY.items())
        assert row['native_budget_fields'].get('reasoning_effort') is None
        count += 1
    assert count > 0
    return count


def main():
    os.umask(0o077)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads((INPUTS / 'manifest.json').read_text())
        for name, checksum in manifest['files'].items():
            assert sha(INPUTS / name) == checksum, name
        for name, checksum in manifest['index_files'].items():
            assert sha(INPUTS / 'index' / name) == checksum, name
        jobs = json.loads((INPUTS / 'cases.json').read_text())
        assert len(jobs) == 100 and {r['query_id'] for r in jobs} == set(manifest['protocol']['query_ids'])
        identity = dict(model=MODEL, profile=json.loads(Path(os.environ['S5_NANO_PROFILE']).read_text()),
                        input_manifest_sha256=manifest['manifest_sha256'], worker_sha256=sha(__file__),
                        judge_profile=JUDGE_PROFILE)
        path = OUT / 'identity.json'
        if path.exists():
            assert json.loads(path.read_text()) == identity, 'Changed run identity'
        else:
            save(path, identity)
        native, grader, prompts, handler = load_native()
        # CPU-only retrieval preflight: both native tools must work on this index.
        hits = json.loads(handler.execute_tool('search', {'query': 'Brazil'}))
        assert len(hits) == 5
        assert json.loads(handler.execute_tool('get_document', {'docid': hits[0]['docid']}))['text']
        save(OUT / 'preflight.json', dict(passed=True, time=time.time(), n=100,
                                        manifest_sha256=manifest['manifest_sha256'], index_verified=True,
                                        snippet_tokenizer=manifest['protocol']['snippet_tokenizer'],
                                        candidate_model=MODEL))
        if '--preflight' in sys.argv:
            return
        candidate = OpenAI(base_url=os.environ['S5_NANO_PROXY_URL'] + '/browsecomp_plus/v1',
                           api_key=os.environ.get('S5_NANO_MODEL_API_KEY', 'local'), timeout=600, max_retries=2)
        judge = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=600, max_retries=2)
        def one(job):
            generation = generate(job, candidate, native, prompts, handler)
            verdict = judge_response(job, generation, judge, grader)
            return dict(query_id=job['query_id'], generation=generation, judge=verdict)
        rows = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for future in concurrent.futures.as_completed([pool.submit(one, job) for job in jobs]):
                rows.append(future.result())
                save(OUT / 'progress.json', dict(time=time.time(), completed=len(rows), expected=100, status='PARTIAL'))
        metric = summarize(rows)
        metric.update(protocol=plus_judge.effective_protocol(manifest['protocol'], JUDGE_PROFILE),
                      public_benchmark_sources=True,
                      sources=manifest['sources'], audited_requests=verify_requests())
        save(OUT / 'scored_summary.json', [dict(query_id=x['query_id'], correct=x['judge']['correct'],
                                             answered=x['judge']['answered']) for x in rows])
        save(OUT / 'verified.json', dict(passed=True, time=time.time(), metric=metric,
                                        items_sha256=manifest['manifest_sha256'], all_requests_checked=True,
                                        final_answers_only=True, thinking=THINKING,
                                        label='BrowseComp-Plus · BM25 · val100 · GPT-6 Luna medium',
                                        comparison_note='Same 100 IDs, retrieval, tools and native rubric; GPT-6 Luna medium judge variant; candidate-specific sampling and campaign reasoning history.'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        save(OUT / 'failure.json', dict(time=time.time(), error_type=type(exc).__name__, detail=str(exc)[-300:]))
        raise
