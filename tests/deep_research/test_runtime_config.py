"""Transport and crash-recovery checks; all HTTP requests use MockTransport."""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from draco_benchmark.api import Client, ORIGINS, make_body, resolve_base_url, resolve_key
from draco_benchmark.core import read_json, write_json
from draco_benchmark.research import PROTOCOL
from draco_benchmark.runner import generate, judge


def response(model='local-model', text='report', finish='stop'):
    return dict(model=model, choices=[dict(finish_reason=finish, message=dict(content=text))])


def test_explicit_endpoint_and_plain_openai_body():
    for provider in ('maritaca', 'openrouter'):
        assert resolve_base_url(provider) == ORIGINS[provider]
    assert resolve_base_url('openai', 'http://localhost:8000/v1/') == 'http://localhost:8000/v1'
    for url in (None, '', 'file:///tmp/model', 'https://user:secret@example.com/v1',
                'https://example.com/v1?key=secret', 'https://example.com/v1#secret'):
        with pytest.raises(ValueError):
            resolve_base_url('openai', url)
    endpoint, body = make_body('openai', 'local-model', 'none', [], 100)
    assert endpoint == '/chat/completions'
    assert body == dict(model='local-model', messages=[], max_tokens=100)
    assert make_body('openai', 'local-model', 'high', [], 100)[1]['reasoning_effort'] == 'high'
    with pytest.raises(ValueError, match='Serper'):
        make_body('openai', 'local-model', 'none', [], 100, research=True)


def test_endpoint_routing_and_completed_receipt_recovery(tmp_path):
    async def run():
        requests = []
        def reply(req):
            requests.append(req)
            return httpx.Response(200, json=response())
        client = Client('openai', 'test-secret', base_url='http://localhost:8000/v1/')
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        body = dict(model='local-model', max_tokens=100, messages=[])
        try:
            first = await client.request('/chat/completions', body, tmp_path, str)
            second = await client.request('/chat/completions', body, tmp_path, str)
            assert first == second and len(requests) == 1
            assert str(requests[0].url) == 'http://localhost:8000/v1/chat/completions'
            assert requests[0].headers['Authorization'] == 'Bearer test-secret'
            assert 'test-secret' not in (tmp_path/'0001.json').read_text()
            with pytest.raises(ValueError, match='configuration'):
                await client.request('/chat/completions', dict(body, messages=[dict(role='user',content='changed')]), tmp_path, str)
            client.base_url = 'http://localhost:8001/v1'
            with pytest.raises(ValueError, match='configuration'):
                await client.request('/chat/completions', body, tmp_path, str)
            assert len(requests) == 1
        finally:
            await client.close()
    asyncio.run(run())


def test_resume_after_output_limit_retry_and_legacy_receipt(tmp_path):
    async def run():
        calls = []
        def reply(req):
            calls.append(json.loads(req.content))
            return httpx.Response(200, json=response('S5', finish='length' if len(calls)==1 else 'stop'))
        client = Client('maritaca', 'test')
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        body = dict(model='S5', max_tokens=100)
        try:
            with patch('draco_benchmark.api.asyncio.sleep', new_callable=AsyncMock):
                first = await client.request('/chat/completions', body, tmp_path, str)
            receipt = read_json(tmp_path/'0002.json')
            receipt.pop('base_url'); receipt.pop('endpoint')
            write_json(tmp_path/'0002.json', receipt)
            assert await client.request('/chat/completions', body, tmp_path, str) == first
            assert [b['max_tokens'] for b in calls] == [100, 200]
            receipt['response']['model'] = 'wrong-model'
            write_json(tmp_path/'0002.json', receipt)
            with pytest.raises(ValueError, match='Invalid saved'):
                await client.request('/chat/completions', body, tmp_path, str)
            assert len(calls) == 2
        finally:
            await client.close()
    asyncio.run(run())


def test_serper_candidate_url_preserves_default_judge_endpoint(tmp_path, monkeypatch):
    import draco_benchmark.runner as runner
    import draco_benchmark.research as research_module
    endpoints, bodies = [], []
    real_client = Client
    def fake_client(provider, key, timeout, **kwargs):
        client = real_client(provider, key, timeout, **kwargs)
        endpoints.append(client.base_url)
        async def post(url, *, json, headers):
            bodies.append(json)
            text = 'report' if len(bodies)==1 else '{"criterion_status":"MET","explanation":"Present"}'
            return httpx.Response(200, json=response(json['model'], text))
        client.http.post = post
        return client
    class Search:
        def __init__(self, key): pass
        async def close(self): pass
    monkeypatch.setattr(runner, 'Client', fake_client)
    monkeypatch.setattr(research_module, 'Serper', Search)
    case = dict(id='one', domain='Finance', problem='question', answer=json.dumps(dict(sections=[dict(
        id='section', criteria=[dict(id='c', weight=1, requirement='report')]) ])))
    config = dict(provider='openai', model='local-model', effort='none', max_tokens=100,
                  research=True, research_backend='serper', research_protocol=PROTOCOL,
                  base_url='http://localhost:8000/v1')
    async def run():
        await generate(tmp_path, [case], config, 'test', search_key='test-search')
        await judge(tmp_path, [case], dict(provider='maritaca', model='S5', effort='none', max_tokens=100), 'judge', 'test')
    asyncio.run(run())
    assert endpoints == ['http://localhost:8000/v1', ORIGINS['maritaca']]
    assert 'tools' in bodies[0] and 'web_search' not in bodies[0] and 'provider' not in bodies[0]
    assert bodies[1]['model'] == 'S5' and bodies[1]['web_search'] is False


def test_generic_endpoint_never_implicitly_uses_openai_credential(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-test-key')
    with pytest.raises(ValueError, match='explicit --api-key-env'):
        resolve_key('openai')
    monkeypatch.setenv('CANDIDATE_API_KEY', 'explicit-test-key')
    assert resolve_key('openai', 'CANDIDATE_API_KEY') == 'explicit-test-key'


def test_legacy_empty_research_receipt_does_not_block_resume(tmp_path):
    async def run():
        body = dict(model='S5', max_tokens=100, messages=[])
        write_json(tmp_path/'0001.json', dict(status='ok', provider='maritaca',
            request=body, response=response('S5', ''), seconds=1))
        calls = []
        def reply(req):
            calls.append(req)
            return httpx.Response(200, json=response('S5', 'usable report'))
        client = Client('maritaca', 'test')
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        try:
            first = await client.request('/chat/completions', body, tmp_path, str, allow_tool_calls=True)
            assert first[0] == 'usable report'
            assert await client.request('/chat/completions', body, tmp_path, str, allow_tool_calls=True) == first
            assert len(calls) == 1 and (tmp_path/'0001.json').exists()
        finally:
            await client.close()
    asyncio.run(run())


def test_endpoint_override_is_not_a_canonical_draco_run():
    from draco_benchmark.cli import canonical_protocol
    config = dict(model='S5', effort='xhigh', provider='maritaca', max_tokens=8192)
    generation = dict(research=True)
    summary = dict(config=config, generation_configs=[generation], by_generator={'S5': {}}, imported=False)
    assert canonical_protocol(summary, 'full')
    generation['base_url'] = 'http://localhost:8000/v1'
    assert not canonical_protocol(summary, 'full')
