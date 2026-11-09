"""ResearchRubrics Serper protocol: shared tools, explicit context/output limits."""
import json
from draco_benchmark.api import complete, make_body, now, response_text
from draco_benchmark.core import GENERATOR_SYSTEM, digest, freeze, read_json, write_json
from draco_benchmark.research import Serper, TOOLS, FINALIZE_MESSAGE, usable_response, PROTOCOL as BASE_PROTOCOL

PROTOCOL = dict(BASE_PROTOCOL, version=3, context_policy='Conservative UTF-8 byte bound; finalize at context reserve and retain latest source snippets within budget.')

def capped_answer(attempt_dir, body, ceiling):
    """Keep the first visible answer at the fixed output ceiling, even if poor."""
    for path in sorted(attempt_dir.glob('[0-9][0-9][0-9][0-9].json')):
        row=read_json(path);data=row.get('response') or {}
        choice=(data.get('choices') or [{}])[0]
        saved=dict(row.get('request') or {})
        limit=saved.get('max_tokens',0)
        saved['max_tokens']=body['max_tokens'];saved.pop('cache_control',None)
        if (saved==body and limit==ceiling
            and data.get('model')==body.get('model') and not data.get('error')
            and choice.get('finish_reason')=='length'
            and not choice.get('message',{}).get('tool_calls')
            and response_text(data).strip()):
            return dict(response=data,attempt=str(path),seconds=row['seconds'],
                output_limit_reached=True)
    return None


async def research(client, search, run_dir, rid, config, query):
    if config['research_protocol'] != PROTOCOL:
        raise ValueError('Research protocol changed; use a new run ID')
    messages = [{'role': 'system', 'content': GENERATOR_SYSTEM}, {'role': 'user', 'content': query}]
    session = run_dir/'research_sessions'/rid
    tool_count = 0
    usage, seconds = {}, 0.0
    for turn in range(PROTOCOL['max_tool_calls'] + 2):
        context_full = len(json.dumps(messages, ensure_ascii=False).encode()) > config['input_byte_budget']
        if context_full:
            messages = fit_context(messages, config['input_byte_budget'])
        finalizing = context_full or tool_count >= PROTOCOL['max_tool_calls']
        if finalizing:
            messages.append({'role': 'user', 'content': FINALIZE_MESSAGE})
        endpoint, body = make_body(config['provider'], config['model'], config['effort'], messages, config['max_tokens'])
        if config.get('openrouter_provider'):
            body['provider']['only'] = [config['openrouter_provider']]
        body.update(tools=TOOLS, tool_choice='none' if finalizing else 'auto')
        folder = session/f'{turn:04d}'
        freeze(folder/'request.json', body)
        result_file = folder/'result.json'
        attempt_dir = run_dir/'generation_attempts'/rid/f'{turn:04d}'
        if result_file.exists():
            result = read_json(result_file)
            retained_cap=result.get('output_limit_reached') and capped_answer(attempt_dir, body, config['output_ceiling'])
            if not usable_response(result['response']) and not retained_cap:
                # Retain legacy records whose empty finals were incorrectly cached as successful.
                rejected = folder/f'result-rejected-empty-{digest(result)[:12]}.json'
                freeze(rejected, result)
                result_file.unlink()
        if not result_file.exists():
            result = None
            # Recover the first saved successful response if interrupted before result.json.
            for path in sorted(attempt_dir.glob('*.json')):
                row = read_json(path)
                saved_body = dict(row['request'], max_tokens=body['max_tokens'])
                # Cache metadata changes billing, not the model-visible input.
                saved_body.pop('cache_control', None)
                if row['status'] == 'ok' and saved_body == body and usable_response(row['response']):
                    result = {'response': row['response'], 'attempt': str(path), 'seconds': row['seconds']}
                    break
            if result is None:
                result=capped_answer(attempt_dir, body, config['output_ceiling'])
            if result is None:
                try:
                    _, data, attempt, elapsed = await client.request(endpoint, body, attempt_dir, str, allow_tool_calls=True)
                    result = {'response': data, 'attempt': attempt, 'seconds': elapsed}
                except RuntimeError:
                    result=capped_answer(attempt_dir, body, config['output_ceiling'])
                    if result is None:raise
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
                'tool_calls': tool_count, 'session': str(session), 'context_finalization': context_full,
                'output_limit_reached':bool(result.get('output_limit_reached'))}
            write_json(session/'complete.json', trace)
            return text, {'usage': usage,'output_limit_reached':bool(result.get('output_limit_reached'))}, result['attempt'], seconds
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
                if finalizing or tool_count >= PROTOCOL['max_tool_calls']:
                    output = {'error': 'Research tool budget exhausted; finish using collected evidence.'}
                else:
                    output = await search.execute(call, run_dir/'tool_attempts'/rid/f'{turn:04d}-{index:03d}')
                write_json(tool_file, {'call': call, 'output': output})
            tool_count += 1
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(output, ensure_ascii=False)})
    raise ValueError('Research did not finish within the fixed turn budget')


def fit_context(messages, budget):
    """Do not silently drop the question or model reasoning. Trim older tool text only.

    Full tool outputs remain in the tool receipts. This deterministic fallback is
    necessary for legacy small context candidates; counts are included in reports.
    """
    messages = [dict(m) for m in messages]
    for m in messages:
        if len(json.dumps(messages, ensure_ascii=False).encode()) <= budget:
            return messages
        if m['role'] == 'tool' and len(m.get('content', '')) > 256:
            m['content'] = m['content'][:256] + '\n[Source excerpt truncated to fit the model context. Full source was retrieved earlier.]'
    if len(json.dumps(messages, ensure_ascii=False).encode()) > budget:
        # A single legacy-model turn can emit many more than 30 tool calls.
        # These excess calls were never executed and contain no source evidence.
        # Remove their synthetic budget-error pairs only as the final context
        # fallback; preserve all executed calls, question, content and reasoning.
        exhausted={'error':'Research tool budget exhausted; finish using collected evidence.'}
        dropped=set()
        for m in messages:
            if m['role']=='tool':
                try:
                    if json.loads(m.get('content',''))==exhausted:dropped.add(m['tool_call_id'])
                except (ValueError,TypeError):pass
        compact=[]
        for m in messages:
            if m['role']=='tool' and m.get('tool_call_id') in dropped:continue
            if m['role']=='assistant' and m.get('tool_calls'):
                m=dict(m,tool_calls=[c for c in m['tool_calls'] if c['id'] not in dropped])
                if not m['tool_calls']:m.pop('tool_calls')
            compact.append(m)
        messages=compact
    if len(json.dumps(messages, ensure_ascii=False).encode()) > budget:
        raise ValueError('Model conversation exceeds its reserved context even after source trimming')
    return messages
