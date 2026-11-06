"""Offline adapter regressions, including one complete loopback HTTP exchange."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from s5_nano import gaia_transport_adapter as adapter
import test_protocol


class ToolAdapterTests(unittest.TestCase):
    def test_history_preserves_system_and_parallel_tool_outputs(self):
        tools = [dict(type='function', function=dict(name='lookup', parameters={}))]
        calls = [dict(id=str(i), type='function', function=dict(name='lookup', arguments='{}')) for i in range(2)]
        messages = [dict(role='system', content='Instrução original.'),
                    dict(role='user', content='Pergunta original.'),
                    dict(role='assistant', content=None, tool_calls=calls),
                    dict(role='tool', tool_call_id='0', content='Resultado A'),
                    dict(role='tool', tool_call_id='1', content='Resultado B')]
        out = adapter.adapt_request(dict(messages=messages, tools=tools))
        self.assertNotIn('tools', out)
        self.assertEqual([m['role'] for m in out['messages']], ['system', 'user', 'assistant', 'user'])
        self.assertTrue(out['messages'][0]['content'].startswith('Instrução original.'))
        self.assertIn('Resultado A', out['messages'][-1]['content'])
        self.assertIn('Resultado B', out['messages'][-1]['content'])
        self.assertIsNone(messages[2]['content'])
        self.assertIsNone(adapter.parse_call('Resposta em texto.'))
        self.assertEqual(adapter.parse_call('{"name":"unknown","parameters":{}}')['function']['name'], 'unknown')

    def test_proxy_delivers_tool_call_and_records_original_wire_response(self):
        with tempfile.TemporaryDirectory() as temp:
            proxy = test_protocol.ProtocolTests().proxy('instruct', temp)
            proxy.PROFILE['tool_adapter'] = adapter.ADAPTER_ID
            seen = []
            class Upstream(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass
                def do_POST(self):
                    seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                    body = json.dumps(dict(model=proxy.MODEL,
                        choices=[dict(index=0, message=dict(role='assistant',
                            content='{"name":"lookup","parameters":{"q":"teste"}}'), finish_reason='stop')],
                        usage=dict(prompt_tokens=10, completion_tokens=8, total_tokens=18))).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
            proxy.UPSTREAM = urlsplit(f'http://127.0.0.1:{upstream.server_port}/v1')
            forwarding = ThreadingHTTPServer(('127.0.0.1', 0), proxy.Handler)
            threads = [Thread(target=s.serve_forever, daemon=True) for s in (upstream, forwarding)]
            for t in threads:
                t.start()
            try:
                payload = dict(model=proxy.MODEL, messages=[dict(role='user', content='Busque teste')],
                    tools=[dict(type='function', function=dict(name='lookup', parameters={}))], temperature=0)
                request = Request(f'http://127.0.0.1:{forwarding.server_port}/canary/v1/chat/completions',
                    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
                with urlopen(request, timeout=10) as response:
                    result = json.load(response)
                self.assertEqual(result['choices'][0]['finish_reason'], 'tool_calls')
                self.assertEqual(result['choices'][0]['message']['tool_calls'][0]['function']['name'], 'lookup')
                self.assertEqual(len(seen), 1)
                self.assertNotIn('tools', seen[0])
                self.assertIn('lookup', seen[0]['messages'][0]['content'])
                self.assertEqual(seen[0]['temperature'], proxy.POLICY['temperature'])
                events = [json.loads(line) for line in (Path(temp)/'candidate_attempts.jsonl').read_text().splitlines()]
                self.assertEqual([e['phase'] for e in events], ['started', 'finished'])
            finally:
                for s in (forwarding, upstream):
                    s.shutdown()
                    s.server_close()
                for t in threads:
                    t.join(timeout=3)
