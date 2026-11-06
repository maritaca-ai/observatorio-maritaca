"""Optional campaign-wide dispatch guard; this never changes judge parameters."""
import fcntl
import json
import os
from pathlib import Path
import time


def update(host, identifier, *, finish=False, amount=None, status=None):
    name = os.environ.get('S5_NANO_JUDGE_BUDGET_FILE')
    if not name or host not in ('api.openai.com', 'openrouter.ai'):
        return
    path = Path(name)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = json.loads(path.read_text())
        attempts = value.setdefault('attempts', {})
        if finish:
            old = attempts.get(identifier)
            if old and old.get('phase') == 'finished':
                return
            attempts[identifier] = dict(phase='finished', usd=amount, status=status, time=time.time())
        else:
            spent = sum(row['usd'] for row in attempts.values() if row.get('usd') is not None)
            uncertain = sum(row.get('phase') != 'finished' or row.get('usd') is None for row in attempts.values())
            if spent + (uncertain + 1) * value['reserve_per_attempt_usd'] > value['alert_and_pause_usd']:
                raise RuntimeError('Judge spending reserve reached; results preserved, further dispatch paused')
            if identifier in attempts:
                raise ValueError('Duplicate paid dispatch identity')
            attempts[identifier] = dict(phase='started', host=host, time=time.time())
        value['time'] = time.time()
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(value, indent=2) + '\n')
        tmp.chmod(0o600)
        tmp.replace(path)


def check_budget(host, identifier):
    update(host, identifier)


def finish_attempt(host, identifier, amount, status):
    update(host, identifier, finish=True, amount=amount, status=status)
