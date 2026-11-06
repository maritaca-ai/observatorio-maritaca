"""Keep the recorder alive until every dispatched candidate attempt is closed."""
import json
from pathlib import Path
import time

from .remaining_core import save


def pending_http(runtime):
    path = Path(runtime) / 'candidate_attempts.jsonl'
    if not path.exists():
        return set()
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    # A client-side failure does not establish whether the upstream call ended.
    started = {row['attempt_id'] for row in rows if row['phase'] == 'started'}
    finished = {row['attempt_id'] for row in rows if row['phase'] == 'finished'}
    if finished - started:
        raise ValueError('Candidate completion without a recorded start; audit required')
    return started - finished


def drain_proxy(runtime, proxy):
    runtime = Path(runtime)
    last = None
    while True:
        try:
            pending = pending_http(runtime)
            state = dict(status='WAITING' if pending else 'DRAINED', pending=len(pending))
        except (OSError, ValueError, KeyError, TypeError):
            # A concurrent append may be incomplete; an unreadable audit cannot
            # authorize termination. Persistent corruption requires operator audit.
            pending = None
            state = dict(status='LEDGER_AUDIT_REQUIRED', pending=None)
        alive = proxy.poll() is None
        if not alive and pending != set():
            save(runtime / 'proxy_drain.json', dict(state, status='PROXY_EXITED_AUDIT_REQUIRED',
                                                  time=time.time()))
            raise RuntimeError('Proxy exited before candidate ledger closed; audit required')
        if state != last:
            save(runtime / 'proxy_drain.json', dict(state, time=time.time()))
            last = state
        if pending == set():
            if alive:
                proxy.terminate()
                proxy.wait(timeout=10)
            return
        # Deliberately do not kill a recorder with unresolved upstream calls.
        time.sleep(1)
