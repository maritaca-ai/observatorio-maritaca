"""Offline tests for scoring, resume safety, exact pairing and provider adapters."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from draco_benchmark.api import Client, make_body
from draco_benchmark.cli import canonical_protocol, parser
from draco_benchmark.comparison import binary, compare_pair
from draco_benchmark.core import (criteria, digest, freeze, judge_messages, load_dataset,
    parse_grade, read_json, score, select_cases, store_report, summarize, validate_cases, write_json)
from draco_benchmark.runner import generate, import_reports, judge


CASE = {'id': 'test-task', 'domain': 'Finance', 'problem': 'What is the margin?', 'answer': json.dumps({
    'sections': [{'id': 'accuracy', 'criteria': [
        {'id': 'margin', 'weight': 10, 'requirement': 'States margin of 20%.'},
        {'id': 'error', 'weight': -50, 'requirement': 'Claims margin is 50%.'}]}]})}


class CoreTests(unittest.TestCase):
    def test_penalties_and_per_task_clipping(self):
        items = criteria(CASE)
        self.assertEqual(score(items, ['MET', 'UNMET'])['score'], 100)
        self.assertEqual(score(items, ['MET', 'MET']), {'raw_score': -40, 'positive_weight_sum': 10, 'score': 0})
        self.assertEqual(score(items, ['UNMET', 'UNMET'])['score'], 0)
        with self.assertRaises(ValueError):
            score(items, ['MET'])

    def test_negative_means_error_present(self):
        prompt = judge_messages(CASE, 'Avoid 50%.', criteria(CASE)[1])
        self.assertIn('<criterion_type>\nnegative', prompt[1]['content'])
        self.assertNotIn('-50', prompt[1]['content'])
        self.assertNotIn('test-task', prompt[1]['content'])

    def test_strict_grade(self):
        for value in ('{}', '{"criterion_status":true,"explanation":"yes"}',
                      '{"criterion_status":"MET","explanation":""}', '[]'):
            with self.assertRaises(ValueError):
                parse_grade(value)
        self.assertEqual(parse_grade('```json\n{"criterion_status":"UNMET","explanation":"Absent"}\n```')['criterion_status'], 'UNMET')

    def test_dataset_schema_and_selection(self):
        cases = [CASE, dict(CASE, id='another-task'), dict(CASE, id='third-task', domain='Medicine')]
        validate_cases(cases)
        self.assertEqual(select_cases(cases, 'per-domain'), select_cases(cases[::-1], 'per-domain'))
        with self.assertRaises(ValueError):
            validate_cases([CASE, CASE])

    def test_corrupt_dataset_fails_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'data.jsonl'
            path.write_text(json.dumps(CASE))
            with patch('draco_benchmark.core.urlopen') as network:
                with self.assertRaises(ValueError):
                    load_dataset(path)
                network.assert_not_called()

    def test_freeze_blocks_changed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'manifest.json'
            freeze(path, {'a': 1})
            freeze(path, {'a': 1})
            with self.assertRaises(ValueError):
                freeze(path, {'a': 2})

    def test_import_and_report_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'reports.jsonl'
            source.write_text(json.dumps({'case_id': CASE['id'], 'generator': 'provider/model', 'text': '20%'})+'\n')
            import_reports(root, [CASE], source)
            import_reports(root, [CASE], source)
            self.assertEqual(len(list((root/'answers').glob('*.json'))), 1)
            source.write_text(json.dumps({'case_id': CASE['id'], 'generator': 'provider/model', 'text': '50%'})+'\n')
            with self.assertRaises(ValueError):
                import_reports(root, [CASE], source)

    def test_default_is_s5_xhigh(self):
        args = parser().parse_args(['--run-id', 'sample'])
        self.assertEqual((args.judge_model, args.judge_effort, args.judge_provider),
                         ('S5', 'xhigh', 'maritaca'))
        self.assertEqual(args.selection, 'full')

    def test_closed_book_and_imported_runs_do_not_mix_in_consolidation(self):
        summary = {'generation_configs': [{'research': True}], 'imported': False,
            'by_generator': {'S5': {}}, 'config': {'model': 'S5',
            'effort': 'xhigh', 'provider': 'maritaca', 'max_tokens': 8192}}
        self.assertTrue(canonical_protocol(summary, 'full'))
        self.assertFalse(canonical_protocol(summary, 'per-domain'))
        summary['generation_configs'][0]['research_backend'] = 'serper'
        self.assertFalse(canonical_protocol(summary, 'full'))
        del summary['generation_configs'][0]['research_backend']
        summary['generation_configs'][0]['research'] = False
        self.assertFalse(canonical_protocol(summary, 'full'))
        summary['generation_configs'][0]['research'] = True
        summary['imported'] = True
        self.assertFalse(canonical_protocol(summary, 'full'))

    def test_provider_bodies_and_no_judge_browsing(self):
        messages = judge_messages(CASE, '20%', criteria(CASE)[0])
        endpoint, body = make_body('maritaca', 'S5', 'xhigh', messages, 8192)
        self.assertEqual(body['reasoning_effort'], 'xhigh')
        self.assertFalse(body['web_search'])
        self.assertNotIn('tools', body)
        endpoint, body = make_body('openrouter', 'openai/gpt-6-luna', 'medium', messages, 8192)
        self.assertEqual(body['reasoning'], {'effort': 'medium'})
        self.assertTrue(body['provider']['require_parameters'])
        self.assertFalse(body['provider']['allow_fallbacks'])
        self.assertNotIn('tools', body)
        endpoint, body = make_body('openrouter', 'openai/gpt-6-luna', 'medium', messages, 32768, research=True)
        self.assertEqual(endpoint, '/responses')
        self.assertEqual(body['tools'][0]['parameters']['engine'], 'native')


class FakeClient:
    calls = []
    def __init__(self, *args, **kwargs):
        pass
    async def close(self):
        pass
    async def request(self, endpoint, body, attempt_dir, parse):
        self.calls.append(body)
        if 'criterion_type' in body.get('messages', [{}, {}])[1].get('content', ''):
            text = '{"criterion_status":"MET","explanation":"Present."}'
        else:
            text = 'Margin 20%.'
        return parse(text), {'usage': {}}, 'fake-attempt.json', 0.0


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_incremental_judging_reuses_votes_and_rejects_changed_or_removed_reports(self):
        with tempfile.TemporaryDirectory() as directory, patch('draco_benchmark.runner.Client', FakeClient):
            root = Path(directory)
            cases = [CASE, dict(CASE, id='second-task')]
            config = {'provider': 'maritaca', 'model': 'S5', 'effort': 'xhigh', 'max_tokens': 8192}
            FakeClient.calls = []
            store_report(root, CASE['id'], 'candidate', 'First answer')
            await judge(root, cases, config, 's5', 'dummy', allow_new_reports=True)
            self.assertEqual(len(FakeClient.calls), 2)
            self.assertFalse(summarize(root, cases, 's5')['complete'])
            store_report(root, 'second-task', 'candidate', 'Second answer')
            with self.assertRaises(ValueError):
                await judge(root, cases, config, 's5', 'dummy')
            await judge(root, cases, config, 's5', 'dummy', allow_new_reports=True)
            await judge(root, cases, config, 's5', 'dummy', allow_new_reports=True)
            self.assertEqual(len(FakeClient.calls), 4)
            self.assertTrue(summarize(root, cases, 's5')['complete'])
            self.assertEqual(len(list((root/'judgments/s5/input_history').glob('*/inputs.json'))), 1)
            path = next((root/'answers').glob('*.json'))
            row = read_json(path)
            write_json(path, dict(row, text='Changed', text_sha256=digest('Changed')))
            with self.assertRaises(ValueError):
                await judge(root, cases, config, 's5', 'dummy', allow_new_reports=True)
            write_json(path, row)
            path.unlink()
            with self.assertRaises(ValueError):
                await judge(root, cases, config, 's5', 'dummy', allow_new_reports=True)
            self.assertEqual(len(FakeClient.calls), 4)

    async def test_generate_judge_resume_and_changed_effort(self):
        with tempfile.TemporaryDirectory() as directory, patch('draco_benchmark.runner.Client', FakeClient):
            root = Path(directory)
            FakeClient.calls = []
            config = {'provider': 'maritaca', 'model': 'S5', 'effort': 'medium', 'max_tokens': 8192, 'research': True}
            await generate(root, [CASE], config, 'dummy')
            self.assertNotIn('Claims margin', str(FakeClient.calls))
            await generate(root, [CASE], config, 'dummy')
            self.assertEqual(len(FakeClient.calls), 1)
            judge_config = {'provider': 'openrouter', 'model': 'openai/gpt-6-luna', 'effort': 'medium', 'max_tokens': 8192}
            await judge(root, [CASE], judge_config, 'luna', 'dummy')
            await judge(root, [CASE], judge_config, 'luna', 'dummy')
            self.assertEqual(len(FakeClient.calls), 3)
            result = summarize(root, [CASE], 'luna')
            self.assertTrue(result['complete'])
            self.assertEqual(result['reports'][0]['score'], 0)
            with self.assertRaises(ValueError):
                await judge(root, [CASE], dict(judge_config, effort='xhigh'), 'luna', 'dummy')
            self.assertEqual(len(FakeClient.calls), 3)
            # Removing one grade cannot silently produce a full aggregate score.
            next((root/'judgments/luna').glob('test-task_*/*.json')).unlink()
            self.assertFalse(summarize(root, [CASE], 'luna')['complete'])

    async def test_retry_preserves_attempts_and_never_auth(self):
        replies = [
            {'model': 'S5', 'choices': [{'finish_reason': 'length', 'message': {'content': ''}}]},
            {'model': 'S5', 'choices': [{'finish_reason': 'stop', 'message': {'content': '{"criterion_status":"MET","explanation":"Present"}'}}]},
        ]
        client = Client('maritaca', 'test-secret-not-for-logs')
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=replies.pop(0))))
        with tempfile.TemporaryDirectory() as directory, patch('draco_benchmark.api.asyncio.sleep', return_value=None):
            root = Path(directory)
            _, body = make_body('maritaca', 'S5', 'xhigh', [], 8192)
            result, _, _, _ = await client.request('/chat/completions', body, root, parse_grade)
            self.assertEqual(result['criterion_status'], 'MET')
            self.assertEqual(read_json(root/'0001.json')['request']['max_tokens'], 8192)
            self.assertEqual(read_json(root/'0002.json')['request']['max_tokens'], 16384)
            self.assertNotIn('test-secret', ''.join(p.read_text() for p in root.glob('*.json')))
        await client.close()

    async def test_wrong_model_never_accepted(self):
        client = Client('maritaca', 'dummy')
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            'model': 'different', 'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}]})))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                await client.request('/chat/completions', {'model': 'S5'}, Path(directory), str)
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 1)
        await client.close()


class ComparisonTests(unittest.TestCase):
    def summary(self, label):
        return {'judge': label, 'complete': True,
            'reports': [{'report_id': f'r{i}', 'case_id': f'c{i}', 'generator': 'model',
                         'text_sha256': str(i), 'score': i*25, 'flags': []} for i in range(4)],
            'pairs': [{'report_id': f'r{i}', 'criterion_index': 0, 'criterion': {'weight': 10},
                       'criterion_status': 'MET' if i > 1 else 'UNMET', 'explanation': 'x'} for i in range(4)]}

    def test_identical_and_reversed_agreement(self):
        self.assertEqual(binary([0, 0, 1, 1], [0, 0, 1, 1])['kappa'], 1)
        self.assertEqual(binary([0, 0, 1, 1], [1, 1, 0, 0])['kappa'], -1)
        result = compare_pair(self.summary('a'), self.summary('b'), bootstrap=30)
        self.assertAlmostEqual(result['scores']['pearson_r'], 1)
        self.assertEqual(result['task_cluster_bootstrap_95ci']['agreement'], [1, 1])

    def test_mismatched_text_and_partial_judge_rejected(self):
        a, b = self.summary('a'), self.summary('b')
        b['reports'][0]['text_sha256'] = 'different'
        with self.assertRaises(ValueError):
            compare_pair(a, b)
        b = self.summary('b')
        b['complete'] = False
        with self.assertRaises(ValueError):
            compare_pair(a, b)


if __name__ == '__main__':
    unittest.main()
