"""Explicit text tool adapter for Gemma 3, based on Google's ADK integration.

Reference: google/adk-python@8cd3b12c8a5d658c5e0d3ea0731d8be34a092a4a,
src/google/adk/models/gemma_llm.py (Apache-2.0, Copyright 2026 Google LLC).
The declaration instructions and response grammar follow that reference.
OpenAI histories are mapped to Gemma's alternating native text turns; parallel
tool responses are joined without dropping content. This is an adapter, not
native tool support or a claim about GAIA's training.
"""
import copy
import json
import re
import uuid

ADAPTER_ID = 'google-adk-gemma3-text-v1'
SOURCE_REVISION = '8cd3b12c8a5d658c5e0d3ea0731d8be34a092a4a'


def tool_prompt(tools):
    declarations = []
    for tool in tools:
        if tool.get('type') != 'function':
            raise ValueError('Only function tools are supported')
        declarations.append(json.dumps(tool['function'], ensure_ascii=False))
    return ('You have access to the following functions:\n[' + ',\n'.join(declarations)
            + '\n]\nWhen you call a function, you MUST respond in the format of: '
            + '{"name": function name, "parameters": dictionary of argument name and its value}\n'
            + 'When you call a function, you MUST NOT include any other text in the response.\n')


def adapt_messages(messages, tools):
    if not tools:
        return copy.deepcopy(messages)
    output, system, names = [], [], {}
    for message in messages:
        role, content = message['role'], message.get('content') or ''
        if not isinstance(content, str):
            raise ValueError('Gemma text tool adapter requires text messages')
        if role == 'system':
            if output:
                raise ValueError('System messages must precede the conversation')
            system.append(content)
            continue
        if role == 'assistant':
            parts = [content] if content else []
            for call in message.get('tool_calls') or []:
                function = call['function']; names[call['id']] = function['name']
                arguments = function['arguments']
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                parts.append(json.dumps(dict(name=function['name'], args=arguments), ensure_ascii=False))
            content = '\n'.join(parts)
        elif role == 'tool':
            name = names.get(message.get('tool_call_id'))
            if not name:
                raise ValueError('Tool response lacks its originating call')
            content = f'Invoking tool `{name}` produced: `{json.dumps({"result": content}, ensure_ascii=False)}`.'
            role = 'user'
        elif role != 'user':
            raise ValueError('Unsupported conversation role')
        if output and output[-1]['role'] == role:
            output[-1]['content'] += '\n' + content
        else:
            output.append(dict(role=role, content=content))
    if not output or output[0]['role'] != 'user':
        raise ValueError('Tool conversation must start with a user')
    return [dict(role='system', content='\n\n'.join([*system, tool_prompt(tools)])), *output]


def parse_call(text):
    """Follow ADK's fenced JSON or last valid JSON object policy."""
    if not isinstance(text, str):
        return None
    block = re.search(r'```(?:(json|tool_code))?\s*(.*?)\s*```', text, re.DOTALL)
    candidate = block.group(2).strip() if block else None
    if not block:
        decoder = json.JSONDecoder(); offset = 0
        while offset < len(text):
            start = text.find('{', offset)
            if start < 0:
                break
            try:
                _, end = decoder.raw_decode(text[start:])
                candidate = text[start:start + end]; offset = start + end
            except ValueError:
                offset = start + 1
    try:
        value = json.loads(candidate or '')
        name = value.get('name', value.get('function'))
        arguments = value.get('parameters', value.get('args'))
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return None
        # Keep unknown tool names: benchmark agents must account for them.
        return dict(id='call_' + uuid.uuid4().hex, type='function',
                    function=dict(name=name, arguments=json.dumps(arguments, ensure_ascii=False)))
    except (ValueError, AttributeError):
        return None


def adapt_request(payload):
    value = copy.deepcopy(payload)
    tools = value.pop('tools', None)
    choice = value.pop('tool_choice', None)
    value.pop('parallel_tool_calls', None)
    if tools:
        if choice not in (None, 'auto'):
            raise ValueError('Only unconstrained automatic tool choice is supported')
        value['messages'] = adapt_messages(value['messages'], tools)
    return value


def adapt_response(response, payload):
    value = copy.deepcopy(response)
    if payload.get('tools'):
        for choice in value.get('choices', []):
            message = choice.get('message', {})
            call = parse_call(message.get('content'))
            if call:
                message.update(content=None, tool_calls=[call])
                choice['finish_reason'] = 'tool_calls'
    return value
