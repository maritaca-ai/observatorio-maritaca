"""Private HTTP attempt records, including SDK retries and failed judgments."""
from datetime import datetime, timezone
import base64
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid


def stamp():
    return datetime.now(timezone.utc).isoformat()


def append(path, record):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def token_cost(model, usage, service_tier=None):
    """Output reasoning tokens are already included in output tokens."""
    remaining_rates = {
        'gpt-5.2': (1.75, .175, 14, 'gpt-5.2'),
        'gpt-5.2-2025-12-11': (1.75, .175, 14, 'gpt-5.2'),
        'gpt-4o-mini': (.15, .075, .6, 'gpt-4o-mini'),
        'gpt-4o-mini-2024-07-18': (.15, .075, .6, 'gpt-4o-mini'),
    }
    if model not in ('gpt-4.1', 'gpt-4.1-2025-04-14', 'gpt-6-luna', *remaining_rates) or not usage:
        return dict(usd=None, status='tariff_or_usage_unavailable')
    input_tokens = usage.get('input_tokens', usage.get('prompt_tokens'))
    output_tokens = usage.get('output_tokens', usage.get('completion_tokens'))
    if input_tokens is None or output_tokens is None:
        return dict(usd=None, status='usage_unavailable')
    details = usage.get('input_tokens_details') or usage.get('prompt_tokens_details') or {}
    cached = details.get('cached_tokens') or 0
    if not 0 <= cached <= input_tokens:
        raise ValueError('Invalid cached input usage')
    if model in remaining_rates:
        if service_tier not in (None, 'default', 'standard'):
            return dict(usd=None, status='service_tier_tariff_unconfirmed')
        price_input, price_cached, price_output, source = remaining_rates[model]
        return dict(usd=((input_tokens-cached)*price_input + cached*price_cached
                         + output_tokens*price_output)/1_000_000,
                    status='estimate_from_reported_usage', currency='USD', tariff_date='2026-11-01',
                    tariff_source='https://developers.openai.com/api/docs/models/' + source,
                    input_tokens=input_tokens, cached_input_tokens=cached, output_tokens=output_tokens,
                    input_per_million=price_input, cached_input_per_million=price_cached,
                    output_per_million=price_output, service_tier=service_tier or 'standard_assumed')
    if model == 'gpt-6-luna':
        if service_tier not in (None, 'default', 'standard'):
            return dict(usd=None, status='service_tier_tariff_unconfirmed')
        writes = details.get('cache_write_tokens') or 0
        if not 0 <= writes <= input_tokens-cached:
            raise ValueError('Invalid cache-write input usage')
        input_multiplier = 2 if input_tokens > 272_000 else 1
        output_multiplier = 1.5 if input_tokens > 272_000 else 1
        return dict(usd=((input_tokens-cached-writes)*.1 + cached*.01 + writes*.125)*input_multiplier/1_000_000
                         + output_tokens*.5*output_multiplier/1_000_000,
                    status='estimate_from_reported_usage', currency='USD', tariff_date='2026-10-31',
                    tariff_source='https://developers.openai.com/api/docs/models/gpt-6-luna',
                    input_tokens=input_tokens, cached_input_tokens=cached, cache_write_tokens=writes,
                    output_tokens=output_tokens, input_per_million=.1*input_multiplier,
                    cached_input_per_million=.01*input_multiplier,
                    cache_write_per_million=.125*input_multiplier, output_per_million=.5*output_multiplier,
                    service_tier=service_tier or 'standard_assumed')
    return dict(usd=((input_tokens-cached)*2 + cached*.5 + output_tokens*8)/1_000_000,
                status='estimate_from_reported_usage', currency='USD',
                tariff_date='2026-10-30',
                tariff_source='https://developers.openai.com/api/docs/models/gpt-4.1',
                input_tokens=input_tokens, cached_input_tokens=cached, output_tokens=output_tokens,
                input_per_million=2, cached_input_per_million=.5, output_per_million=8)


def store(root, identifier, phase, record):
    folder = root / 'http_raw'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / (identifier + '.' + phase + '.json.gz')
    with path.open('xb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as handle:
            handle.write(json.dumps(record, ensure_ascii=False).encode())
    path.chmod(0o600)
    return dict(artifact=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def maritaca_token_cost(model, usage):
    """Conservative BRL estimate; discounts are reconciled against provider billing."""
    if model != 'sabia-4-thinking' or not usage:
        return dict(brl=None, currency='BRL', status='tariff_or_usage_unavailable')
    inputs, outputs = usage.get('prompt_tokens'), usage.get('completion_tokens')
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens') or 0
    if inputs is None or outputs is None:
        return dict(brl=None, currency='BRL', status='usage_unavailable')
    if not 0 <= cached <= inputs or outputs < 0:
        raise ValueError('Invalid Maritaca token usage')
    return dict(brl=((inputs-cached)*5 + cached*1.25 + outputs*40)/1_000_000,
        currency='BRL', status='standard_tariff_estimate_before_night_or_tier_discounts',
        input_tokens=inputs, cached_input_tokens=cached, output_tokens=outputs,
        reasoning_included_in_output=True, input_per_million=5,
        cached_input_per_million=1.25, output_per_million=40,
        tariff_date='2026-11-02', tariff_source='https://docs.maritaca.ai/pt/precos')


def openrouter_token_cost(model, usage):
    """Preserve provider cost; never count reasoning twice or invent zero usage."""
    if model != 'anthropic/claude-opus-4.6' or not isinstance(usage, dict):
        return dict(usd=None, status='tariff_or_usage_unavailable')
    reported = usage.get('cost')
    if type(reported) in (int, float) and math.isfinite(reported) and reported >= 0:
        return dict(usd=reported, currency='USD', status='provider_reported_usage_cost',
                    reasoning_included_in_output=True)
    inputs, outputs = usage.get('prompt_tokens'), usage.get('completion_tokens')
    detail = usage.get('prompt_tokens_details') or {}
    cached, writes = detail.get('cached_tokens') or 0, detail.get('cache_write_tokens') or 0
    if inputs is None or outputs is None:
        return dict(usd=None, status='usage_unavailable')
    if min(inputs, outputs, cached, writes) < 0 or cached + writes > inputs:
        raise ValueError('Invalid OpenRouter usage')
    return dict(usd=((inputs-cached-writes)*5 + cached*.5 + writes*10 + outputs*25)/1_000_000,
        currency='USD', status='standard_tariff_estimate_cache_writes_conservative',
        tariff_source='https://platform.claude.com/docs/en/about-claude/pricing',
        tariff_date='2026-11-04', reasoning_included_in_output=True)


def OpenAI(*args, **kwargs):
    """Compatible factory: log each HTTP attempt without changing API payloads."""
    import httpx
    from openai import OpenAI as Client
    folder = os.environ.get('S5_NANO_AUDIT_DIR')
    if not folder:
        raise ValueError('An explicit private audit directory is required')
    if 'http_client' in kwargs:
        raise ValueError('Unaudited HTTP clients cannot bypass the recorder')
    root = Path(folder)
    # A Tucano error may follow a durably saved generation. SDK retries would
    # silently produce a second candidate. Native judge retry policy is separate.
    profile_path = os.environ.get('S5_NANO_PROFILE')
    proxy_base = os.environ.get('S5_NANO_PROXY_URL', '').rstrip('/')
    if profile_path and proxy_base and str(kwargs.get('base_url', '')).startswith(proxy_base + '/'):
        if json.loads(Path(profile_path).read_text()).get('transport_policy') == 'tucano_raw_completion_v1':
            kwargs['max_retries'] = 0

    class Transport(httpx.BaseTransport):
        def __init__(self):
            self.inner = httpx.HTTPTransport()

        def handle_request(self, request):
            identifier = uuid.uuid4().hex
            start = time.monotonic()
            body = request.read()
            url = urlsplit(str(request.url))
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                payload = None
            model = payload.get('model') if isinstance(payload, dict) else None
            from .judge_budget import check_budget
            check_budget(url.hostname, identifier)
            common = dict(attempt_id=identifier, benchmark=os.environ.get('S5_NANO_BENCHMARK'),
                          host=url.hostname, path=url.path, method=request.method, model=model)
            raw = store(root, identifier, 'request', dict(**common, time=stamp(),
                        payload=payload, wire_body_base64=base64.b64encode(body).decode()))
            append(root / 'http_attempts.jsonl', dict(**common, phase='started', time=stamp(), **raw))
            try:
                replay = None
                response = self.inner.handle_request(request)
                data = response.read()
                try:
                    parsed = json.loads(data)
                except (ValueError, UnicodeError):
                    parsed = None
                usage = parsed.get('usage') if isinstance(parsed, dict) else None
                response_model = parsed.get('model', model) if isinstance(parsed, dict) else model
                cost = token_cost(response_model, usage, parsed.get('service_tier') if isinstance(parsed, dict) else None) if url.hostname == 'api.openai.com' else dict(
                    usd=None, status='local_compute' if url.hostname in ('127.0.0.1', 'localhost') else 'tariff_unavailable')
                if url.hostname == 'chat.maritaca.ai':
                    cost = maritaca_token_cost(model, usage)
                elif url.hostname == 'openrouter.ai':
                    cost = openrouter_token_cost(response_model, usage)
                if replay:
                    cost=dict(usd=0.0,status='reused_saved_response_no_new_charge',original_cost=replay[1]['original_cost'])
                record = dict(**common, time=stamp(), status=response.status_code,
                              response_model=response_model, usage=usage, cost=cost,
                              elapsed_seconds=time.monotonic()-start,
                              provider_request_id=response.headers.get('x-request-id'))
                if replay:record['replay_source']=replay[1]
                raw = store(root, identifier, 'response', dict(**record, payload=parsed,
                            wire_body_base64=base64.b64encode(data).decode()))
                append(root / 'http_attempts.jsonl', dict(**record, phase='finished', **raw))
                from .judge_budget import finish_attempt
                finish_attempt(url.hostname, identifier, cost.get('usd'), response.status_code)
                return response
            except BaseException as exc:
                from .judge_budget import finish_attempt
                finish_attempt(url.hostname, identifier, None, None)
                append(root / 'http_attempts.jsonl', dict(**common, phase='failed', time=stamp(),
                       error_type=type(exc).__name__, elapsed_seconds=time.monotonic()-start,
                       cost=dict(usd=None, status='unknown_after_transport_failure')))
                raise

        def close(self):
            self.inner.close()

    timeout = kwargs.get('timeout', 1800)
    kwargs['http_client'] = httpx.Client(transport=Transport(), timeout=timeout,
                                        follow_redirects=False)
    class IdentityClient(Client):
        def request(self, cast_to, options, *, stream=False, stream_cls=None):
            from .model_identity import expected_model, verify_response_model
            endpoint = str(options.url).split('?')[0].rstrip('/')
            generation = options.method.lower() == 'post' and endpoint.endswith(
                ('/chat/completions', '/completions', '/responses'))
            model = None
            if generation:
                model = expected_model(options.json_data, options.extra_json)
                if stream:
                    raise ValueError('Streaming generation has no supported response identity gate')
            result = super().request(cast_to, options, stream=stream, stream_cls=stream_cls)
            if generation:
                raw = result.model_dump(mode='json') if hasattr(result, 'model_dump') else None
                verify_response_model(raw, model, root, source='completed_sdk_response',
                                      request=options.json_data, provider_host=self.base_url.host)
            return result
    return IdentityClient(*args, **kwargs)


def install_tool_http_audit():
    """Record requests-based search/crawl attempts without logging credentials."""
    import requests
    root = Path(os.environ['S5_NANO_AUDIT_DIR'])
    previous = requests.sessions.Session.send
    if getattr(previous, '_s5_nano_audited', False):
        return

    def send(session, request, **kwargs):
        identifier = uuid.uuid4().hex
        start = time.monotonic()
        url = urlsplit(request.url)
        # Tool inputs/results are private; headers and credential-bearing URLs
        # are deliberately excluded. The evaluated tool code is unmodified.
        body = request.body or b''
        if isinstance(body, str):
            body = body.encode()
        if not isinstance(body, bytes):
            raise ValueError('Unsupported tool HTTP body: cannot audit safely')
        common = dict(attempt_id=identifier, benchmark=os.environ.get('S5_NANO_BENCHMARK'),
                      host=url.hostname, path=url.path, method=request.method)
        receipt = store(root, identifier, 'tool_request', dict(**common, time=stamp(),
                        wire_body_base64=base64.b64encode(body).decode()))
        append(root / 'tool_http_attempts.jsonl', dict(**common, phase='started', time=stamp(), **receipt))
        try:
            response = previous(session, request, **kwargs)
            receipt = store(root, identifier, 'tool_response', dict(**common, time=stamp(),
                            status=response.status_code,
                            wire_body_base64=base64.b64encode(response.content).decode()))
            append(root / 'tool_http_attempts.jsonl', dict(**common, phase='finished', time=stamp(),
                   elapsed_seconds=time.monotonic()-start, status=response.status_code,
                   cost=dict(usd=None, status='tool_tariff_not_confirmed'), **receipt))
            return response
        except BaseException as exc:
            append(root / 'tool_http_attempts.jsonl', dict(**common, phase='failed', time=stamp(),
                   error_type=type(exc).__name__, elapsed_seconds=time.monotonic()-start,
                   cost=dict(usd=None, status='unknown_after_transport_failure')))
            raise

    send._s5_nano_audited = True
    requests.sessions.Session.send = send
