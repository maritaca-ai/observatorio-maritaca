"""Small standard-library clients; credentials never enter request fingerprints."""
import json
import os
import urllib.error
import urllib.request

PROVIDERS = {
    'maritaca': ('https://chat.maritaca.ai/api/chat/completions', 'MARITACA_API_KEY'),
    'openai': ('https://api.openai.com/v1/responses', 'OPENAI_API_KEY'),
    'anthropic': ('https://api.anthropic.com/v1/messages', 'ANTHROPIC_API_KEY'),
    'openrouter': ('https://openrouter.ai/api/v1/chat/completions', 'OPENROUTER_API_KEY'),
}

class APIError(ValueError):
    """Safe error without credentials, HTTP body or private response text."""

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def api_key(provider):
    env = PROVIDERS[provider][1]
    key = os.environ.get(env, '').strip()
    if not key:
        raise APIError(f'Set {env} in your environment.')
    return key

def prepare(provider, model, messages, max_tokens=8000, temperature=None, reasoning_effort=None):
    if provider not in PROVIDERS or not model or not model.strip() or max_tokens < 1:
        raise APIError('Provide a supported provider, nonempty model and positive token limit.')
    if temperature is not None and not 0 <= temperature <= 2:
        raise APIError('Temperature must be between 0 and 2 (individual models may impose tighter limits).')
    body = dict(model=model, messages=messages, max_tokens=max_tokens)
    if provider == 'openai':
        body = dict(model=model, input=messages, max_output_tokens=max_tokens, store=False)
    elif provider == 'maritaca':
        body['service_tier'] = 'auto'
    if provider == 'openrouter':
        body['provider'] = {'require_parameters':True}
    if temperature is not None:
        body['temperature'] = temperature
    if reasoning_effort:
        if provider in ('openai','openrouter'):
            body['reasoning'] = {'effort': reasoning_effort}
        elif provider == 'anthropic':
            body['thinking'] = {'type':'adaptive'}
            body['output_config'] = {'effort':reasoning_effort}
        else:
            raise APIError('Reasoning effort is not configurable for Maritaca in this runner.')
    return dict(provider=provider, endpoint=PROVIDERS[provider][0], body=body)

def extract(provider, result):
    if provider == 'openai':
        if result.get('status') != 'completed':
            raise APIError('Incomplete OpenAI response; increase the token limit if necessary.')
        texts = []
        for item in result.get('output',[]):
            if item.get('type') == 'message':
                for block in item.get('content',[]):
                    if block.get('type') == 'refusal':
                        raise APIError('Model refusal; no successful response cached.')
                    if block.get('type') == 'output_text':
                        texts.append(block['text'])
        text = '\n'.join(texts)
    elif provider == 'anthropic':
        if result.get('stop_reason') != 'end_turn':
            raise APIError('Incomplete or refused Anthropic response; no successful response cached.')
        text = '\n'.join(b['text'] for b in result.get('content',[]) if b.get('type')=='text')
    else:
        choice = result['choices'][0]
        if choice.get('finish_reason') != 'stop' or choice.get('message',{}).get('refusal'):
            raise APIError('Incomplete or refused response; no successful response cached.')
        text = choice['message'].get('content')
    if not isinstance(text,str) or not text.strip():
        raise APIError('Provider returned no final answer text.')
    return dict(text=text, usage=result.get('usage',{}), model=result.get('model'))

def send(spec, key):
    provider = spec['provider']
    if spec['endpoint'] != PROVIDERS[provider][0]:
        raise APIError('Unrecognized provider endpoint.')
    headers = {'Content-Type':'application/json'}
    if provider == 'anthropic':
        headers.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
    else:
        headers['Authorization'] = 'Bearer '+key
    req = urllib.request.Request(spec['endpoint'],data=json.dumps(spec['body']).encode(),headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=300) as response:
            result = json.load(response)
        return extract(provider,result)
    except urllib.error.HTTPError as exc:
        raise APIError(f'{provider} returned HTTP {exc.code}. Check model access and supported parameters; completed calls remain cached.') from None
    except (urllib.error.URLError, TimeoutError):
        raise APIError('API connection failed; completed calls remain cached.') from None
    except (KeyError,IndexError,TypeError,json.JSONDecodeError):
        raise APIError('Malformed API response; no successful response cached.') from None
