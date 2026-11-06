import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from s5_nano import harm_scorer as scorer
from s5_nano.remaining_harm import finish_classifier


class HarmFailStopTests(unittest.TestCase):
    def fixture(self, produce):
        tokenizer = SimpleNamespace(encode=lambda text, **kw: list(text[:512]),
                                    decode=lambda tokens, **kw: ''.join(tokens))
        native = SimpleNamespace(compute_results_classifier=lambda row, data, cls, params: produce(data),
                                 compute_results_hashing=lambda row, data: [{'label': 0}])
        return dict(row={'BehaviorID': 'synthetic', 'Tags': []},
                    completion={'generation': 'saved final', 'test_case': 'synthetic'}, tokenizer=tokenizer,
                    native=native, classifier=None, params={'temperature': 0.0, 'max_tokens': 1}, allow_dispatch=True)

    def test_timeout_preserves_claim_and_blocks_another_process(self):
        calls = []
        def fail(data):
            calls.append(data)
            raise TimeoutError('synthetic uncertain transport')
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            with self.assertRaises(TimeoutError):
                scorer.score_row(output, **self.fixture(fail))
            with self.assertRaisesRegex(RuntimeError, 'audit required'):
                scorer.score_row(output, **self.fixture(fail))
            self.assertEqual(len(calls), 1)

    def test_cached_native_verdict_and_clipping_remain_unchanged(self):
        calls = []
        def produce(data):
            calls.append(data)
            return [{'label': -1, 'generation': data[0]['generation']}]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            fixture = self.fixture(produce)
            fixture['completion']['generation'] = 'x' * 600
            first = scorer.score_row(output, **fixture)
            second = scorer.score_row(output, **fixture)
            self.assertEqual(first, second)
            self.assertEqual(first['label'], -1)
            self.assertEqual(first['clipped_tokens'], 512)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(calls[0][0]['generation']), 512)
            self.assertEqual(len(fixture['completion']['generation']), 600)
            fixture['completion']['generation'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'generation changed'):
                scorer.score_row(output, **fixture)

    def test_invalid_native_return_cannot_be_dispatched_again(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = self.fixture(lambda data: [])
            with self.assertRaises(IndexError):
                scorer.score_row(Path(folder), **fixture)
            with self.assertRaisesRegex(RuntimeError, 'audit required'):
                scorer.score_row(Path(folder), **fixture)

    def test_hash_only_does_not_dispatch_or_claim_classifier(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = self.fixture(lambda data: self.fail('classifier called'))
            fixture['row']['Tags'] = ['hash_check']
            fixture['allow_dispatch'] = False
            record = scorer.score_row(Path(folder), **fixture)
            self.assertEqual(record['label'], 0)
            self.assertFalse((Path(folder) / 'dispatch_claims').exists())

    def test_legacy_ledger_blocks_new_judgments_but_allows_saved_ones(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            fixture = self.fixture(lambda data: [{'label': 0}])
            saved = scorer.score_row(root, **fixture)
            (root / 'http_attempts.jsonl').write_text(json.dumps(dict(model='harmbench-classifier', phase='started')) + '\n')
            self.assertFalse(scorer.prepare_transport(root, root))
            fixture['allow_dispatch'] = False
            self.assertEqual(scorer.score_row(root, **fixture), saved)
            fixture['row']['BehaviorID'] = 'missing'
            with self.assertRaisesRegex(RuntimeError, 'Legacy.*audit'):
                scorer.score_row(root, **fixture)

    def test_transport_marker_is_validated(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            self.assertTrue(scorer.prepare_transport(root, root))
            self.assertTrue(scorer.prepare_transport(root, root))
            (root / 'classifier_transport.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                scorer.prepare_transport(root, root)

    def test_real_sdk_performs_no_retry_on_transient_error(self):
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(503, json={'error': {'message': 'synthetic transient error'}})
        with tempfile.TemporaryDirectory() as folder:
            env = dict(S5_NANO_AUDIT_DIR=folder, S5_NANO_BENCHMARK='harmbench', S5_NANO_CLASSIFIER_API_KEY='synthetic')
            with patch.dict(os.environ, env, clear=True), patch('httpx.HTTPTransport', return_value=httpx.MockTransport(respond)):
                from openai import APIStatusError
                with scorer.classifier_client('http://127.0.0.1:1/v1') as client:
                    with self.assertRaises(APIStatusError):
                        client.completions.create(model='harmbench-classifier', prompt=['synthetic'], temperature=0, max_tokens=1)
            self.assertEqual(len(calls), 1)
            rows = [json.loads(line) for line in (Path(folder) / 'http_attempts.jsonl').read_text().splitlines()]
            self.assertEqual([row['phase'] for row in rows], ['started', 'finished'])

    def ledger(self, root, phases):
        path = root / 'classifier_audit/http_attempts.jsonl'
        path.parent.mkdir(parents=True)
        path.write_text(''.join(json.dumps(dict(model='harmbench-classifier', attempt_id='one', phase=p)) + '\n' for p in phases))

    def test_uncertain_server_is_retained_for_audit(self):
        for phases in [['started'], ['started', 'failed'], ['finished']]:
            with self.subTest(phases=phases), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.ledger(root, phases)
                server = SimpleNamespace(pid=123, poll=lambda: None)
                with patch('s5_nano.remaining_harm.stop_process') as stop:
                    with self.assertRaisesRegex(RuntimeError, 'requires audit'):
                        finish_classifier(root, server)
                    stop.assert_not_called()
                self.assertEqual(json.loads((root / 'classifier_cleanup.json').read_text())['status'], 'RETAINED_FOR_AUDIT')

    def test_completed_attempts_allow_stopping_owned_server(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.ledger(root, ['started', 'finished'])
            server = SimpleNamespace(pid=123, poll=lambda: None)
            with patch('s5_nano.remaining_harm.stop_process') as stop:
                finish_classifier(root, server)
                stop.assert_called_once_with(server)
            self.assertEqual(json.loads((root / 'classifier_cleanup.json').read_text())['status'], 'STOPPED_AFTER_DRAIN')

    def test_corrupt_audit_and_dead_server_require_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.ledger(root, ['started'])
            (root / 'classifier_audit/http_attempts.jsonl').write_text('{incomplete')
            with patch('s5_nano.remaining_harm.stop_process') as stop:
                with self.assertRaisesRegex(RuntimeError, 'requires audit'):
                    finish_classifier(root, SimpleNamespace(pid=123, poll=lambda: 1))
                stop.assert_not_called()
            self.assertEqual(json.loads((root / 'classifier_cleanup.json').read_text())['status'], 'EXITED_AUDIT_REQUIRED')


if __name__ == '__main__':
    unittest.main()
