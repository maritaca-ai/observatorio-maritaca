"""Offline context checks against the pinned native LongBench request builder."""
import ast
import copy
import json
import os
from pathlib import Path
import re
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from s5_nano.longbench_context import input_budget, render_native_context

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'benchmarks/contexto_longo/longbench_v2/fork/pred.py'


def definitions(path, names, bindings=None):
    module = ModuleType('native')
    module.__dict__.update(bindings or {})
    nodes = [node for node in ast.parse(path.read_text()).body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), module.__dict__)
    return module


class Tokenizer:
    def encode(self, text):
        return list(map(ord, text))

    def decode(self, ids, **kwargs):
        return ''.join(map(chr, ids))

    def apply_chat_template(self, messages, **kwargs):
        self.kwargs = kwargs
        content = messages[0]['content']
        return [0] * (4096 if 'OVERFLOW' in content else len(content) + 12)


class LongBenchContextTests(unittest.TestCase):
    def setUp(self):
        self.native = definitions(SOURCE, ['query_llm', 'extract_answer'], dict(re=re, time=time))
        self.tokenizer = Tokenizer()
        self.profile = dict(context_length=4096, max_tokens=None, enable_thinking=True,
                            chat_template_kwargs={'custom': 'preserved'})

    def render(self, prompt, budget=3584):
        return render_native_context(self.native, prompt, self.tokenizer,
                                     'synthetic', self.profile, budget)

    def test_native_truncation_payload_and_profile_are_preserved(self):
        before = copy.deepcopy(self.profile)
        prompt = 'a' * 4000 + 'b' * 4000
        request, evidence = self.render(prompt)
        self.assertEqual(request, dict(model='synthetic', messages=[dict(role='user', content='a'*1792+'b'*1792)], temperature=.1, max_tokens=128))
        self.assertEqual(evidence['generation_space'], 500)
        self.assertIsNone(evidence['profile_max_tokens'])
        self.assertEqual(self.profile, before)
        self.assertTrue(self.tokenizer.kwargs['enable_thinking'])
        self.assertIs(self.tokenizer.kwargs['return_dict'], False)
        self.assertEqual(self.tokenizer.kwargs['custom'], 'preserved')

    def test_batch_mapping_cannot_be_counted_as_tokens(self):
        self.tokenizer.apply_chat_template = lambda *a, **kw: {'input_ids':[0]*4096, 'attention_mask':[1]*4096}
        with self.assertRaisesRegex(ValueError, 'flat list'):
            self.render('x')

    def test_short_input_is_not_padded_or_truncated(self):
        request, evidence = self.render('Short question')
        self.assertEqual(request['messages'][0]['content'], 'Short question')
        self.assertFalse(evidence['truncated'])

    def test_actual_serialization_rejects_overflow_even_if_nominal_budget_fits(self):
        with self.assertRaisesRegex(ValueError, 'serialized prompt'):
            self.render('OVERFLOW')

    def test_fixed_output_limit_is_not_reduced(self):
        self.profile['max_tokens'] = 501
        with self.assertRaisesRegex(ValueError, 'generation space'):
            self.render('x' * 10000)
        self.assertEqual(self.profile['max_tokens'], 501)

    def test_null_is_not_replaced_by_native_128(self):
        self.tokenizer.apply_chat_template = lambda *a, **kw: [0] * 4095
        _, evidence = self.render('x')
        self.assertEqual(evidence['generation_space'], 1)
        self.assertEqual(evidence['native_requested_max_tokens'], 128)
        self.assertIsNone(evidence['profile_max_tokens'])

    def test_budget_must_be_explicit_and_valid(self):
        for policy in [{'input_budgets':{}}, {'input_budgets':{'4096':4096}}, {'input_budgets':{'4096':True}}]:
            with self.assertRaises(ValueError):input_budget(self.profile, policy)
        self.assertEqual(input_budget(self.profile, {'input_budgets':{'4096':3584}}), 3584)

    def evaluator(self):
        module = definitions(ROOT/'src/s5_nano/remaining_knowledge.py', ['longbench'],
            dict(definitions=definitions, re=re, time=SimpleNamespace(sleep=Mock()), os=os, Path=Path,
                 SimpleNamespace=SimpleNamespace,
                 PROFILE=self.profile, input_budget=input_budget, render_native_context=render_native_context,
                 digest=lambda value:'test-profile-digest', save=self.save))
        return module.longbench

    @staticmethod
    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def run_case(self, preflight, overflow=False, duplicate=False, dispatch=False, transport_error=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);(root/'sources').mkdir();(root/'inputs/prompts').mkdir(parents=True)
            (root/'sources/pred.py').write_bytes(SOURCE.read_bytes())
            (root/'inputs/prompts/0shot.txt').write_text('$DOC$ $Q$ $C_A$ $C_B$ $C_C$ $C_D$')
            (root/'chat.jinja').write_text('synthetic')
            rows=[dict(_id=str(i),context='context',question='question',choice_A='a',choice_B='b',choice_C='c',choice_D='d',answer='D',difficulty='easy',length='short') for i in range(503)]
            if overflow:rows[-1]['context']='OVERFLOW'
            if duplicate:rows[-1]['_id']=rows[0]['_id']
            run=SimpleNamespace(root=root, out=root/'out', rows=rows, identity={'model':'synthetic'},manifest={'protocol':{'context_policy':{'input_budgets':{'4096':3584}}}},ask=Mock(side_effect=AssertionError('No inference allowed')))
            if dispatch:
                run.ask=Mock(return_value={'final':'The correct answer is (D)'})
                run.parallel=lambda one:list(map(one,rows))
                run.finish=Mock()
            if transport_error:
                run.ask=Mock(side_effect=RuntimeError('synthetic transport failure'))
                run.parallel=lambda one:one(rows[0])
            tokenizer=SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a,**kw:self.tokenizer))
            with patch.dict('sys.modules', {'transformers':tokenizer}), patch.dict(os.environ, {'S5_NANO_TOKENIZER':'unused','S5_NANO_CHAT_TEMPLATE':str(root/'chat.jinja')}):
                if transport_error:
                    with self.assertRaisesRegex(RuntimeError,'synthetic transport failure'):
                        self.evaluator()(run,preflight=False)
                elif overflow or duplicate:
                    with self.assertRaises(ValueError):self.evaluator()(run,preflight=preflight)
                else:
                    self.evaluator()(run,preflight=preflight)
                    if preflight:
                        self.assertTrue(json.loads((root/'out/preflight.json').read_text())['all_serialized_contexts_validated'])
                    self.assertEqual(len(json.loads((root/'out/context_preflight_rows.json').read_text())),503)
            if transport_error:
                self.assertEqual(run.ask.call_count,5)
            elif dispatch:
                self.assertEqual(run.ask.call_count,503)
                for i,call in enumerate(run.ask.call_args_list):
                    self.assertEqual(call.args,(str(i),[{'role':'user','content':'context question a b c d'}]))
                    self.assertEqual(call.kwargs,{'temperature':.1,'max_tokens':128})
                result,scored=run.finish.call_args.args
                self.assertEqual(result['score'],100)
                self.assertEqual(len(scored),503)
                self.assertTrue(all(row['prediction']=='D' and row['correct'] for row in scored))
            else:
                run.ask.assert_not_called()

    def test_preflight_validates_all_503_without_a_model_client(self):
        self.run_case(preflight=True)

    def test_late_context_failure_blocks_the_whole_dispatch(self):
        self.run_case(preflight=False,overflow=True)

    def test_duplicate_population_identity_blocks_dispatch(self):
        self.run_case(preflight=False,duplicate=True)

    def test_success_preserves_native_requests_and_scoring(self):
        self.run_case(preflight=False,dispatch=True)

    def test_historical_retry_loop_and_error_propagation_are_unchanged(self):
        self.run_case(preflight=False,transport_error=True)

    def test_campaign_budget_map_is_unchanged_and_has_no_4k_entry(self):
        proposal=json.loads((ROOT/'profiles/benchmarks.json').read_text())
        self.assertEqual(proposal['benchmarks']['longbench_v2']['context_policy']['input_budgets'],
                         {'65536':60000,'131072':120000,'262144':240000})


if __name__ == '__main__':
    unittest.main()
