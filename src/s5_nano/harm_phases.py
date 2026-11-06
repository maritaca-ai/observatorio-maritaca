"""Verify frozen HarmBench generations and score them without a candidate server."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def closed_ledger(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    starts = [row['attempt_id'] for row in rows if row['phase'] == 'started']
    ends = [row['attempt_id'] for row in rows if row['phase'] == 'finished']
    if (not starts or len(starts) != len(set(starts)) or len(ends) != len(set(ends))
            or set(starts) != set(ends)
            or any(row['phase'] not in ('started', 'finished') for row in rows)
            or any(row['status'] != 200 for row in rows if row['phase'] == 'finished')):
        raise ValueError('HarmBench transport requires audit; no classification dispatch')
    return rows


def generation_evidence(run):
    from .remaining_core import definitions, digest
    native = definitions(run.root / 'sources/baselines/direct_request/direct_request.py',
                         ['DirectRequest'], dict(RedTeamingMethod=object))
    cases, _ = native.DirectRequest().generate_test_cases(run.rows)
    expected = {row['BehaviorID'] for row in run.rows}
    if len(run.rows) != 320 or len(expected) != 320 or set(cases) != expected:
        raise ValueError('HarmBench generation population changed')
    completions_path = run.out / 'native_completions.json'
    completions = json.loads(completions_path.read_text())
    if set(completions) != expected:
        raise ValueError('HarmBench completions population changed')
    files = sorted((run.out / 'responses').glob('*.json'))
    seen, response_ids = set(), set()
    for path in files:
        item = json.loads(path.read_text())
        identity, raw = item['identity'], item.get('raw')
        identifier = identity['case']
        if (path.stem != digest(identity) or identifier not in expected or identifier in seen
                or identity['run'] != run.identity or identity['turn'] != 0
                or item.get('model_context_exhausted') or item.get('error')
                or not isinstance(raw, dict) or raw.get('model') != run.identity['model']
                or not isinstance(raw.get('id'), str) or not raw['id'] or raw['id'] in response_ids):
            raise ValueError('HarmBench response identity changed or generation incomplete')
        requested = identity['request']
        if (requested['model'] != run.identity['model'] or requested['messages'] !=
                [dict(role='user', content=cases[identifier][0])]):
            raise ValueError('HarmBench native candidate prompt changed')
        final = raw['choices'][0]['message'].get('content') or ''
        if (item['final'] != final or completions[identifier] !=
                [dict(test_case=cases[identifier][0], generation=final)]):
            raise ValueError('HarmBench frozen completion differs from the original response')
        seen.add(identifier)
        response_ids.add(raw['id'])
    if seen != expected or len(files) != 320:
        raise ValueError('HarmBench response population incomplete')
    candidate = closed_ledger(run.root / 'candidate_attempts.jsonl')
    sdk = closed_ledger(run.root / 'http_attempts.jsonl')
    if (sum(row['phase'] == 'started' and row.get('benchmark') == 'harmbench' for row in candidate) != 320
            or sum(row['phase'] == 'started' for row in sdk) != 320):
        raise ValueError('HarmBench dispatch count differs from the frozen population')
    return dict(schema_version=1, identity=run.identity, n=320,
                native_completions_sha256=sha(completions_path),
                native_manifest_sha256=sha(run.root / 'manifest.json'),
                selected_rows_sha256=sha(run.root / 'data/selected.jsonl'),
                responses={path.name: sha(path) for path in files},
                candidate_ledger_sha256=sha(run.root / 'candidate_attempts.jsonl'),
                sdk_ledger_sha256=sha(run.root / 'http_attempts.jsonl'))


def mark_generation_ready(run):
    from .runtime import freeze
    receipt = dict(status='GENERATION_COMPLETE', evidence=generation_evidence(run))
    freeze(run.out / 'generation_ready.json', receipt)
    return receipt


def verify_generation(run):
    receipt = json.loads((run.out / 'generation_ready.json').read_text())
    if receipt != dict(status='GENERATION_COMPLETE', evidence=generation_evidence(run)):
        raise ValueError('Frozen HarmBench generation evidence changed')
    return receipt


def score(source, classifier, url, scorer_python):
    """Only the existing classifier endpoint is used; this function starts no server."""
    source, classifier = Path(source).resolve(), Path(classifier).resolve()
    endpoint = urlsplit(url)
    if (endpoint.scheme not in ('http', 'https') or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('Classifier URL must not contain credentials or query strings')
    profile = json.loads((source / 'profile.json').read_text())
    os.environ.update(S5_NANO_PROFILE=str(source / 'profile.json'), S5_NANO_MODEL=profile['model'],
                      S5_NANO_RESULT_DIR=str(source / 'results'), S5_NANO_BENCHMARK='harmbench')
    from .prepare import REPO
    from .remaining_core import Run, save
    from .remaining_harm import finish
    with (source / 'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads((source / 'run_manifest.json').read_text())
        if manifest['profile'] != profile or manifest['benchmark']['tasks'] != ['harmbench']:
            raise ValueError('HarmBench run identity changed')
        for name, expected in manifest['code'].items():
            if sha(REPO / name) != expected:
                raise ValueError('Use the frozen generation code for HarmBench scoring')
        for field, filename in [('dependencies_sha256', 'requirements.lock'),
                                ('scorer_dependencies_sha256', 'requirements-scorer.lock'),
                                ('remaining_dependencies_sha256', 'requirements-remaining.lock'),
                                ('harm_scorer_dependencies_sha256', 'requirements-harm-scorer.lock')]:
            if sha(REPO / filename) != manifest[field]:
                raise ValueError('HarmBench dependency lock changed')
        run = Run(source / 'runtime', 'harmbench')
        verify_generation(run)
        ready = json.loads((source / 'generation_complete.json').read_text())
        if (ready['status'] != 'GENERATION_COMPLETE'
                or ready['generation_ready_sha256'] != sha(run.out / 'generation_ready.json')
                or ready['run_manifest_sha256'] != sha(source / 'run_manifest.json')):
            raise ValueError('HarmBench generation phase receipt changed')
        final_path = source / 'results_verified.json'
        if final_path.exists():
            saved = json.loads(final_path.read_text())
            proof = json.loads((run.out / 'verified.json').read_text())
            if (saved['status'] != 'FINAL' or saved['profile'] != profile
                    or saved['benchmarks'] != {'harmbench': proof['metric']}
                    or saved['generation_ready_sha256'] != sha(run.out / 'generation_ready.json')):
                raise ValueError('HarmBench final result identity changed')
            return saved
        classifier_lock = json.loads((REPO / 'locks/harmbench-classifier.json').read_text())['models']['harmbench-classifier']
        for name, expected in classifier_lock['files'].items():
            if sha(classifier / name) != expected:
                raise ValueError('HarmBench classifier weights changed')
        env = {key: value for key, value in os.environ.items() if key not in
               ('OPENAI_API_KEY', 'OPENAI_ADMIN_KEY', 'MARITACA_API_KEY', 'SERPER_API_KEY', 'VLLM_API_KEY')}
        env.update(S5_NANO_AUDIT_DIR=str(run.out / 'classifier_audit'), PYTHONPATH=str(REPO / 'src'))
        command = [scorer_python, '-m', 's5_nano.harm_scorer', '--root', str(run.root),
                   '--output', str(run.out), '--classifier', str(classifier), '--url', url]
        with (run.out / 'score_phase.log').open('ab') as log:
            subprocess.run(command, env=env, stdin=subprocess.DEVNULL, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        verify_generation(run)
        classifier_rows = closed_ledger(run.out / 'classifier_audit/http_attempts.jsonl')
        if any(row.get('response_model') != 'harmbench-classifier'
               for row in classifier_rows if row['phase'] == 'finished'):
            raise ValueError('HarmBench classifier response identity changed')
        finish(run)
        proof = json.loads((run.out / 'verified.json').read_text())
        result = dict(status='FINAL', model=profile['model'], profile=profile,
                      benchmarks={'harmbench': proof['metric']},
                      independent_verification=dict(passed=True),
                      run_manifest_sha256=sha(source / 'run_manifest.json'),
                      generation_ready_sha256=sha(run.out / 'generation_ready.json'),
                      time=time.time(), candidate_calls_in_score_phase=0)
        responses = [json.loads(line) for line in (run.root / 'response_audit.jsonl').read_text().splitlines()]
        result['mode_audit'] = dict(policy='requested_mode_final_only', requested_thinking=profile['enable_thinking'],
            spontaneous_reasoning_responses=sum(bool(row['reasoning_chars']) for row in responses)
            if not profile['enable_thinking'] else 0)
        save(final_path, result)
        print(json.dumps(dict(benchmark='harmbench', status='FINAL', score=proof['metric']['score'])))
        return result
