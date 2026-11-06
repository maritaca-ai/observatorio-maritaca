"""DirectRequest generations and native local HarmBench grading on the allocated GPU."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import urllib.request

from .remaining_core import definitions, save
from .prepare import REPO
from .processes import stop_process


def classifier_environment(source):
    """Use an ephemeral local token, without forwarding paid-provider credentials."""
    env = {key: value for key, value in source.items() if key not in
           ('OPENAI_API_KEY', 'OPENAI_ADMIN_KEY', 'MARITACA_API_KEY', 'SERPER_API_KEY')}
    env['S5_NANO_CLASSIFIER_API_KEY'] = secrets.token_urlsafe(32)
    env['VLLM_API_KEY'] = env['S5_NANO_CLASSIFIER_API_KEY']
    return env


def finish_classifier(output, server):
    """An uncertain classifier request does not authorize killing its server."""
    pending = None
    try:
        path = output / 'classifier_audit/http_attempts.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
        rows = [row for row in rows if row.get('model') == 'harmbench-classifier']
        starts = {row['attempt_id'] for row in rows if row['phase'] == 'started'}
        ends = {row['attempt_id'] for row in rows if row['phase'] == 'finished'}
        if ends - starts:
            raise ValueError('Classifier completion without recorded start')
        pending = starts - ends
    except (OSError, ValueError, KeyError, TypeError):
        pass
    alive = server.poll() is None
    if pending != set():
        save(output / 'classifier_cleanup.json', dict(time=time.time(), pid=server.pid,
            status='RETAINED_FOR_AUDIT' if alive else 'EXITED_AUDIT_REQUIRED',
            pending=len(pending) if pending is not None else None))
        raise RuntimeError('Unresolved HarmBench classifier attempts; server requires audit')
    if alive:
        stop_process(server)
    save(output / 'classifier_cleanup.json', dict(time=time.time(), pid=server.pid,
        status='STOPPED_AFTER_DRAIN' if alive else 'ALREADY_EXITED', pending=0))


def evaluate(run, preflight=False):
    phase = os.environ.get('S5_NANO_HARM_PHASE', 'all')
    if phase not in ('all', 'generate'):
        raise ValueError('Unknown HarmBench phase')
    native = definitions(run.root / 'sources/baselines/direct_request/direct_request.py', ['DirectRequest'],
                         dict(RedTeamingMethod=object))
    test_cases, _ = native.DirectRequest().generate_test_cases(run.rows)
    if len(test_cases) != 320:
        raise ValueError('HarmBench population changed')
    if preflight:
        command, env = scorer_command(run)
        subprocess.run(command + ['--preflight'], env=env, check=True)
        save(run.out / 'preflight.json', dict(passed=True, n=320, model_or_judge_calls=0))
        return
    responses = run.parallel(lambda row: dict(id=row['BehaviorID'], test_case=test_cases[row['BehaviorID']][0],
        generation=run.ask(row['BehaviorID'], [{'role': 'user', 'content': test_cases[row['BehaviorID']][0]}],
                           temperature=0, max_tokens=512)['final']))
    save(run.out / 'native_completions.json', {row['id']: [dict(test_case=row['test_case'], generation=row['generation'])] for row in responses})
    if phase == 'generate':
        from .harm_phases import mark_generation_ready
        mark_generation_ready(run)
        return
    command, env = scorer_command(run)
    weights = Path(os.environ['S5_NANO_HARM_CLASSIFIER'])
    lock = json.loads((REPO / 'locks/harmbench-classifier.json').read_text())['models']['harmbench-classifier']
    for name, expected in lock['files'].items():
        sha = hashlib.sha256()
        with (weights / name).open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                sha.update(chunk)
        if sha.hexdigest() != expected:
            raise ValueError('HarmBench classifier weights changed')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    argv = [os.environ['S5_NANO_HARM_SERVING_PYTHON'], '-m', 'vllm.entrypoints.openai.api_server',
        '--model', str(weights), '--served-model-name', 'harmbench-classifier',
        '--host', '127.0.0.1', '--port', str(port), '--tensor-parallel-size', '1',
        '--gpu-memory-utilization', '.30', '--max-num-seqs', '32']
    with (run.out / 'classifier_server.log').open('ab') as log:
        server = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                  stderr=subprocess.STDOUT, start_new_session=True)
    save(run.out / 'classifier_server.json', dict(pid=server.pid, argv=argv, model=lock['model'],
        revision=lock['revision'], lock_sha256=hashlib.sha256((REPO / 'locks/harmbench-classifier.json').read_bytes()).hexdigest()))
    try:
        deadline = time.monotonic() + 1800
        while True:
            if server.poll() is not None:
                raise RuntimeError('Local HarmBench classifier failed; results remain pending')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError('Local HarmBench classifier readiness')
                time.sleep(3)
        subprocess.run(command + ['--classifier', str(weights), '--url', f'http://127.0.0.1:{port}/v1'], env=env, check=True)
    finally:
        finish_classifier(run.out, server)
    finish(run)


def finish(run):
    lock = json.loads((REPO / 'locks/harmbench-classifier.json').read_text())['models']['harmbench-classifier']
    rows = json.loads((run.out / 'native_scored_rows.json').read_text())
    completions = json.loads((run.out / 'native_completions.json').read_text())
    expected = {row['BehaviorID'] for row in run.rows}
    if len(rows) != 320 or {row['id'] for row in rows} != expected or set(completions) != expected:
        raise ValueError('HarmBench scored population changed')
    for row in rows:
        digest = hashlib.sha256(completions[row['id']][0]['generation'].encode()).hexdigest()
        if row['original_final_sha256'] != digest or row['label'] not in (-1, 0, 1):
            raise ValueError('HarmBench scored completion changed')
    run.finish(dict(score=100 * sum(row['label'] == 1 for row in rows) / 320,
        metric_name='directrequest_attack_success_rate', higher_is_better=False,
        native_invalid_classifier_labels=sum(row['label'] == -1 for row in rows),
        classifier=lock['model'], classifier_revision=lock['revision'], external_api_cost_usd=0), rows)


def scorer_command(run):
    command = [os.environ['S5_NANO_HARM_SCORER_PYTHON'], '-m', 's5_nano.harm_scorer',
               '--root', str(run.root.resolve()), '--output', str(run.out.resolve())]
    env = classifier_environment(os.environ)
    env['S5_NANO_AUDIT_DIR'] = str((run.out / 'classifier_audit').resolve())
    return command, env
