import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from s5_nano.auditing import openrouter_token_cost
from s5_nano.judge_budget import check_budget, finish_attempt


class JudgeBudgetTests(unittest.TestCase):
    def test_concurrent_dispatch_cannot_exceed_reserved_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'budget.json'
            path.write_text(json.dumps(dict(alert_and_pause_usd=4, reserve_per_attempt_usd=2)))
            def attempt(i):
                try:
                    check_budget('openrouter.ai', str(i))
                    return True
                except RuntimeError:
                    return False
            with patch.dict(os.environ, S5_NANO_JUDGE_BUDGET_FILE=str(path)):
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    self.assertEqual(sum(pool.map(attempt, range(8))), 2)
                check_budget('127.0.0.1', 'local')
            self.assertEqual(len(json.loads(path.read_text())['attempts']), 2)

    def test_unknown_cost_stays_reserved_and_finished_receipt_is_immutable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'budget.json'
            path.write_text(json.dumps(dict(alert_and_pause_usd=4, reserve_per_attempt_usd=2)))
            with patch.dict(os.environ, S5_NANO_JUDGE_BUDGET_FILE=str(path)):
                check_budget('api.openai.com', 'a')
                finish_attempt('api.openai.com', 'a', None, None)
                check_budget('api.openai.com', 'b')
                with self.assertRaises(RuntimeError):
                    check_budget('api.openai.com', 'c')
                finish_attempt('api.openai.com', 'b', .25, 200)
                finish_attempt('api.openai.com', 'b', None, None)
            self.assertEqual(json.loads(path.read_text())['attempts']['b']['usd'], .25)

    def test_openrouter_uses_reported_charge_and_avoids_double_counting_reasoning(self):
        usage = dict(prompt_tokens=1000, completion_tokens=200,
            prompt_tokens_details={'cached_tokens': 500, 'cache_write_tokens': 100},
            completion_tokens_details={'reasoning_tokens': 100})
        self.assertAlmostEqual(openrouter_token_cost('anthropic/claude-opus-4.6', usage)['usd'], .00825)
        usage['cost'] = .007
        self.assertEqual(openrouter_token_cost('anthropic/claude-opus-4.6', usage)['usd'], .007)
        self.assertIsNone(openrouter_token_cost('unconfirmed-model', usage)['usd'])
