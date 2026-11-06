"""Explicit, hash-pinned evidence for unchanged legacy Cultural/Arena caches."""
import base64
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath

from .model_identity import ModelIdentityError

KIND = 'retrospective_native_judgment_identity_v1'
ORIGIN = 'RETROSPECTIVE_OFFLINE_NATIVE_REPLAY_NOT_CONTEMPORANEOUS'
MODELS = {'culturalbench': 'gpt-4o-mini-2024-07-18', 'arena_hard_v2': 'gpt-6-luna'}
ENDPOINTS = {'culturalbench': '/v1/chat/completions', 'arena_hard_v2': '/v1/responses'}


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def identity_digest(value):
    return checksum(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def request_signature(host, path, request):
    value = dict(host=host, path=path, request=request)
    return checksum(json.dumps(value, sort_keys=True, ensure_ascii=False,
                               separators=(',', ':')).encode())


def require(condition):
    if not condition:
        raise ModelIdentityError('Retrospective judgment evidence needs audit; cache unchanged')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


class RetrospectiveJudgmentEvidence:
    """Opt-in evidence, never inferred from a nearby file or model alias.

    The manifest hash must come from the separately reviewed native replay audit.
    All artifact paths in that manifest are relative to the explicitly supplied
    historical root. The manifest is evidence of a retrospective audit, not a
    replacement for a contemporaneous validation recorded by the runner.
    """

    def __init__(self, manifest_path, manifest_sha256, artifact_root):
        self.path = Path(manifest_path)
        self.expected_sha256 = manifest_sha256
        self.artifact_root = Path(artifact_root).resolve(strict=True)
        require(self.artifact_root.is_dir())
        data = self.path.read_bytes()
        require(checksum(data) == manifest_sha256)
        self.manifest = json.loads(data, object_pairs_hook=unique_object)
        require(self.manifest.get('kind') == KIND and self.manifest.get('origin') == ORIGIN)
        self.benchmark = self.manifest.get('benchmark')
        require(self.benchmark in MODELS)
        require(self.manifest.get('network_disabled') is True)
        for name in ('new_judge_calls', 'new_candidate_calls'):
            require(type(self.manifest.get(name)) is int and self.manifest[name] == 0)
        replay = self.manifest.get('native_replay', {})
        for name, length in [('script_sha256', 64), ('source_revision', 40)]:
            value = replay.get(name)
            require(isinstance(value, str) and len(value) == length
                    and all(c in '0123456789abcdef' for c in value))
        records = self.manifest.get('records')
        require(isinstance(records, dict) and bool(records))
        attempts, caches, requests = set(), set(), set()
        for key, record in records.items():
            require(record.get('cache_identity_sha256') == key)
            require(record.get('native_result_unchanged') is True)
            cache = self.artifact(record['cache_artifact'])
            require(cache not in caches)
            caches.add(cache)
            paid = record.get('original_http_attempts')
            require(isinstance(paid, list))
            require(len(paid) == (0 if record.get('required_model') is None else 1))
            require(record.get('required_model') in (None, MODELS[self.benchmark]))
            for attempt in paid:
                for field in ('request_artifact', 'response_artifact', 'original_ledger'):
                    self.artifact(attempt[field])
                identity = (attempt['original_ledger'], attempt['attempt_id'])
                require(identity not in attempts)
                attempts.add(identity)
                request = (attempt['provider_host'], attempt['provider_path'], attempt['request_signature'])
                require(request not in requests)
                requests.add(request)

    def artifact(self, relative):
        require(isinstance(relative, str) and bool(relative))
        path = PurePosixPath(relative)
        require(not path.is_absolute() and '..' not in path.parts and str(path) == relative)
        resolved = (self.artifact_root / relative).resolve(strict=True)
        require(resolved.is_relative_to(self.artifact_root) and resolved.is_file())
        return resolved

    def read_artifact(self, relative, expected, compressed=False):
        data = self.artifact(relative).read_bytes()
        require(checksum(data) == expected)
        return json.loads(gzip.decompress(data) if compressed else data)

    def validate(self, cache_path, identity, result, expected_model):
        """Return exact-model proofs after checking the original closed attempt."""
        require(checksum(self.path.read_bytes()) == self.expected_sha256)
        require(identity_digest(identity['run']) == self.manifest['run_identity_sha256'])
        key = identity_digest(identity)
        record = self.manifest['records'][key]
        require(record['case_id'] == identity['case'])
        require(record['cache_identity_sha256'] == key)
        require(record['required_model'] == expected_model)
        require(identity_digest(result) == record['result_sha256'])
        cache_bytes = Path(cache_path).read_bytes()
        require(checksum(cache_bytes) == record['cache_sha256'])
        cached = json.loads(cache_bytes)
        original = self.read_artifact(record['cache_artifact'], record['cache_sha256'])
        require(cached == original and original['identity'] == identity and original['result'] == result)
        attempts = record['original_http_attempts']
        if expected_model is None:
            require(self.benchmark == 'culturalbench' and result.get('src') == 'rule' and not attempts)
            return []
        require(expected_model == MODELS[self.benchmark] and len(attempts) == 1)
        proofs = []
        for attempt in attempts:
            request = self.read_artifact(attempt['request_artifact'], attempt['request_sha256'], True)
            response = self.read_artifact(attempt['response_artifact'], attempt['response_sha256'], True)
            payload = request['payload']
            require(payload == json.loads(base64.b64decode(request['wire_body_base64'])))
            raw = json.loads(base64.b64decode(response['wire_body_base64']))
            require(response['status'] == 200)
            if 'payload' in response:
                require(response['payload'] == raw)
            require(request['host'] == attempt['provider_host'] == 'api.openai.com')
            require(request['path'] == attempt['provider_path'] == ENDPOINTS[self.benchmark])
            require(request['method'] == attempt['method'] == 'POST')
            require(payload['model'] == attempt['requested_model'] == expected_model)
            require(raw['model'] == attempt['returned_model'] == expected_model)
            require(request_signature(request['host'], request['path'], payload) == attempt['request_signature'])
            ledger_bytes = self.artifact(attempt['original_ledger']).read_bytes()
            require(checksum(ledger_bytes) == attempt['original_ledger_sha256'])
            rows = [json.loads(line) for line in ledger_bytes.splitlines()]
            rows = [row for row in rows if row.get('attempt_id') == attempt['attempt_id']]
            require(len(rows) == 2 and {row['phase'] for row in rows} == {'started', 'finished'})
            first = next(row for row in rows if row['phase'] == 'started')
            last = next(row for row in rows if row['phase'] == 'finished')
            require(first['sha256'] == attempt['request_sha256'] and last['sha256'] == attempt['response_sha256'])
            require(first['artifact'] == PurePosixPath(attempt['request_artifact']).name)
            require(last['artifact'] == PurePosixPath(attempt['response_artifact']).name)
            require(last['status'] == 200 and first['method'] == last['method'] == 'POST')
            require(first['host'] == last['host'] == request['host'])
            require(first['path'] == last['path'] == request['path'])
            require(first['model'] == last['model'] == payload['model'])
            proofs.append(dict(expected_model=expected_model, returned_model=raw['model'],
                               provider_host=request['host']))
        return proofs
