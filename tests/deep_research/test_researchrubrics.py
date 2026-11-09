import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

BENCH = Path(__file__).resolve().parents[2]/'benchmarks/agentico/researchrubrics/fork'
sys.path.insert(0, str(BENCH))
spec = importlib.util.spec_from_file_location('rr_eval', BENCH/'run_eval.py')
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)


def grade(score=1):
    return dict(score=score, verdict='Satisfied' if score else 'Not Satisfied', reasoning='Evidence in report.', confidence=.9)


def test_signed_weights_and_incomplete_grades():
    criteria = [dict(weight=5), dict(weight=-10), dict(weight=0)]
    assert rr.question_score(criteria, [1, 1, 1]) == -100
    assert rr.question_score(criteria, [1, 0, 0]) == 100
    with pytest.raises(ValueError):
        rr.question_score(criteria, [1, 0])
    with pytest.raises(ValueError):
        rr.question_score(criteria, [True, 0, 0])


def test_default_and_json_validation():
    assert rr.DEFAULT_JUDGE == dict(provider='maritaca', model='S5', effort='none', max_tokens=50000)
    _, body = rr.body_for(rr.DEFAULT_JUDGE, [{'role':'user','content':'grade'}])
    assert body['reasoning_effort'] == 'none' and body['web_search'] is False
    assert rr.parse_grade(json.dumps(grade(1.0))) == grade(1.0)
    assert rr.question_score([dict(weight=5)], [1.0]) == 100
    assert rr.parse_grade('```json\n'+json.dumps(grade())+'\n```') == grade()
    for invalid in [dict(grade(), score=True), dict(grade(), verdict='Not Satisfied'), dict(grade(), confidence=2)]:
        with pytest.raises(ValueError):
            rr.parse_grade(json.dumps(invalid))
    with pytest.raises(ValueError):
        rr.parse_grade('Commentary '+json.dumps(grade()))


def test_full_dataset_pin_and_corruption(tmp_path, monkeypatch):
    cases = [dict(sample_id=str(i), prompt='question', rubrics=[dict(weight=1)]*(26 if i<68 else 25)) for i in range(101)]
    assert sum(len(c['rubrics']) for c in cases) == 2593
    path = tmp_path/'processed_data.jsonl'
    path.write_text('\n'.join(json.dumps(c) for c in cases))
    manifest = dict(sources={'processed_data.jsonl':dict(sha256=rr.digest(path.read_bytes()), url='unused')})
    monkeypatch.setattr(rr, 'read_json', lambda _: manifest)
    assert rr.load_inputs(tmp_path)[0] == cases
    path.write_text(path.read_text()+'\n')
    with pytest.raises(ValueError, match='checksum'):
        rr.load_inputs(tmp_path)


def test_import_is_immutable(tmp_path):
    cases = [dict(sample_id='one', prompt='question')]
    file = tmp_path/'input.jsonl'; file.write_text(json.dumps(dict(case_id='one', text='report')))
    rr.import_answers(tmp_path/'run', cases, file)
    file.write_text(json.dumps(dict(case_id='one', text='changed')))
    with pytest.raises(ValueError, match='Inputs changed'):
        rr.import_answers(tmp_path/'run', cases, file)


def test_saved_grade_transport_fallback_and_receipt_tamper(tmp_path):
    async def run():
        bodies = []
        def reply(request):
            bodies.append(json.loads(request.content))
            if len(bodies)==1:
                return httpx.Response(400, text='The model did not produce valid JSON')
            return httpx.Response(200, json=dict(model='S5', choices=[dict(finish_reason='stop',message=dict(content=json.dumps(grade())))]))
        client = rr.Client('maritaca','never-persist-me', output_ceiling=65536, json_fallback=True)
        await client.http.aclose(); client.http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        prompt=[dict(role='user',content='grade')]; path=tmp_path/'vote.json'
        try:
            with patch('draco_benchmark.api.asyncio.sleep', new_callable=AsyncMock):
                row=await rr.saved_grade(client,rr.DEFAULT_JUDGE,prompt,path)
            assert row['json_transport_fallback'] and 'response_format' not in bodies[1]
            assert bodies[1]['reasoning_effort']=='none'
            assert (await rr.saved_grade(None,rr.DEFAULT_JUDGE,prompt,path))['parsed']==grade()
            path.unlink()
            assert (await rr.saved_grade(client,rr.DEFAULT_JUDGE,prompt,path))['parsed']==grade()
            assert len(bodies)==2  # Recover a completed receipt without a second charge.
            receipt=rr.read_json(row['attempt']);receipt['request']['messages'][0]['content']='changed'
            rr.write_json(row['attempt'],receipt)
            with pytest.raises(ValueError,match='receipt changed'):
                rr.check_vote(row,rr.DEFAULT_JUDGE,prompt)
            assert all('never-persist-me' not in p.read_text() for p in tmp_path.rglob('*.json'))
        finally:await client.close()
    asyncio.run(run())


def test_output_ceiling_does_not_repeat_identical_truncation(tmp_path):
    async def run():
        bodies=[]
        def reply(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200,json=dict(model='S5', choices=[dict(finish_reason='length',message=dict(content='partial'))]))
        client=rr.Client('maritaca','test',output_ceiling=20)
        await client.http.aclose();client.http=httpx.AsyncClient(transport=httpx.MockTransport(reply))
        try:
            with patch('draco_benchmark.api.asyncio.sleep', new_callable=AsyncMock), pytest.raises(RuntimeError):
                await client.request('/chat/completions',dict(model='S5',max_tokens=10),tmp_path,str)
            assert [b['max_tokens'] for b in bodies]==[10,20]
        finally:await client.close()
    asyncio.run(run())


def test_partial_results_never_publish(tmp_path, monkeypatch):
    cases=[dict(sample_id='one', prompt='q', rubrics=[dict(weight=5, criterion='c',axis='Explicit Criteria')])]
    rr.store_answer(tmp_path,cases[0],'answer')
    async def fake_grade(*args,**kwargs):return dict(parsed=grade())
    monkeypatch.setattr(rr,'grade_report',fake_grade)
    publish=AsyncMock();monkeypatch.setattr(rr,'publish',publish)
    args=rr.parser().parse_args(['--run-id','test','--wandb']);args.cache=tmp_path
    with pytest.raises(RuntimeError,match='1/101'):
        asyncio.run(rr.judge_and_score(args,tmp_path,cases,rr.DEFAULT_JUDGE,False))
    assert rr.read_json(tmp_path/'results.json')['score'] is None
    publish.assert_not_called()


def test_research_replays_tools_and_retains_visible_capped_answer(tmp_path):
    from research import PROTOCOL, research
    class Search:
        def __init__(self):self.calls=0
        async def execute(self,call,folder):
            self.calls+=1
            return {'results':[{'title':'Source','snippet':'Evidence'}]}
    class Model:
        def __init__(self):self.calls=0
        async def request(self,endpoint,body,folder,parser,**kwargs):
            self.calls+=1
            if self.calls==1:
                message=dict(role='assistant',content=None,reasoning_details=[dict(type='reasoning.text',text='search rationale')],tool_calls=[dict(id='call1',type='function',function=dict(name='web_search',arguments='{"query":"evidence"}'))])
                response=dict(model='S5',choices=[dict(finish_reason='tool_calls',message=message)],usage=dict(prompt_tokens=10,completion_tokens=5))
                status='ok'
            else:
                assert body['messages'][2]['reasoning_details'][0]['text']=='search rationale'
                response=dict(model='S5',choices=[dict(finish_reason='length',message=dict(role='assistant',content='Visible answer at the approved ceiling.'))],usage=dict(prompt_tokens=20,completion_tokens=50))
                status='error'
            path=folder/'0001.json';rr.write_json(path,dict(request=body,response=response,seconds=1,status=status))
            if status=='error':raise RuntimeError('capped')
            return '',response,str(path),1
    async def run():
        model,search=Model(),Search()
        config=dict(model='S5',provider='maritaca',effort='xhigh',max_tokens=50,output_ceiling=50,input_byte_budget=100000,research_protocol=PROTOCOL)
        first=await research(model,search,tmp_path,'one',config,'Research this question.')
        assert first[0]=='Visible answer at the approved ceiling.' and first[1]['output_limit_reached']
        second=await research(model,search,tmp_path,'one',config,'Research this question.')
        assert second==first and model.calls==2 and search.calls==1
        with pytest.raises(ValueError,match='Inputs changed'):
            await research(model,search,tmp_path,'one',config,'Different question.')
    asyncio.run(run())


def test_context_fallback_preserves_question_and_reasoning():
    from research import fit_context
    messages=[dict(role='system',content='system'),dict(role='user',content='question'),
              dict(role='assistant',content=None,reasoning_details=[dict(text='reasoning')],tool_calls=[dict(id='one')]),
              dict(role='tool',tool_call_id='one',content='a'*10000)]
    fitted=fit_context(messages,1000)
    assert fitted[:3]==messages[:3] and len(fitted[3]['content'])<1000
    assert len(messages[3]['content'])==10000  # full source remains untouched


def test_context_reserve_default_and_4k_configuration(tmp_path):
    args = rr.parser().parse_args(['--run-id', 'test'])
    spec = rr.generation_config(args)
    assert args.context_reserve == 4096
    assert spec['input_byte_budget'] == min(500000, args.context_length-args.max_tokens-4096)
    assert 'context_reserve' not in spec and 'base_url' not in spec  # historical run identity
    args.context_length = 4096; args.max_tokens = 1024
    with pytest.raises(ValueError, match='Context must exceed'):
        rr.generation_config(args)
    args.context_reserve = 256
    spec = rr.generation_config(args)
    assert spec['input_byte_budget'] == 2816 and spec['context_reserve'] == 256
    rr.freeze(tmp_path/'generation.json', spec)
    args.context_reserve = 0
    assert rr.generation_config(args)['input_byte_budget'] == 3072
    with pytest.raises(ValueError, match='Inputs changed'):
        rr.freeze(tmp_path/'generation.json', rr.generation_config(args))
    args.context_reserve = -1
    with pytest.raises(ValueError, match='nonnegative'):
        rr.generation_config(args)


def test_local_candidate_url_and_provider_validation():
    args = rr.parser().parse_args(['--run-id', 'test', '--provider', 'openai'])
    with pytest.raises(ValueError, match='base-url'):
        rr.generation_config(args)
    args.base_url = 'http://localhost:8000/v1/'
    assert rr.generation_config(args)['base_url'] == 'http://localhost:8000/v1'
    assert rr.DEFAULT_JUDGE['provider'] == 'maritaca'
    args.openrouter_provider = 'vendor'
    with pytest.raises(ValueError, match='openrouter-provider'):
        rr.generation_config(args)


def test_wrong_model_truncated_response_is_not_accepted(tmp_path):
    from research import PROTOCOL, research
    async def run():
        requests = []
        def reply(request):
            requests.append(request)
            return httpx.Response(200, json=dict(model='unexpected-model', choices=[dict(
                finish_reason='length', message=dict(role='assistant', content='Visible but wrong model.'))]))
        client = rr.Client('maritaca', 'synthetic-test-value', output_ceiling=50)
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        config = dict(model='S5', provider='maritaca', effort='none', max_tokens=50,
                      output_ceiling=50, input_byte_budget=10000, research_protocol=PROTOCOL)
        try:
            with pytest.raises(RuntimeError):
                await research(client, None, tmp_path, 'one', config, 'Question.')
            assert len(requests) == 1
            assert not (tmp_path/'research_sessions/one/complete.json').exists()
            assert (tmp_path/'generation_attempts/one/0000/0001.json').exists()
        finally:
            await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('invalid_response', [
    dict(model='unexpected-model', choices=[dict(finish_reason='stop', message=dict(content=json.dumps(grade())))]),
    dict(model='S5', choices=[]),
])
def test_invalid_judge_receipt_does_not_block_resume(tmp_path, invalid_response):
    async def run():
        calls = []
        def reply(request):
            calls.append(request)
            return httpx.Response(200, json=dict(model='S5', choices=[dict(
                finish_reason='stop', message=dict(content=json.dumps(grade())))]))
        client = rr.Client('maritaca', 'synthetic-test-value', output_ceiling=65536, json_fallback=True)
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        path = tmp_path/'vote.json'; prompt = [dict(role='user', content='Grade.')]
        endpoint, body = rr.body_for(rr.DEFAULT_JUDGE, prompt)
        previous = path.parent/'attempts/vote/0001.json'
        rr.write_json(previous, dict(status='error', request=body, response=invalid_response,
                                    provider='maritaca', seconds=1))
        previous_bytes = previous.read_bytes()
        try:
            first = await rr.saved_grade(client, rr.DEFAULT_JUDGE, prompt, path)
            assert first['parsed'] == grade()
            second = await rr.saved_grade(client, rr.DEFAULT_JUDGE, prompt, path)
            assert second == first and len(calls) == 1
            assert previous.read_bytes() == previous_bytes
            assert (path.parent/'attempts/vote/0002.json').exists()
        finally:
            await client.close()
    asyncio.run(run())
