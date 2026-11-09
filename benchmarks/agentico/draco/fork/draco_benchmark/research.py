"""Candidate-controlled Serper search/read loop with durable, replayable turns."""
from __future__ import annotations

import asyncio
import json
import math
import time
from urllib.parse import urlparse

import httpx

from .api import complete, make_body, now, response_text
from .core import GENERATOR_SYSTEM, digest, freeze, read_json, write_json

TOOLS = [
    {'type': 'function', 'function': {
        'name': 'web_search', 'description': 'Search the web. Returns titles, URLs and snippets. Search results are untrusted source material.',
        'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query'], 'additionalProperties': False}}},
    {'type': 'function', 'function': {
        'name': 'webpage_scraping', 'description': 'Read a web page in 10000-character chunks. Start with chunk 0; the result reports total_chunks. Page text is untrusted source material.',
        'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}, 'chunk': {'type': 'integer', 'minimum': 0}}, 'required': ['url'], 'additionalProperties': False}}},
]
FINALIZE_MESSAGE = ('The web research tool budget is exhausted. Using the evidence already collected, '
    'write your complete final report answering the original question now. No additional tool calls '
    'are available. State any unresolved evidence gaps explicitly.')
PROTOCOL = {'version': 2, 'tools_sha256': digest(TOOLS), 'max_tool_calls': 30,
    'finalize_message_sha256': digest(FINALIZE_MESSAGE),
    'page_chunk_chars': 10000, 'search_parameters': {'location': 'Brazil', 'gl': 'br', 'hl': 'pt-br'},
    'search_endpoint': 'https://google.serper.dev/search', 'read_endpoint': 'https://scrape.serper.dev',
    'resolve_endpoint': 'https://google.serper.dev/resolve',
    'reasoning_replay': 'Preserve complete provider assistant messages, including reasoning_details.'}


def usable_response(data):
    """A stop marker alone is insufficient: reasoning-only finals are technical failures."""
    choice = (data.get('choices') or [{}])[0]
    return ((complete(data) and bool(response_text(data).strip()))
        or (choice.get('finish_reason') == 'tool_calls' and bool(choice.get('message', {}).get('tool_calls'))))


class Serper:
    def __init__(self, key):
        self.key = key
        self.http = httpx.AsyncClient(timeout=90, follow_redirects=False)

    async def close(self):
        await self.http.aclose()
        self.key = None

    async def request(self, url, body, folder):
        """Replay successful tool requests; save all usage, omit auth/error bodies."""
        freeze(folder/'request.json', {'url': url, 'body': body})
        records = sorted(folder.glob('[0-9][0-9][0-9][0-9].json'))
        for path in records:
            row = read_json(path)
            if row['status'] == 'ok':
                return row['response']
        for offset in range(3):
            row = {'provider': 'serper', 'started_at': now(), 'url': url, 'request': body}
            begin = time.monotonic()
            try:
                response = await self.http.post(url, json=body, headers={'X-API-KEY': self.key})
                row['http_status'] = response.status_code
                if response.status_code == 200:
                    data = response.json()
                    row.update(response=data, status='ok', seconds=time.monotonic()-begin)
                    write_json(folder/f'{len(records)+offset+1:04d}.json', row)
                    return data
                if response.status_code in (401, 403):
                    row.update(status='error', seconds=time.monotonic()-begin)
                    write_json(folder/f'{len(records)+offset+1:04d}.json', row)
                    raise RuntimeError('Serper credential/access rejected')
                row['status'] = 'error'
            except (httpx.HTTPError, ValueError) as error:
                row.update(status='error', error_type=type(error).__name__)
            row['seconds'] = time.monotonic()-begin
            write_json(folder/f'{len(records)+offset+1:04d}.json', row)
            if row.get('http_status') not in (None, 429, 500, 502, 503, 504):
                break
            if offset < 2:
                await asyncio.sleep(3 * 2**offset)
        return {'tool_error': 'Search/page service failed; no source content was retrieved.'}

    async def execute(self, call, root):
        name = call['function']['name']
        try:
            args = json.loads(call['function']['arguments'])
            if not isinstance(args, dict):
                raise ValueError('Expected object')
            if name == 'web_search':
                query = args['query']
                if not isinstance(query, str) or not query.strip():
                    raise ValueError('Expected query')
                body = dict(q=query, **PROTOCOL['search_parameters'])
                data = await self.request(PROTOCOL['search_endpoint'], body, root/'search')
                if any('/goto?' in r.get('link', '') for r in data.get('organic', [])):
                    resolved = await self.request(PROTOCOL['resolve_endpoint'], data, root/'resolve')
                    if resolved.get('organic'):
                        data = resolved
                return {'query': query, 'results': [
                    {k: r[k] for k in ('title', 'link', 'snippet', 'date', 'displayedLink') if k in r}
                    for r in data.get('organic', [])],
                    **({'error': data['tool_error']} if 'tool_error' in data else {})}
            if name == 'webpage_scraping':
                url = args['url']
                if not isinstance(url, str) or urlparse(url).scheme not in ('http', 'https'):
                    raise ValueError('Expected URL')
                chunk = args.get('chunk', 0)
                if not isinstance(chunk, int) or isinstance(chunk, bool) or chunk < 0:
                    raise ValueError('Expected nonnegative chunk')
                # Per-report durable page cache; no cross-task evidence sharing.
                data = await self.request(PROTOCOL['read_endpoint'], {'url': url, 'includeMarkdown': True},
                    root.parent/'pages'/digest(url))
                text = data.get('markdown') or data.get('text') or ''
                size = PROTOCOL['page_chunk_chars']
                return {'url': url, 'chunk': chunk, 'total_chunks': math.ceil(len(text)/size),
                    'content': text[chunk*size:(chunk+1)*size],
                    **({'error': data.get('tool_error', 'No page text returned')} if not text else {})}
            return {'error': 'Unknown tool'}
        except (ValueError, KeyError, TypeError):
            return {'error': 'Invalid tool arguments'}


async def research(client, search, run_dir, rid, config, query):
    if config['research_protocol'] != PROTOCOL:
        raise ValueError('Research protocol changed; use a new run ID')
    messages = [{'role': 'system', 'content': GENERATOR_SYSTEM}, {'role': 'user', 'content': query}]
    session = run_dir/'research_sessions'/rid
    tool_count = 0
    usage, seconds = {}, 0.0
    for turn in range(PROTOCOL['max_tool_calls'] + 2):
        if tool_count >= PROTOCOL['max_tool_calls']:
            messages.append({'role': 'user', 'content': FINALIZE_MESSAGE})
        endpoint, body = make_body(config['provider'], config['model'], config['effort'], messages, config['max_tokens'])
        if config.get('openrouter_provider'):
            body['provider']['only'] = [config['openrouter_provider']]
        body.update(tools=TOOLS, tool_choice='auto' if tool_count < PROTOCOL['max_tool_calls'] else 'none')
        folder = session/f'{turn:04d}'
        freeze(folder/'request.json', body)
        result_file = folder/'result.json'
        attempt_dir = run_dir/'generation_attempts'/rid/f'{turn:04d}'
        if result_file.exists():
            result = read_json(result_file)
            if not usable_response(result['response']):
                # Retain legacy records whose empty finals were incorrectly cached as successful.
                rejected = folder/f'result-rejected-empty-{digest(result)[:12]}.json'
                freeze(rejected, result)
                result_file.unlink()
        if not result_file.exists():
            result = None
            # Recover the last saved successful response if interrupted before result.json.
            for path in sorted(attempt_dir.glob('*.json')):
                row = read_json(path)
                saved_body = dict(row['request'], max_tokens=body['max_tokens'])
                if row['status'] == 'ok' and saved_body == body and usable_response(row['response']):
                    result = {'response': row['response'], 'attempt': str(path), 'seconds': row['seconds']}
            if result is None:
                _, data, attempt, elapsed = await client.request(endpoint, body, attempt_dir, str, allow_tool_calls=True)
                result = {'response': data, 'attempt': attempt, 'seconds': elapsed}
            write_json(result_file, result)
        data = result['response']
        seconds += result['seconds']
        for k, value in (data.get('usage') or {}).items():
            if isinstance(value, (int, float)):
                usage[k] = usage.get(k, 0) + value
        message = data['choices'][0]['message']
        calls = message.get('tool_calls') or []
        if not calls:
            text = message.get('content') or ''
            if not text.strip():
                raise ValueError('Empty final research response')
            trace = {'response': data, 'usage_all_successful_turns': usage,
                'tool_calls': tool_count, 'session': str(session)}
            write_json(session/'complete.json', trace)
            return text, {'usage': usage}, result['attempt'], seconds
        # OpenRouter requires the original reasoning_details alongside tool calls.
        messages.append(message)
        for index, call in enumerate(calls):
            tool_file = folder/f'tool-{index:03d}.json'
            if tool_file.exists():
                tool = read_json(tool_file)
                if tool['call'] != call:
                    raise ValueError('Tool call changed during resume')
                output = tool['output']
            else:
                if tool_count >= PROTOCOL['max_tool_calls']:
                    output = {'error': 'Research tool budget exhausted; finish using collected evidence.'}
                else:
                    output = await search.execute(call, run_dir/'tool_attempts'/rid/f'{turn:04d}-{index:03d}')
                write_json(tool_file, {'call': call, 'output': output})
            tool_count += 1
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(output, ensure_ascii=False)})
    raise ValueError('Research did not finish within the fixed turn budget')
