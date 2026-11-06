"""Load native definitions from the pinned public source, without unrelated harness backends.

Source revisions: ../upstream.lock.json. Runtime source and data remain in .cache/.
"""
from s5_nano.engines.pt_native import load, score_case, aggregate
