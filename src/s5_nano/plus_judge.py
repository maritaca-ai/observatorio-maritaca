"""Explicit BrowseComp-Plus judge identity; immutable native prompt and parser."""
import hashlib
import fcntl
import importlib
import json
from pathlib import Path
import sys
import uuid

from .prepare import REPO

DEFAULT_PROFILE = REPO / 'profiles/judges/browsecomp-plus-gpt6-luna-medium.json'
FORK = REPO / 'benchmarks/agentico/browsecomp_plus/fork'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def profile(path=DEFAULT_PROFILE):
    value = json.loads(Path(path).read_text())
    if not (value['api'] == 'Responses' and value['reasoning_effort'] == 'medium'
            and value['model'] == 'gpt-6-luna' and value['reasoning_summary'] == 'detailed'
            and value['max_output_tokens'] == 1024 and value['denominator'] == 100
            and value['parsed_judgment_attempts'] == 1 and value['sdk_max_retries'] == 2):
        raise ValueError('Unexpected BrowseComp-Plus judge profile')
    return value


def load_grader():
    sys.path.insert(0, str(FORK))
    grader = importlib.import_module('grader')
    if Path(grader.__file__).resolve() != (FORK / 'grader.py').resolve():
        raise ValueError('Unexpected grader module')
    return grader


def effective_protocol(original, selected):
    value = dict(original)
    value.update(judge=selected['model'], judge_api=selected['api'],
                 judge_max_output_tokens=selected['max_output_tokens'],
                 judge_reasoning_effort=selected['reasoning_effort'],
                 judge_reasoning_summary=selected['reasoning_summary'],
                 judge_profile_id=selected['id'],
                 judge_failure_policy=selected['incomplete_judge_policy'])
    return value


def judge_response(job, record, client, native, output, selected, *, retry_failed=False):
    """Reuse valid verdicts; explicitly retry a pending verdict once per call."""
    folder=Path(output)/'judgments';folder.mkdir(parents=True,exist_ok=True)
    with (folder/(digest(job['query_id'])+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _judge_response(job,record,client,native,output,selected,retry_failed=retry_failed)


def archive_pending(output, path, cached):
    """Keep the exact failed record and raw response before another attempt."""
    key=path.stem;checksum=sha(path);folder=output/'judge_attempts'/key/checksum
    folder.mkdir(parents=True,exist_ok=True)
    files={}
    sources={'judgment.json':path}
    if cached.get('raw_sha256'):
        raw=output/'judge_raw'/(str(cached['query_id'])+'.json')
        if sha(raw)!=cached['raw_sha256']:raise ValueError('Pending raw judgment checksum differs')
        sources['raw.json']=raw
    for name,source in sources.items():
        data=source.read_bytes();target=folder/name
        if target.exists():
            if target.read_bytes()!=data:raise ValueError('Archived judgment collision')
        else:
            with target.open('xb') as stream:stream.write(data)
            target.chmod(0o600)
        files[str(target.relative_to(output))]=sha(target)
    return dict(judgment_sha256=checksum,files=files)


def _judge_response(job, record, client, native, output, selected, *, retry_failed):
    output = Path(output)
    prompt = native.create_judge_prompt(job['query'], record['final'], job['answer'])
    identity = dict(query_id=job['query_id'], prompt_sha256=digest(prompt),
                    final_sha256=digest(record['final']), profile_sha256=digest(selected),
                    grader_sha256=sha(FORK / 'grader.py'), template_sha256=sha(FORK / 'prompts.py'))
    path = output / 'judgments' / (digest(job['query_id']) + '.json')
    previous=[]
    if path.exists():
        cached = json.loads(path.read_text())
        if cached.get('identity') != identity:
            raise ValueError('Judge cache identity changed; use a new variant destination')
        if not cached.get('judge_error') or not retry_failed:
            return cached
        if client is None:raise ValueError('Pending judgment recovery requires an explicit judge client')
        previous=[*cached.get('previous_attempts',[]),archive_pending(output,path,cached)]
    result = dict(query_id=job['query_id'], identity=identity, judge=selected['model'],
                  judge_profile_id=selected['id'], reasoning_effort=selected['reasoning_effort'],
                  correct=False, answered=bool(record['final']), judge_error=None, usage={})
    if previous:result['previous_attempts']=previous
    if not record['final']:
        result['label'] = 'unanswered'
    else:
        try:
            response = native.call_openai_judge(client, prompt, selected['model'],
                selected['max_output_tokens'], reasoning_effort=selected['reasoning_effort'])
            raw = response.model_dump(mode='json')
            raw_path = output / 'judge_raw' / (str(job['query_id']) + '.json')
            save(raw_path, raw)
            result.update(raw_sha256=sha(raw_path), usage=raw.get('usage') or {},
                          returned_model=raw.get('model'), response_id=raw.get('id'),
                          response_status=raw.get('status'), returned_reasoning=raw.get('reasoning'))
            if raw.get('status') != 'completed':
                raise ValueError('Incomplete judge response; a final score is withheld')
            if raw.get('model') != selected['model']:
                raise ValueError('Unexpected returned judge model')
            if (raw.get('reasoning') or {}).get('effort') != selected['reasoning_effort']:
                raise ValueError('Judge did not confirm the requested reasoning effort')
            parsed = native.parse_judge_response(response.output_text)
            if type(parsed['correct']) is not bool:
                raise ValueError('Missing binary judge verdict')
            result.update(correct=parsed['correct'], parsed=parsed)
        except Exception as exc:
            result['judge_error'] = dict(type=type(exc).__name__, status_code=getattr(exc, 'status_code', None))
    save(path, result)
    return result


def summarize(rows, selected):
    if len(rows) != 100 or len({x['query_id'] for x in rows}) != 100:
        raise ValueError('All 100 selected queries must remain in the denominator')
    for row in rows:
        error = row['generation'].get('error') or {}
        if isinstance(error, dict):
            message = str(error.get('message', '')).lower()
            if ('out of memory' in message or error.get('type') in (
                    'InternalServerError', 'APIConnectionError', 'APITimeoutError',
                    'RateLimitError', 'AuthenticationError', 'PermissionDeniedError')):
                raise ValueError('Generation infrastructure failure; recover affected cases before a final score')
    if any(x['judge']['judge_error'] for x in rows):
        raise ValueError('Pending judge verdicts; no final score can be published')
    correct = sum(x['judge']['correct'] for x in rows)
    answered = sum(x['judge']['answered'] for x in rows)
    categories = dict(answered=answered, failed=0, no_answer_at_limit=0, no_answer_before_limit=0)
    for row in rows:
        if row['judge']['answered']:
            continue
        generation = row['generation']
        category = ('failed' if generation['status'] == 'failed' else
                    'no_answer_at_limit' if generation['iterations'] >= 100 else 'no_answer_before_limit')
        categories[category] += 1
    return dict(status='FINAL', n=100, correct=correct, score=float(correct),
                metric_name='accuracy_percent_full_denominator', answered=answered,
                response_rate=float(answered), accuracy_given_response=100*correct/answered if answered else None,
                generation_errors=sum(x['generation']['status'] == 'failed' for x in rows), judge_errors=0,
                stop_categories=categories,
                invented_tool_calls=sum(x['generation']['invented_tool_calls'] for x in rows),
                judge=selected['model'], judge_reasoning_effort=selected['reasoning_effort'],
                judge_profile_id=selected['id'], protocol_id=selected['id'],
                judge_usage={k:sum(x['judge']['usage'].get(k,0) or 0 for x in rows)
                             for k in ('input_tokens','output_tokens','total_tokens')}, completion_coverage=1.0)
