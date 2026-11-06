"""Private resumable transport for native remaining-benchmark adapters."""
import concurrent.futures
import ast
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
import types
import sys

from .auditing import OpenAI
from .context_failures import is_context_limit_response
from .runtime_config import PROFILE, WORKERS


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    tmp.chmod(0o600)
    tmp.replace(path)


def definitions(path, names, bindings=None):
    """Execute selected original definitions, without importing a source CLI."""
    module = types.ModuleType('native_' + digest(str(path))[:16])
    module.__file__ = str(path)
    module.__dict__.update(bindings or {})
    sys.modules[module.__name__] = module
    nodes = []
    found = set()
    for node in ast.parse(Path(path).read_text()).body:
        name = getattr(node, 'name', None)
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], 'id', None)
        if isinstance(node, ast.AnnAssign):
            name = getattr(node.target, 'id', None)
        if name in names:
            nodes.append(node)
            found.add(name)
    if found != set(names):
        raise ValueError('Native definition missing: ' + str(set(names) - found))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), module.__dict__)
    return module


def claim_dispatch(root, kind, key):
    """An unfinished dispatch requires an explicit audit, never an implicit retry."""
    path = root / 'dispatch_claims' / kind / (key + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError('Existing dispatch without reusable result; audit required') from exc
    with os.fdopen(fd, 'w') as stream:
        json.dump(dict(time=time.time(), kind=kind, identity_sha256=key), stream)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Run:
    def __init__(self, root, task, *, retrospective_judgment_identity=None):
        self.root, self.task = Path(root), task
        if retrospective_judgment_identity is not None:
            from .retrospective_identity import RetrospectiveJudgmentEvidence
            if (not isinstance(retrospective_judgment_identity, RetrospectiveJudgmentEvidence)
                    or retrospective_judgment_identity.benchmark != task):
                raise ValueError('Explicit retrospective evidence must match the benchmark')
        self.retrospective_judgment_identity = retrospective_judgment_identity
        self.out = Path(os.environ['S5_NANO_RESULT_DIR']) / task
        self.out.mkdir(parents=True, exist_ok=True)
        self.manifest = json.loads((self.root / 'manifest.json').read_text())
        for name, expected in self.manifest['files'].items():
            if hashlib.sha256((self.root / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Prepared benchmark source changed: ' + name)
        self.rows = [json.loads(line) for line in (self.root / 'data/selected.jsonl').open()]
        self.identity = dict(model=os.environ['S5_NANO_MODEL'], profile=PROFILE,
                             manifest_sha256=digest(self.manifest))
        identity_path = self.out / 'identity.json'
        if identity_path.exists() and json.loads(identity_path.read_text()) != self.identity:
            raise ValueError('Run identity changed; use a new destination')
        if not identity_path.exists():
            save(identity_path, self.identity)
        self.client = None
        self.judge_client = None

    def paid_client(self):
        if self.judge_client is None:
            self.judge_client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=1800, max_retries=0)
        return self.judge_client

    def judgment(self, identifier, details, produce, valid, *, required_model=None):
        from .model_identity import capture_model_validations, verify_response_model
        identity = dict(case=str(identifier), details=details, run=self.identity)
        key = digest(identity)
        path = self.out / 'judgments' / (key + '.json')
        def validate_model(record, *, legacy_cache=False):
            expected = required_model(record['result']) if callable(required_model) else required_model
            if expected is None:
                return
            proofs = record.get('model_identity_validations')
            evidence = getattr(self, 'retrospective_judgment_identity', None)
            if legacy_cache and 'model_identity_validations' not in record and evidence is not None:
                proofs = evidence.validate(path, identity, record['result'], expected)
            if not isinstance(proofs, list) or not proofs or any(not isinstance(proof, dict) or proof.get('expected_model') != expected for proof in proofs):
                verify_response_model(record, expected, self.out, source='judgment_identity_missing', request=details)
            for proof in proofs:
                verify_response_model(dict(model=proof.get('returned_model')), expected, self.out,
                                      source='judgment_identity', provider_host=proof.get('provider_host'))
        if path.exists():
            cached = json.loads(path.read_text())
            if cached['identity'] != identity or not valid(cached['result']):
                raise ValueError('Invalid completed judgment cache')
            validate_model(cached, legacy_cache=True)
            return cached['result']
        if any((self.out / 'judgment_attempts' / key).glob('*.json')):
            raise RuntimeError('Previous judgment attempt without reusable result; audit required')
        claim_dispatch(self.out, 'judge', key)
        attempt = self.out / 'judgment_attempts' / key / (uuid.uuid4().hex + '.json')
        try:
            with capture_model_validations() as validations:
                result = produce()
        except Exception as exc:
            save(attempt, dict(identity=identity, time=time.time(), judge_error=type(exc).__name__))
            raise
        record = dict(identity=identity, time=time.time(), result=result, model_identity_validations=validations)
        if not valid(result):
            record['judge_error'] = 'invalid_verdict'
            save(attempt, record)
            raise RuntimeError('Pending judgment; previous attempt preserved, generation reusable')
        save(attempt, record)
        validate_model(record)
        save(path, record)
        return result

    def ask(self, identifier, messages, turn=0, **native_options):
        from .model_identity import ModelIdentityError, expected_model, verify_response_model
        model = expected_model(self.identity, native_options.get('extra_body'))
        if 'model' in native_options:
            raise ValueError('Native options cannot replace the explicit candidate model')
        request = dict(model=model, messages=messages, **native_options)
        identity = dict(case=str(identifier), turn=turn, request=request, run=self.identity)
        path = self.out / 'responses' / (digest(identity) + '.json')
        def validate_model(raw, source):
            verify_response_model(raw, model, self.out, source=source, request=request)
        if path.exists():
            value = json.loads(path.read_text())
            if value['identity'] != identity:
                raise ValueError('Response cache identity mismatch')
            if not (value.get('model_context_exhausted') is True and 'raw_error' in value):
                validate_model(value.get('raw'), 'response_cache')
            return value
        claim_dispatch(self.out, 'candidate', digest(identity))
        if self.client is None:
            self.client = OpenAI(base_url=os.environ['S5_NANO_PROXY_URL'] + '/' + self.task + '/v1',
                api_key=os.environ.get('S5_NANO_MODEL_API_KEY', ''), timeout=21600, max_retries=0)
        try:
            raw = self.client.chat.completions.create(**request,
                extra_headers={'X-S5-Nano-Conversation-Id': self.task + ':' + str(identifier)}).model_dump(mode='json')
        except ModelIdentityError:
            raise
        except Exception as exc:
            body = getattr(exc, 'body', None)
            if not is_context_limit_response(getattr(exc, 'status_code', None), body, PROFILE['context_length']):
                raise
            value = dict(identity=identity, raw_error=body, final='', model_context_exhausted=True)
        else:
            validate_model(raw, 'completed_http_response')
            message = raw['choices'][0]['message']
            final = message.get('content') or ''
            if not isinstance(final, str):
                raise ValueError('Nontext final answer')
            value = dict(identity=identity, raw=raw, final=final, model_context_exhausted=False)
        save(path, value)
        return value

    def parallel(self, fn):
        # Bounded in-flight work; drain already dispatched calls on any failure.
        results = []
        rows = iter(self.rows)
        exhausted = object()
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            pending = set()
            for _ in range(WORKERS):
                row = next(rows, exhausted)
                if row is exhausted:
                    break
                pending.add(pool.submit(fn, row))
            while pending:
                done, pending = concurrent.futures.wait(
                    pending, return_when=concurrent.futures.FIRST_COMPLETED)
                errors = [future.exception() for future in done if future.exception() is not None]
                for future in done:
                    if future.exception() is None:
                        results.append(future.result())
                save(self.out / 'progress.json', dict(time=time.time(), completed=len(results), expected=len(self.rows)))
                if errors:
                    # Executor context waits for all in-flight HTTP calls; no new work.
                    raise errors[0]
                for _ in done:
                    row = next(rows, exhausted)
                    if row is not exhausted:
                        pending.add(pool.submit(fn, row))
        return results

    def finish(self, metric, rows):
        expected = PROFILE['sampling']
        audited = 0
        with (self.root / 'effective_requests_secondary.jsonl').open() as stream:
            for line in stream:
                request = json.loads(line)
                if request.get('status') == 'forwarding' and request.get('benchmark') == self.task:
                    applied = request['applied']
                    if (any(applied[k] != v for k, v in expected.items()) or
                            applied['enable_thinking'] is not PROFILE['enable_thinking'] or
                            applied['max_tokens'] != PROFILE['max_tokens']):
                        raise ValueError('Effective generation parameters differ from profile')
                    audited += 1
        if not audited or len(rows) != len(self.rows):
            raise ValueError('Missing request audit or incomplete selected population')
        metric.update(status='FINAL', n=len(rows), protocol_id=self.manifest['protocol']['variant'],
                      selection_sha256=self.manifest['selection_sha256'], audited_requests=audited)
        save(self.out / 'scored_rows.json', rows)
        save(self.out / 'verified.json', dict(passed=True, time=time.time(), metric=metric,
             thinking=PROFILE['enable_thinking'], final_answers_only=True,
             protocol=self.manifest['protocol'], manifest_sha256=self.identity['manifest_sha256']))
