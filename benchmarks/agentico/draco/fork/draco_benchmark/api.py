"""Provider adapters. Persist request bodies/usage, never authentication headers."""
from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from .core import read_json, write_json

ORIGINS = {'openrouter': 'https://openrouter.ai/api/v1', 'maritaca': 'https://chat.maritaca.ai/api', 'openai': None}
KEY_ENVS = {'openrouter': 'OPENROUTER_API_KEY', 'maritaca': 'MARITACA_API_KEY'}


def resolve_base_url(provider, base_url=None):
    value = base_url if base_url is not None else ORIGINS[provider]
    if not value:
        raise ValueError('The openai provider requires an explicit --base-url')
    url = httpx.URL(value)
    if url.scheme not in ('http', 'https') or not url.host or url.userinfo or url.query or url.fragment:
        raise ValueError('Base URL must be HTTP(S), without credentials, query or fragment')
    return str(url).rstrip('/')


def now():
    return datetime.now(timezone.utc).isoformat()


def resolve_key(provider, env_name=None):
    name = env_name or KEY_ENVS.get(provider)
    if not name:
        raise ValueError('The openai provider requires explicit --api-key-env')
    value = os.environ.get(name)
    if not value:
        raise ValueError(f'Missing credential: {name}; no fallback to another provider/key')
    return value


def make_body(provider, model, effort, messages, max_tokens, *, research=False):
    if provider == 'openrouter' and research:
        return '/responses', {
            'model': model, 'reasoning': {'effort': effort}, 'max_output_tokens': max_tokens,
            'instructions': messages[0]['content'], 'input': messages[1]['content'],
            'tools': [{'type': 'openrouter:web_search', 'parameters': {'engine': 'native'}}],
            'provider': {'require_parameters': True, 'allow_fallbacks': False},
        }
    body = {'model': model, 'messages': messages, 'max_tokens': max_tokens}
    if provider == 'openrouter':
        body.update(provider={'require_parameters': True, 'allow_fallbacks': False})
        if effort is not None:
            body['reasoning'] = {'effort': effort}
    elif provider == 'maritaca':
        body.update(stream=False, web_search=research)
        if effort is not None:
            body['reasoning_effort'] = effort
    elif provider == 'openai':
        if research:
            raise ValueError('OpenAI-compatible servers require explicit Serper tools or research=none')
        if effort not in (None, 'none'):
            body['reasoning_effort'] = effort
    else:
        raise ValueError(f'Unknown provider: {provider}')
    return '/chat/completions', body


def response_text(data):
    if 'choices' in data:
        return data['choices'][0]['message'].get('content') or ''
    return '\n'.join(p.get('text', '') for o in data.get('output', []) if o.get('type') == 'message'
                     for p in o.get('content', []) if p.get('type') == 'output_text')


def complete(data):
    if 'choices' in data:
        return bool(data['choices']) and data['choices'][0].get('finish_reason') == 'stop'
    return data.get('status') == 'completed'


def rate_limit_delay(value, offset):
    """Back off throttled inference; honor numeric and HTTP-date Retry-After."""
    fallback = min(300, 60 * 2**offset)
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            seconds = (stamp - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return fallback
    return max(fallback, seconds) if math.isfinite(seconds) else fallback


class Client:
    def __init__(self, provider, key, timeout=1200, *, output_ceiling=None, json_fallback=False, base_url=None):
        self.base_url = resolve_base_url(provider, base_url)
        self.provider, self.key = provider, key
        self.output_ceiling, self.json_fallback = output_ceiling, json_fallback
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=30), follow_redirects=False)

    async def close(self):
        await self.http.aclose()
        self.key = None

    async def request(self, endpoint, body, attempt_dir, parse, attempts=3, *, allow_tool_calls=False):
        """Retry only technical failures; each response/error gets a distinct record."""
        attempt_dir.mkdir(parents=True, exist_ok=True)
        existing = [int(p.stem) for p in attempt_dir.glob('*.json') if p.stem.isdigit()]
        start = max(existing, default=0) + 1
        body = dict(body)
        token_key = 'max_output_tokens' if 'max_output_tokens' in body else 'max_tokens'
        if self.output_ceiling is not None:
            body[token_key] = min(body[token_key], self.output_ceiling)
        # Recover a receipt written before the caller could save its final result.
        for number in sorted(existing):
            path = attempt_dir/f'{number:04d}.json'
            saved = read_json(path)
            if saved.get('status') != 'ok':
                continue
            request = dict(saved['request'])
            limit = request.get(token_key)
            if (not isinstance(limit, int) or limit < body[token_key]
                    or (self.output_ceiling is not None and limit > self.output_ceiling)):
                raise ValueError('Saved successful request has a different output budget')
            request[token_key] = body[token_key]
            if self.json_fallback and 'response_format' not in request:
                request['response_format'] = body.get('response_format')
                if request['response_format'] is None:
                    request.pop('response_format')
            if (request != body or saved.get('provider') != self.provider
                    or saved.get('base_url', ORIGINS.get(self.provider)) != self.base_url
                    or saved.get('endpoint', endpoint) != endpoint):
                raise ValueError('Saved successful request does not match current configuration')
            data = saved['response']
            tool_turn = (allow_tool_calls and bool(data.get('choices'))
                and data['choices'][0].get('finish_reason') == 'tool_calls'
                and bool(data['choices'][0]['message'].get('tool_calls')))
            text = response_text(data)
            if data.get('model') != body['model']:
                raise ValueError('Invalid saved successful response: unexpected model ID')
            if data.get('error') or not (complete(data) or tool_turn):
                continue
            if allow_tool_calls and not tool_turn and not text.strip():
                # Old research runs incorrectly recorded empty finals as successful.
                continue
            return parse(text), data, str(path), saved['seconds']
        for offset in range(attempts):
            number = start + offset
            path = attempt_dir/f'{number:04d}.json'
            stamp, begin = now(), time.monotonic()
            record = {'request': body.copy(), 'started_at': stamp, 'provider': self.provider,
                      'base_url': self.base_url, 'endpoint': endpoint}
            fatal = False
            retry_delay = min(30, 3 * 2**offset)
            try:
                response = await self.http.post(self.base_url+endpoint, json=body,
                    headers={'Authorization': 'Bearer '+self.key})
                if response.status_code >= 400:
                    # Deliberately omit headers and provider error text (may echo secrets).
                    record['http_status'] = response.status_code
                    if response.status_code == 429:
                        retry_delay = rate_limit_delay(response.headers.get('retry-after'), offset)
                        record['retry_delay_seconds'] = retry_delay
                    fatal = response.status_code not in (429, 500, 502, 503, 504)
                    if (self.json_fallback and response.status_code == 400
                            and body.get('response_format') == {'type': 'json_object'}
                            and 'The model did not produce valid JSON' in response.text):
                        record['error_class'] = 'provider_invalid_json'
                        body.pop('response_format')
                        fatal = False
                    raise ValueError(f'HTTP {response.status_code}')
                data = response.json()
                record['response'] = data
                if data.get('error'):
                    raise ValueError('Provider returned an error object')
                if data.get('model') != body['model']:
                    fatal = True
                    raise ValueError('Provider returned an unexpected model ID')
                tool_turn = (allow_tool_calls and bool(data.get('choices'))
                    and data['choices'][0].get('finish_reason') == 'tool_calls'
                    and bool(data['choices'][0]['message'].get('tool_calls')))
                if not complete(data) and not tool_turn:
                    finish = (data.get('choices') or [{}])[0].get('finish_reason')
                    reason = (data.get('incomplete_details') or {}).get('reason')
                    if finish == 'length' or reason == 'max_output_tokens':
                        token_key = 'max_output_tokens' if 'max_output_tokens' in body else 'max_tokens'
                        if self.output_ceiling is not None and body[token_key] >= self.output_ceiling:
                            fatal = True
                        else:
                            body[token_key] *= 2
                            if self.output_ceiling is not None:
                                body[token_key] = min(body[token_key], self.output_ceiling)
                    if finish == 'content_filter' or (data.get('choices') or [{}])[0].get('message', {}).get('refusal'):
                        fatal = True
                    raise ValueError('Incomplete response')
                text = response_text(data)
                if allow_tool_calls and not tool_turn and not text.strip():
                    raise ValueError('Empty final response')
                parsed = parse(text)
                record.update(seconds=time.monotonic()-begin, status='ok')
                write_json(path, record)
                return parsed, data, str(path), record['seconds']
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
                # No exception repr/traceback from HTTP clients with auth context.
                record.update(seconds=time.monotonic()-begin, status='error', error_type=type(error).__name__)
                write_json(path, record)
                if fatal or offset+1 == attempts:
                    raise RuntimeError(f'Request failed; sanitized evidence at {path}') from None
                await asyncio.sleep(retry_delay)
        raise RuntimeError('No API attempt made')
