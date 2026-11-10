import copy
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

from s5_nano.tucano_transport import (
    SAMPLING, check_upstream, complete, interpret_completion, json_http,
    make_handler, parse_output, prepare_request, validate_profile, TucanoHTTPServer,
)

ROOT = Path(__file__).resolve().parents[1]


def profile(mode='thinking'):
    return json.loads((ROOT / 'profiles/models/tucano2-qwen-3.7b' / f'{mode}.json').read_text())


class Tokenizer:
    eos_token_id = 2

    def apply_chat_template(self, messages, tools=None, **kwargs):
        return json.dumps(dict(messages=messages, tools=tools), ensure_ascii=False)

    def encode(self, text, **kwargs):
        return [ord(c) + 10 for c in text]

    def decode(self, ids, **kwargs):
        return ''.join('<|im_end|>' if t == 2 else chr(t - 10) for t in ids)


def body(p=None, **extra):
    return dict(model=(p or profile())['model'], messages=[dict(role='user', content='Pergunta sintética.')], **extra)


def response(request, text, tokenizer=None, finish='stop', stop=None):
    tok = tokenizer or Tokenizer()
    ids = tok.encode(text, add_special_tokens=False)
    if finish == 'stop' and stop is None:
        ids += [tok.eos_token_id]
    return dict(id='cmpl-synthetic', created=1, model=request['model'],
                choices=[dict(index=0, text=tok.decode(ids), token_ids=ids,
                              prompt_token_ids=request['prompt'], finish_reason=finish, stop_reason=stop)],
                usage=dict(prompt_tokens=len(request['prompt']), completion_tokens=len(ids),
                           total_tokens=len(request['prompt']) + len(ids)))


TOOLS = [dict(type='function', function=dict(name='lookup', parameters=dict(type='object')))]


class Parsing(unittest.TestCase):
    def test_plain_and_multiple_explicit_spans_preserve_spaces(self):
        x = parse_output('  Antes<think>um</think>\nMeio<think>dois</think>Fim ', thinking=True)
        self.assertEqual(x['content'], '  Antes\nMeioFim ')
        self.assertEqual(x['reasoning_content'], 'umdois')
        self.assertEqual(parse_output('  Final\n', thinking=True)['content'], '  Final\n')

    def test_instruct_keeps_literal_thinking_tags(self):
        text = 'Exemplo: <think>literal</think>\n'
        x = parse_output(text, thinking=False)
        self.assertEqual((x['content'], x['reasoning_content']), (text, ''))

    def test_unfinished_reasoning_does_not_become_final_or_execute_tool(self):
        x = parse_output('Prefixo<think>texto<tool_call>{"name":"lookup","arguments":{}}</tool_call>',
                         thinking=True, tool_names=['lookup'])
        self.assertEqual(x['content'], 'Prefixo')
        self.assertFalse(x['tool_calls'])
        self.assertIn('unfinished_reasoning', x['warnings'])

    def test_tool_json_strings_are_opaque_to_both_delimiters(self):
        for thinking in [False, True]:
            args = {'text': '  <think>x</think> </tool_call> " ç\n'}
            text = ('<think>decisão</think>' if thinking else '') + '<tool_call>\n' + json.dumps(
                {'name': 'lookup', 'arguments': args}, ensure_ascii=False) + '\n</tool_call>'
            x = parse_output(text, thinking=thinking, tool_names=['lookup'])
            self.assertEqual(x['content'], '')
            self.assertEqual(json.loads(x['tool_calls'][0]['function']['arguments']), args)
            self.assertEqual(x['reasoning_content'], 'decisão' if thinking else '')

    def test_multiple_calls_have_unique_ids_and_content_is_retained(self):
        call = '<tool_call>{"name":"lookup","arguments":{}}</tool_call>'
        x = parse_output('Antes' + call + '\n' + call + 'Depois', thinking=True, tool_names=['lookup'])
        self.assertEqual(x['content'], 'Antes\nDepois')
        self.assertEqual(len({c['id'] for c in x['tool_calls']}), 2)

    def test_malformed_unknown_and_unrequested_tools_remain_content(self):
        for text in ['<tool_call>invalid</tool_call>', '<tool_call>{"name":"other","arguments":{}}</tool_call>',
                     '<tool_call>{"name":"lookup","arguments":']:
            x = parse_output(text, thinking=True, tool_names=['lookup'])
            self.assertEqual(x['content'], text)
            self.assertFalse(x['tool_calls'])
        text = '<tool_call>{"name":"lookup","arguments":{}}</tool_call>'
        self.assertEqual(parse_output(text, thinking=True)['content'], text)


class Protocol(unittest.TestCase):
    def setUp(self):
        self.p = profile()
        self.t = Tokenizer()

    def test_profiles_are_independent_and_incompatible_generic_profile_is_rejected(self):
        for mode in ['thinking', 'instruct']:
            validate_profile(profile(mode))
        self.assertNotEqual(profile()['weight_sha256'], profile('instruct')['weight_sha256'])
        for key, value in [('model', profile('instruct')['model']), ('context_length', 8192),
                           ('max_tokens', 1024), ('enable_thinking', False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_profile(dict(self.p, **{key: value}))

    def test_budget_is_explicit_remaining_not_null_or_inherited_limit(self):
        b = body(max_tokens=1, temperature=0, seed=42, stop=['Q:', 'Pergunta:'])
        x = prepare_request(b, self.p, self.t)
        wire = x['raw_request']
        self.assertEqual(wire['max_tokens'], 4096 - len(wire['prompt']))
        self.assertGreater(wire['max_tokens'], 1024)
        self.assertEqual({k: wire[k] for k in SAMPLING}, SAMPLING)
        self.assertEqual(wire['stop'], b['stop'])
        self.assertEqual(wire['seed'], 42)
        self.assertTrue(wire['return_token_ids'])
        self.assertTrue(wire['include_stop_str_in_output'])
        self.assertFalse(wire['skip_special_tokens'])
        self.assertFalse(wire['spaces_between_special_tokens'])

    def test_opt_in_output_cap_preserves_prompt_and_sampling(self):
        original = prepare_request(body(), self.p, self.t)
        limited = prepare_request(body(), self.p, self.t, max_output_tokens=1024)
        self.assertEqual(limited['raw_request']['max_tokens'], 1024)
        self.assertEqual(limited['prompt_token_ids'], original['prompt_token_ids'])
        self.assertEqual({k: limited['raw_request'][k] for k in SAMPLING}, SAMPLING)
        self.assertEqual(limited['max_output_tokens'], 1024)
        long_body = body() | {'messages': [dict(role='user', content='x' * 3900)]}
        limited = prepare_request(long_body, self.p, self.t, max_output_tokens=1024)
        self.assertEqual(limited['raw_request']['max_tokens'], 4096-len(limited['prompt_token_ids']))
        self.assertLess(limited['raw_request']['max_tokens'], 1024)
        for invalid in (0, -1, True, 1.5, '1024'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                prepare_request(body(), self.p, self.t, max_output_tokens=invalid)

    def test_full_context_is_rejected_without_truncation(self):
        with self.assertRaisesRegex(ValueError, 'native model context'):
            prepare_request(body() | {'messages': [dict(role='user', content='x' * 4096)]}, self.p, self.t)

    def test_canary_audit_flags_are_accepted_without_disabling_capture(self):
        for value in [True, False]:
            prepared = prepare_request(body(return_token_ids=value, return_prompt_text=value), self.p, self.t)
            self.assertIs(prepared['raw_request']['return_token_ids'], True)
            result, _ = interpret_completion(response(prepared['raw_request'], 'Final'), prepared, self.p, self.t)
            self.assertEqual(result['prompt_token_ids'], prepared['prompt_token_ids'])
            self.assertEqual(result['prompt_text'], prepared['prompt'])
        with self.assertRaisesRegex(ValueError, 'Audit flags'):
            prepare_request(body(return_token_ids='true'), self.p, self.t)

    def test_unsupported_controls_and_mode_switch_rejected(self):
        cases = [dict(stream=True), dict(n=2), dict(response_format={'type':'json_object'}),
                 dict(tool_choice='required'), dict(ignore_eos=True), dict(structured_outputs={'json': {}}),
                 dict(allowed_token_ids=[1]), dict(parallel_tool_calls=False),
                 dict(chat_template_kwargs={'enable_thinking':False}), dict(truncate_prompt_tokens=100),
                 dict(messages=[dict(role='user', content=[{'type':'image_url'}])])]
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                prepare_request(body() | extra, self.p, self.t)

    def test_history_is_not_mutated_and_tool_arguments_render_as_objects(self):
        messages = [dict(role='user', content='Consulta'), dict(role='assistant', content='',
                    reasoning_content='Razão', tool_calls=[dict(id='call_a', type='function',
                    function=dict(name='lookup', arguments='{"key":"a"}'))]),
                    dict(role='tool', tool_call_id='call_a', content='7')]
        b = body(tools=TOOLS) | {'messages': messages}
        before = copy.deepcopy(b)
        x = prepare_request(b, self.p, self.t)
        self.assertEqual(b, before)
        self.assertEqual(x['messages'][1]['tool_calls'][0]['function']['arguments'], {'key':'a'})
        self.assertEqual(x['messages'][1]['reasoning_content'], 'Razão')
        with self.assertRaisesRegex(ValueError, 'reasoning history'):
            prepare_request(b | {'model':profile('instruct')['model']}, profile('instruct'), self.t)

    def test_raw_eos_and_stop_tokens_retained_but_not_in_scored_content(self):
        x = prepare_request(body(stop=['END']), self.p, self.t)
        result, evidence = interpret_completion(response(x['raw_request'], ' A ENDtrailing', stop='END'), x, self.p, self.t)
        self.assertEqual(result['choices'][0]['message']['content'], ' A ')
        self.assertEqual(evidence['raw_generated_text'], ' A ENDtrailing')
        result, evidence = interpret_completion(response(x['raw_request'], '<think>r</think>F'), x, self.p, self.t)
        self.assertEqual(result['choices'][0]['message']['content'], 'F')
        self.assertTrue(evidence['raw_generated_text'].endswith('<|im_end|>'))
        self.assertEqual(result['choices'][0]['token_ids'][-1], 2)

    def test_explicit_eos_stop_uses_original_tokens_before_removing_eos(self):
        for mode in ['thinking', 'instruct']:
            p = profile(mode)
            x = prepare_request(body(p, stop=['</s>', 'Q:', 'Pergunta:', '<|im_end|>']), p, self.t)
            raw = response(x['raw_request'], 'A resposta é (C).')
            raw['choices'][0]['stop_reason'] = '<|im_end|>'
            result, evidence = interpret_completion(raw, x, p, self.t)
            self.assertEqual(result['choices'][0]['message']['content'], 'A resposta é (C).')
            self.assertEqual(result['choices'][0]['token_ids'], raw['choices'][0]['token_ids'])
            self.assertTrue(evidence['raw_generated_text'].endswith('<|im_end|>'))

    def test_length_and_empty_response_are_not_promoted_or_retried(self):
        x = prepare_request(body(), self.p, self.t)
        for text in ['', '<think>incompleto']:
            result, _ = interpret_completion(response(x['raw_request'], text, finish='length'), x, self.p, self.t)
            self.assertEqual(result['choices'][0]['finish_reason'], 'length')
            self.assertEqual(result['choices'][0]['message']['content'], '')

    def test_upstream_version_model_context_and_loopback_are_verified(self):
        good = lambda url: {'version':'0.31.0'} if url.endswith('/version') else {
            'data':[dict(id=self.p['model'], max_model_len=4096)]}
        check_upstream('http://127.0.0.1:8000', self.p, good)
        with self.assertRaises(ValueError):
            check_upstream('http://external.invalid', self.p, good)
        for bad in [{'version':'0.32.0'}, {'version':'0.31.0', 'data':[dict(id='other',max_model_len=4096)]}]:
            with self.assertRaises(ValueError):
                check_upstream('http://localhost:8000', self.p, lambda url: bad)


class Durability(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.p, self.t = profile(), Tokenizer()

    def tearDown(self):
        self.temp.cleanup()

    def test_http_output_cap_reaches_upstream_and_audit(self):
        calls = []
        def upstream(req):
            calls.append(req)
            return response(req, 'Final')
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(
            self.p, self.t, self.root, upstream, max_output_tokens=1024))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = json_http(f'http://127.0.0.1:{server.server_port}/v1/chat/completions', body(max_tokens=32768))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['max_tokens'], 1024)
            self.assertEqual(result['choices'][0]['message']['content'], 'Final')
            audit = json.loads(next(self.root.glob('*/request.json')).read_text())
            self.assertEqual(audit['prepared']['max_output_tokens'], 1024)
            self.assertEqual(audit['prepared']['raw_request']['max_tokens'], 1024)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_raw_is_durable_before_parser_failure_and_dispatch_is_single(self):
        calls = []
        def upstream(req):
            self.assertEqual(len(list(self.root.glob('*/request.json'))), 1)
            calls.append(req)
            return response(req, 'Original')
        with patch('s5_nano.tucano_transport.interpret_completion', side_effect=ValueError('bad parser')):
            with self.assertRaises(ValueError):
                complete(body(), self.p, self.t, self.root, upstream)
        self.assertEqual(len(calls), 1)
        raw = json.loads(next(self.root.glob('*/raw_response.json')).read_text())
        self.assertEqual(raw['choices'][0]['token_ids'], self.t.encode('Original') + [2])
        self.assertFalse(list(self.root.glob('*/interpreted.json')))

    def test_token_identity_and_usage_failure_still_leave_raw_evidence(self):
        for mutate in [lambda r:r['choices'][0].pop('token_ids'),
                       lambda r:r['choices'][0].update(prompt_token_ids=[999]),
                       lambda r:r['usage'].update(completion_tokens=0)]:
            def upstream(req):
                r = response(req, 'final');mutate(r);return r
            with self.assertRaises(ValueError):
                complete(body(), self.p, self.t, self.root, upstream)
        self.assertEqual(len(list(self.root.glob('*/raw_response.json'))), 3)

    def test_no_dispatch_if_audit_cannot_be_written(self):
        with patch('s5_nano.tucano_transport.durable_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                complete(body(), self.p, self.t, self.root, lambda req:self.fail('dispatch forbidden'))

    def test_network_failure_recorded_without_retry(self):
        calls = []
        def upstream(req):
            calls.append(req);raise TimeoutError()
        with self.assertRaises(TimeoutError):
            complete(body(), self.p, self.t, self.root, upstream)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(list(self.root.glob('*/transport_error.json'))), 1)

    def test_http_context_overflow_is_distinct_from_invalid_request_without_dispatch(self):
        from s5_nano.context_failures import is_context_limit_response
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(
            self.p, self.t, self.root, lambda req: self.fail('No dispatch allowed')))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = 'http://127.0.0.1:' + str(server.server_port) + '/v1/chat/completions'
            for payload, context_error in [
                    (body() | {'messages': [dict(role='user', content='x'*4096)]}, True),
                    (body(return_token_ids='invalid'), False)]:
                with self.assertRaises(urllib.error.HTTPError) as captured:
                    json_http(url, payload)
                with captured.exception as error:
                    self.assertEqual(error.code, 400)
                    value = json.load(error)
                self.assertEqual(is_context_limit_response(400, value, 4096), context_error)
                if context_error:
                    self.assertFalse(value['new_model_call'])
                    self.assertGreaterEqual(value['error']['input_tokens'], 4096)
                    self.assertEqual(value['error']['context_length'], 4096)
            self.assertFalse(list(self.root.iterdir()))
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_http_post_generation_failure_is_not_retryable_and_links_raw_attempt(self):
        calls = []
        def upstream(req):
            calls.append(req)
            result = response(req, 'Preservado')
            result['model'] = 'wrong-model'
            return result
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.p,self.t,self.root,upstream))
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as captured:
                json_http('http://127.0.0.1:'+str(server.server_port)+'/v1/chat/completions',body())
            with captured.exception as error:
                self.assertEqual(error.code,422);result=json.load(error)
            self.assertFalse(result['retry_allowed'])
            self.assertEqual(result['error']['code'],'generation_audit_required')
            self.assertTrue((self.root/result['tucano_audit_id']/'raw_response.json').exists())
            self.assertTrue((self.root/result['tucano_audit_id']/'interpretation_error.json').exists())
            self.assertEqual(len(calls),1)
        finally:server.shutdown();server.server_close();thread.join(timeout=5)

    def test_http_concurrent_requests_and_two_turn_tool_history(self):
        barrier = threading.Barrier(3)
        def upstream(req):
            barrier.wait(timeout=10)
            return response(req, '<think>r</think><tool_call>{"name":"lookup","arguments":{"key":"a"}}</tool_call>')
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.p, self.t, self.root, upstream))
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                answers = list(pool.map(lambda _:json_http(base + '/v1/chat/completions', body(tools=TOOLS)), range(3)))
            self.assertEqual(len({a['tucano_audit_id'] for a in answers}), 3)
            self.assertEqual(len(list(self.root.glob('*/interpreted.json'))), 3)
            message = answers[0]['choices'][0]['message']
            self.assertEqual(answers[0]['choices'][0]['finish_reason'], 'tool_calls')
            next_body = body(tools=TOOLS)
            next_body['messages'] += [message, dict(role='tool', tool_call_id=message['tool_calls'][0]['id'], content='7')]
            prepared = prepare_request(next_body, self.p, self.t)
            self.assertIn('reasoning_content', prepared['prompt'])
            self.assertEqual(prepared['messages'][1]['reasoning_content'], 'r')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_production_listener_accepts_concurrent_burst_without_retries(self):
        server = TucanoHTTPServer(('127.0.0.1', 0), make_handler(
            self.p, self.t, self.root, lambda request: response(request, 'ok')))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        barrier = threading.Barrier(64)
        def request(_):
            barrier.wait(timeout=15)
            return json_http('http://127.0.0.1:' + str(server.server_port) +
                             '/v1/chat/completions', body())
        try:
            with ThreadPoolExecutor(max_workers=64) as pool:
                answers = list(pool.map(request, range(64)))
            self.assertEqual(len({a['tucano_audit_id'] for a in answers}), 64)
            self.assertEqual(len(list(self.root.glob('*/raw_response.json'))), 64)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
