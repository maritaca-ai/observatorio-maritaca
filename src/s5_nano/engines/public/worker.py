from s5_nano.runtime_config import POLICY, THINKING, WORKERS, MAX_TOKENS
"""Resumable public MARCA, with the explicit campaign sampler enforced."""
import ast
import concurrent.futures
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from statistics import mean
import sys
import time
import traceback
import types

from s5_nano.auditing import OpenAI
from openai.types.chat import ChatCompletion

R = Path(__file__).resolve().parent
TASK = sys.argv[1] if len(sys.argv) > 1 else None
MODEL = os.environ['S5_NANO_MODEL']
BASE = os.environ['S5_NANO_PROXY_URL']+'/'+str(TASK)+'/v1'
LABELS = {'marca_public': 'MARCA público · PT e EN'}
OUT = Path(os.environ['S5_NANO_RESULT_DIR'])/str(TASK)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def saved(directory, key, fn):
    path = directory / (digest(key) + '.json')
    if path.exists():
        return json.loads(path.read_text())
    value = fn()
    save(path, value)
    return value


def native(name, path):
    """Load definitions and literal globals, without executing a source CLI."""
    sys.path.insert(0, str(path.parent))
    body = []
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.FunctionDef)):
            body.append(node)
        elif isinstance(node, ast.Assign):
            try:
                ast.literal_eval(node.value)
                body.append(node)
            except (ValueError, TypeError):
                pass
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), module.__dict__)
    return module


class DurableCompletions:
    def __init__(self, client, directory):
        self.client, self.directory = client, directory

    def create(self, **kwargs):
        row = saved(self.directory, kwargs,
                    lambda: self.client.chat.completions.create(**kwargs).model_dump(mode='json'))
        return ChatCompletion.model_validate(row)


class DurableTool:
    def __init__(self, tool, directory):
        self.tool, self.directory = tool, directory
        self.name = tool.name

    def get_openai_compatible_schema(self):
        return self.tool.get_openai_compatible_schema()

    def execute(self, **kwargs):
        return saved(self.directory, dict(tool=self.name, arguments=kwargs),
                     lambda: dict(result=self.tool.execute(**kwargs)))['result']


def agent(module, case_key, iterations):
    class DurableAssistant(module.AssistantWithTools):
        def __init__(self):
            self.attempt = 0

        def generate_response(self, messages, **kwargs):
            root = OUT / 'turn_cache' / digest(case_key) / str(self.attempt)
            self.attempt += 1
            public_tools = [module.SearchTool(), module.PageScraperTool()]
            model = module.AssistantWithTools(
                MODEL, BASE, os.environ.get('S5_NANO_MODEL_API_KEY',''), system_prompt=module.system_prompt,
                tools=[DurableTool(t, root / 'tools') for t in public_tools], temperature=1)
            model.max_iterations = iterations
            client = OpenAI(base_url=BASE, api_key=os.environ.get('S5_NANO_MODEL_API_KEY',''), timeout=21600, max_retries=2)
            model.client = types.SimpleNamespace(chat=types.SimpleNamespace(
                completions=DurableCompletions(client, root / 'model')))
            return model.generate_response(messages, **kwargs)
    return DurableAssistant()


def parallel(items, fn):
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for future in concurrent.futures.as_completed([pool.submit(fn, x) for x in items]):
            rows.append(future.result())
            save(OUT / 'progress.json', dict(time=time.time(), completed=len(rows), expected=len(items)))
    return rows


def verify_sources():
    manifest = json.loads((R / 'manifest.json').read_text())
    for name, checksum in manifest['files'].items():
        assert hashlib.sha256((R / name).read_bytes()).hexdigest() == checksum, name
    return manifest


def complete(rows, details):
    count = 0
    expected=POLICY
    for line in (R / 'effective_requests_secondary.jsonl').read_text().splitlines():
        row = json.loads(line)
        if row.get('status') != 'forwarding' or row.get('benchmark') != TASK:
            continue
        assert row['applied']['enable_thinking'] is THINKING and row['applied']['max_tokens'] == MAX_TOKENS
        assert all(row['applied'][k] == v for k, v in expected.items())
        assert row['native_budget_fields'].get('reasoning_effort') is None
        count += 1
    assert count > 0
    manifest = verify_sources()
    metric = dict(status='FINAL', n=len(rows), **details,
                  sources=manifest['sources'], public_benchmark_sources=True,
                  protocol=manifest['protocols'][TASK], audited_requests=count)
    save(OUT / 'scored_rows.json', rows)
    save(OUT / 'verified.json', dict(passed=True, time=time.time(), metric=metric,
        items_sha256=manifest['manifest_sha256'], all_requests_checked=True,
        final_answers_only=True, label=LABELS[TASK], thinking=THINKING, lumi_reference=None,
        comparison_note='Separate public-source protocol; historical private runs are not reused.'))


def marca_jobs(grader, resolve=False):
    jobs = []
    for dataset in ('marca_pt', 'marca_en'):
        categories = grader.load_all_categories(dataset)
        assert sum(len(c['questions']) for c in categories.values()) == 52
        for category, data in sorted(categories.items()):
            for question in data['questions']:
                checks = []
                if resolve:
                    for name in question['checklist']:
                        for item in data['checklists'][name.lower()]:
                            if isinstance(item, str):
                                checks.append(item)
                            else:
                                row = saved(OUT / 'dynamic_checklists', item,
                                    lambda item=item: dict(time=time.time(), checks=
                                        grader.available_dynamic_checklists[item['class']].get_checklist(**item['parameters'])))
                                checks.extend(row['checks'])
                    assert checks
                jobs.append(dict(dataset=dataset, category=category, question=question, checks=checks))
    return jobs


def run_marca(module, grader):
    jobs_path = OUT / 'frozen_jobs.json'
    if not jobs_path.exists():
        save(jobs_path, marca_jobs(grader, resolve=True))
    jobs = json.loads(jobs_path.read_text())
    assert len(jobs) == 104
    judge = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=1800, max_retries=2)
    module.args = types.SimpleNamespace(k=1)

    def one(job):
        dataset, category, q, checks = [job[k] for k in ('dataset', 'category', 'question', 'checks')]
        key = [dataset, q['id']]
        response = saved(OUT / 'responses', key, lambda:
            module.process_single_question_generation(dict(q, category=category), 0, agent(module, key, 40)))

        def grade():
            for attempt in range(3):
                result = grader.evaluate_single_response(dataset, (q, response, checks, category, judge))
                if result is not None:
                    items = result['judged_checklist']['check_items']
                    if len(items) == len(checks) and sorted(i['item_number'] for i in items) == list(range(1, len(checks)+1)):
                        assert abs(result['percentage_correct'] - mean(i['correct'] for i in items)) < 1e-12
                        return result
                time.sleep(2 ** attempt)
            raise RuntimeError('Public MARCA judge failed; preserve generation and retry judgment later')

        result = saved(OUT / 'judgments', key, grade)
        return dict(dataset=dataset, id=q['id'], score=result['percentage_correct'],
                    generation_error=bool(response.get('error')))

    rows = parallel(jobs, one)
    assert len({(r['dataset'], r['id']) for r in rows}) == 104
    scores = {d: 100 * mean(r['score'] for r in rows if r['dataset'] == d) for d in ('marca_pt', 'marca_en')}
    complete(rows, dict(score=mean(scores.values()), datasets=scores, metric_name='rubric_score_percent',
        judge='gpt-4.1-2025-04-14', judge_errors=0,
        generation_errors=sum(r['generation_error'] for r in rows), k=1, max_tool_iterations=40,
        frozen_jobs_sha256=hashlib.sha256(jobs_path.read_bytes()).hexdigest()))


def main():
    assert TASK in LABELS
    os.umask(0o077)
    OUT.mkdir(parents=True, exist_ok=True)
    verify_sources()
    assert json.loads((R / 'run_manifest.json').read_text())['profile']['enable_thinking'] is THINKING
    if '--preflight' not in sys.argv:
        for name in ['OPENAI_API_KEY','SERPER_API_KEY']:assert os.environ.get(name), 'Missing environment variable: '+name
    # Transport timeout only; public search/crawl inputs and outputs are unchanged.
    import requests
    from s5_nano.auditing import install_tool_http_audit
    install_tool_http_audit()
    request = requests.request
    def timed_request(*args, **kwargs):
        kwargs.setdefault('timeout', 90)
        return request(*args, **kwargs)
    requests.request = timed_request
    root = R / 'sources/MARCA'
    os.chdir(root)
    module = native('public_marca_main', root / 'main.py')
    grader = native('public_marca_eval', root / 'eval.py')
    if '--preflight' in sys.argv:
        n = len(marca_jobs(grader))
        save(OUT / 'preflight.json', dict(passed=True, time=time.time(), count=n, public_sources=True))
        return
    with (OUT / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (OUT / 'verified.json').exists():
            return
        save(OUT / 'started.json', dict(time=time.time(), pid=os.getpid(), thinking=THINKING, public_sources=True))
        run_marca(module, grader)


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        save(OUT / 'failure.json', dict(time=time.time(), type=type(exc).__name__,
            detail=str(exc)[:1000], traceback=traceback.format_exc()))
        raise
