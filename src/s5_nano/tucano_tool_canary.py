"""Check tool transport with an explicit synthetic history, not model capability."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from .tucano_transport import parse_output


def fixture(thinking):
    tools = [dict(type='function', function=dict(name='saldo', description='Consulta saldo fictício.',
        parameters=dict(type='object', properties={'conta': {'type': 'integer'}}, required=['conta'])))]
    text = ('<think>Consulta sintética de integração.</think>' if thinking else '') + \
        '<tool_call>{"name":"saldo","arguments":{"conta":17}}</tool_call>'
    parsed = parse_output(text, thinking=thinking, tool_names=['saldo'])
    assert not parsed['warnings'] and len(parsed['tool_calls']) == 1
    call = parsed['tool_calls'][0]
    assert call['function']['name'] == 'saldo'
    args = json.loads(call['function']['arguments'])
    def saldo(conta):
        assert conta == 17
        return '500 reais'
    result = saldo(**args)
    messages = [dict(role='user', content='Consulte o saldo fictício da conta 17 e diga o valor.'),
        dict(role='assistant', content=parsed['content'], reasoning_content=parsed['reasoning_content'],
             tool_calls=parsed['tool_calls']),
        dict(role='tool', tool_call_id=call['id'], content=result)]
    return tools, messages, text


def canary(runtime, base, api_base, model, profile, tokenizer_path, template_path):
    from transformers import AutoTokenizer
    from .runtime import post, save, generation_prompt_ids
    runtime = Path(runtime)
    if profile.get('transport_policy') != 'tucano_raw_completion_v1' or model != profile['model']:
        raise ValueError('Tool transport check requires the explicit Tucano profile')
    for name in ['canary_verified.json', 'candidate_attempts.jsonl', 'http_attempts.jsonl']:
        if (runtime/name).exists() and (runtime/name).stat().st_size:
            raise RuntimeError('Existing canary evidence requires audit; no repeated dispatch')
    template = Path(template_path).read_bytes()
    if hashlib.sha256(template).hexdigest() != profile['chat_template_sha256']:
        raise ValueError('Tool canary template differs from profile')
    tok = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    tok.chat_template = template.decode()
    tools, messages, text = fixture(profile['enable_thinking'])
    save(runtime/'canary_tool_fixture.json', dict(origin='synthetic_integration_fixture',
        generated_by_model=False, raw_fixture_text=text, tools=tools, messages=messages))
    response = post(base, '/canary/v1/chat/completions', dict(model=model, messages=messages,
        tools=tools, temperature=0, max_tokens=1,
        chat_template_kwargs={'enable_thinking': not profile['enable_thinking']},
        return_token_ids=True, return_prompt_text=True))
    rendered = deepcopy(messages)
    for m in rendered:
        for call in m.get('tool_calls', []):
            call['function']['arguments'] = json.loads(call['function']['arguments'])
    prompt = tok.apply_chat_template(rendered, tools=tools, tokenize=False, add_generation_prompt=True,
        **dict(profile.get('chat_template_kwargs', {}), enable_thinking=profile['enable_thinking']))
    tokens = generation_prompt_ids(response)
    if (tokens != tok.encode(prompt, add_special_tokens=False)
            or response['usage']['prompt_tokens'] != len(tokens) or response.get('prompt_text') != prompt):
        raise ValueError('Tool/history generation prompt differs from native tokenization')
    with (runtime/'effective_requests_secondary.jsonl').open() as stream:
        applied = [row['applied'] for row in map(json.loads,stream)
                   if row.get('status') == 'forwarding' and row.get('benchmark') == 'canary']
    if len(applied) != 1:
        raise ValueError('Unexpected tool-canary dispatch count')
    a = applied[0]
    if (a['enable_thinking'] is not profile['enable_thinking'] or a['max_tokens'] != profile['max_tokens']
            or any(a[k] != v for k,v in profile['sampling'].items())):
        raise ValueError('Tool canary effective profile differs')
    save(runtime/'canary_verified.json', dict(passed=True, time=time.time(),
        scope='synthetic_tool_transport_with_real_model_continuation', model_tool_capability_asserted=False,
        synthetic_assistant_history=True, thinking_received=profile['enable_thinking'],
        actual_prompt_tokens_match=True, template_sha256=profile['chat_template_sha256'],
        preset=profile['sampling'], max_tokens=profile['max_tokens'],
        rendered_prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest()))
