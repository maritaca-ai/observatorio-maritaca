import json
import os
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from s5_nano import remaining_core as core


class FailStopTests(unittest.TestCase):
    def setUp(self):
        profile_patch = patch.object(core, 'PROFILE', {'context_length': 131072})
        profile_patch.start()
        self.addCleanup(profile_patch.stop)

    def run_fixture(self, root, create):
        run = object.__new__(core.Run)
        run.out, run.task = Path(root), 'synthetic'
        run.identity = {'model': 'synthetic', 'profile': {'mode': 'instruct'}}
        run.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        run.judge_client = None
        return run

    def test_success_cache_is_reused_without_new_dispatch(self):
        with tempfile.TemporaryDirectory() as root:
            calls = []
            def create(**kwargs):
                calls.append(kwargs)
                return types.SimpleNamespace(model_dump=lambda **_: {'model':'synthetic','choices':[{'message':{'content':'saved','reasoning_content':'kept'}}]})
            run = self.run_fixture(root, create)
            self.assertEqual(run.ask('1', [])['final'], 'saved')
            self.assertEqual(run.ask('1', [])['raw']['choices'][0]['message']['reasoning_content'], 'kept')
            self.assertEqual(len(calls), 1)

    def test_timeout_cannot_be_reissued_even_after_new_runner(self):
        with tempfile.TemporaryDirectory() as root:
            calls = []
            def create(**kwargs):
                calls.append(kwargs)
                raise TimeoutError('uncertain synthetic HTTP')
            with self.assertRaises(TimeoutError):
                self.run_fixture(root, create).ask('1', [])
            with self.assertRaisesRegex(RuntimeError, 'audit required'):
                self.run_fixture(root, create).ask('1', [])
            self.assertEqual(len(calls), 1)

    def test_judge_failure_preserved_and_not_reissued(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.run_fixture(root, None)
            calls = []
            def produce():
                calls.append(1)
                raise TimeoutError('synthetic judge timeout')
            with self.assertRaises(TimeoutError):
                run.judgment('1', {}, produce, bool)
            with self.assertRaisesRegex(RuntimeError, 'audit required'):
                run.judgment('1', {}, produce, bool)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(list(run.out.glob('judgment_attempts/*/*.json'))), 1)

    def test_completed_judge_is_reused(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.run_fixture(root, None)
            calls = []
            def produce():
                calls.append(1)
                return {'valid':True}
            for _ in range(2):
                self.assertEqual(run.judgment('1', {}, produce, bool), {'valid':True})
            self.assertEqual(len(calls), 1)

    def test_no_cases_after_failure_and_inflight_drained(self):
        with tempfile.TemporaryDirectory() as root, patch.object(core, 'WORKERS', 2):
            run = self.run_fixture(root, None)
            run.rows = list(range(20)); calls = []; drained = threading.Event(); both = threading.Barrier(2)
            def one(row):
                calls.append(row); both.wait(timeout=2)
                if row == 0:
                    raise RuntimeError('synthetic case failure')
                time.sleep(.05); drained.set(); return row
            with self.assertRaisesRegex(RuntimeError, 'case failure'):
                run.parallel(one)
            self.assertEqual(sorted(calls), [0, 1])
            self.assertTrue(drained.is_set())

    def test_population_complete_with_bounded_concurrency(self):
        with tempfile.TemporaryDirectory() as root, patch.object(core, 'WORKERS', 3):
            run = self.run_fixture(root, None); run.rows = list(range(23))
            self.assertEqual(sorted(run.parallel(lambda x:x)), run.rows)

    def test_candidate_and_judge_sdk_retries_are_disabled(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'S5_NANO_PROXY_URL':'http://invalid.local','OPENAI_API_KEY':'synthetic'}):
            run = self.run_fixture(root, None); run.client = None
            args = []
            def factory(**kwargs):
                args.append(kwargs)
                return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(
                    create=lambda **_:types.SimpleNamespace(model_dump=lambda **_: {'model':'synthetic','choices':[{'message':{'content':'saved'}}]}))))
            with patch.object(core, 'OpenAI', factory):
                run.ask('1', []); run.paid_client()
            self.assertEqual([x['max_retries'] for x in args], [0, 0])

    def test_claim_is_exclusive(self):
        with tempfile.TemporaryDirectory() as root:
            core.claim_dispatch(Path(root), 'candidate', 'fixed')
            with self.assertRaisesRegex(RuntimeError, 'audit required'):
                core.claim_dispatch(Path(root), 'candidate', 'fixed')

    def test_legacy_failed_judgment_without_claim_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.run_fixture(root, None)
            identity = dict(case='1', details={}, run=run.identity)
            path = run.out / 'judgment_attempts' / core.digest(identity) / 'legacy.json'
            core.save(path, dict(identity=identity, judge_error='invalid_verdict'))
            def forbidden():
                self.fail('A historical invalid judgment must not be repeated')
            with self.assertRaisesRegex(RuntimeError, 'audit required'):
                run.judgment('1', {}, forbidden, bool)

    def test_invalid_judgment_is_preserved_and_not_reissued(self):
        with tempfile.TemporaryDirectory() as root:
            run = self.run_fixture(root, None)
            calls = []
            def produce():
                calls.append(1)
                return {'valid': False}
            with self.assertRaisesRegex(RuntimeError, 'Pending judgment'):
                run.judgment('1', {}, produce, lambda x: x['valid'])
            with self.assertRaisesRegex(RuntimeError, 'audit required'):
                run.judgment('1', {}, produce, lambda x: x['valid'])
            self.assertEqual(calls, [1])

    def test_none_row_is_not_a_population_terminator(self):
        with tempfile.TemporaryDirectory() as root, patch.object(core, 'WORKERS', 1):
            run = self.run_fixture(root, None)
            run.rows = [None, 0, 'last']
            self.assertEqual(run.parallel(lambda x: x), run.rows)


if __name__ == '__main__':
    unittest.main()
