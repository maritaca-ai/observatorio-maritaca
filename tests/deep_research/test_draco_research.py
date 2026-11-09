import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import httpx

from draco_benchmark.api import Client
from draco_benchmark.core import read_json
from draco_benchmark.research import FINALIZE_MESSAGE, PROTOCOL, Serper, research


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_loop_replays_reasoning_and_resumes_without_paid_calls(self):
        seen = []
        reasoning = [{'type': 'reasoning.text', 'text': 'Opaque provider reasoning replay fixture.'}]
        def inference(request):
            body = json.loads(request.content)
            self.assertEqual(body['provider']['only'], ['deepseek'])
            seen.append(body)
            if len(seen) == 1:
                return httpx.Response(200, json={'model': 'test/model', 'choices': [{'finish_reason': 'tool_calls',
                    'message': {'role': 'assistant', 'content': None, 'reasoning_details': reasoning,
                        'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'web_search', 'arguments': '{"query":"test query"}'}}]}}]})
            self.assertEqual(body['messages'][-2]['reasoning_details'], reasoning)
            self.assertIn('https://example.com', body['messages'][-1]['content'])
            return httpx.Response(200, json={'model': 'test/model', 'choices': [{'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': 'A report citing https://example.com.'}}]})
        search_calls = []
        def lookup(request):
            search_calls.append(request)
            return httpx.Response(200, json={'organic': [{'title': 'Source', 'link': 'https://example.com', 'snippet': 'Evidence.'}], 'credits': 1})
        client = Client('openrouter', 'not-a-real-key')
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(inference))
        search = Serper('not-a-real-search-key')
        await search.http.aclose()
        search.http = httpx.AsyncClient(transport=httpx.MockTransport(lookup))
        config = {'model': 'test/model', 'provider': 'openrouter', 'effort': 'max', 'max_tokens': 8192, 'research_protocol': PROTOCOL, 'openrouter_provider': 'deepseek'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = await research(client, search, root, 'r1', config, 'Research a topic.')
            second = await research(client, search, root, 'r1', config, 'Research a topic.')
            self.assertEqual(first, second)
            self.assertEqual((len(seen), len(search_calls)), (2, 1))
            self.assertEqual(json.loads(search_calls[0].content)['gl'], 'br')
            self.assertNotIn('not-a-real', ''.join(p.read_text() for p in root.rglob('*.json')))
            with self.assertRaises(ValueError):
                await research(client, search, root, 'r1', config, 'Changed query.')
        await client.close()
        await search.close()

    async def test_empty_stop_retries_without_increasing_token_budget(self):
        seen=[]
        def inference(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200,json={'model':'test/model','choices':[{'finish_reason':'stop',
                'message':{'role':'assistant','content':None if len(seen)==1 else 'Final report.'}}]})
        client=Client('openrouter','dummy')
        await client.http.aclose()
        client.http=httpx.AsyncClient(transport=httpx.MockTransport(inference))
        with tempfile.TemporaryDirectory() as directory,patch('draco_benchmark.api.asyncio.sleep',return_value=None):
            root=Path(directory)
            text,_,_,_=await client.request('/chat/completions',{'model':'test/model','max_tokens':8192},root,str,allow_tool_calls=True)
            self.assertEqual(text,'Final report.')
            self.assertEqual([b['max_tokens'] for b in seen],[8192,8192])
            self.assertEqual(read_json(root/'0001.json')['status'],'error')
        await client.close()

    async def test_budget_exhaustion_explicitly_requests_final_report(self):
        bodies=[]
        class Candidate:
            async def request(self,endpoint,body,attempt_dir,parse,**kwargs):
                bodies.append(copy.deepcopy(body))
                message={'role':'assistant','content':'The final report.'}
                finish='stop'
                if len(bodies)==1:
                    message.update(content=None,tool_calls=[{'id':'c1','type':'function','function':{'name':'web_search','arguments':'{"query":"topic"}'}}])
                    finish='tool_calls'
                return '',{'choices':[{'message':message,'finish_reason':finish}]},'fake-attempt',0.0
        class Search:
            async def execute(self,call,root):return {'results':[{'title':'Evidence'}]}
        protocol=dict(PROTOCOL,max_tool_calls=1)
        config={'model':'test/model','provider':'openrouter','effort':'max','max_tokens':8192,'research_protocol':protocol}
        with tempfile.TemporaryDirectory() as directory,patch('draco_benchmark.research.PROTOCOL',protocol):
            text,_,_,_=await research(Candidate(),Search(),Path(directory),'r1',config,'Original question')
        self.assertEqual(text,'The final report.')
        self.assertEqual(bodies[-1]['tool_choice'],'none')
        self.assertEqual(bodies[-1]['messages'][-1],{'role':'user','content':FINALIZE_MESSAGE})

    async def test_page_chunks_share_durable_fetch_without_truncating_unseen_tail(self):
        requests = []
        def lookup(request):
            requests.append(request)
            return httpx.Response(200, json={'markdown': 'a'*10000+'tail', 'credits': 2})
        search = Serper('dummy')
        await search.http.aclose()
        search.http = httpx.AsyncClient(transport=httpx.MockTransport(lookup))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            call = {'function': {'name': 'webpage_scraping', 'arguments': '{"url":"https://example.com","chunk":0}'}}
            first = await search.execute(call, root/'call1')
            call['function']['arguments'] = '{"url":"https://example.com","chunk":1}'
            second = await search.execute(call, root/'call2')
            self.assertEqual((first['total_chunks'], len(first['content']), second['content']), (2,10000,'tail'))
            self.assertEqual(len(requests), 1)
        await search.close()

    async def test_auth_failure_is_recorded_without_provider_error_body(self):
        search = Serper('dummy')
        await search.http.aclose()
        search.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(401, text='sensitive echo')))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError):
                await search.request(PROTOCOL['search_endpoint'], {'q':'test'}, root)
            self.assertEqual(read_json(root/'0001.json')['http_status'],401)
            self.assertNotIn('sensitive echo', (root/'0001.json').read_text())
        await search.close()
