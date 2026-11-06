"""Pinned Tucano chat adapter over raw vLLM completions, with durable evidence.

No model is loaded here. The independent raw vLLM server does generation only;
this adapter renders the checkpoint template and archives output before parsing.
"""
import argparse
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

class TucanoHTTPServer(ThreadingHTTPServer):
    # Match the evaluation proxy's backlog for bursts from concurrent workers.
    request_queue_size = 256


VLLM_VERSION = '0.31.0'
POLICY = 'tucano_raw_completion_v1'
SAMPLING = dict(temperature=.1, top_p=1., top_k=50, min_p=0.,
                presence_penalty=0., repetition_penalty=1.2)
REVISIONS = {'thinking': '12fb8714e73b42e1fffd1df6a4d6cb1f077a854d',
             'instruct': '95727a44113a9507bba860cf7427aa327fc331ec'}
MODELS = {mode: 'Polygl0t/Tucano2-qwen-3.7B-' + suffix
          for mode, suffix in [('thinking', 'Think'), ('instruct', 'Instruct')]}


class ContextWindowExceeded(ValueError):
    def __init__(self, input_tokens, context_length):
        super().__init__('Input exceeds the native model context length')
        self.input_tokens = input_tokens
        self.context_length = context_length


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def validate_profile(profile):
    mode = profile.get('mode')
    if (mode not in MODELS or profile.get('model') != MODELS[mode]
            or profile.get('revision') != REVISIONS[mode]
            or profile.get('enable_thinking') is not (mode == 'thinking')
            or profile.get('sampling') != SAMPLING
            or profile.get('context_length') != 4096
            or profile.get('max_tokens', 'missing') is not None
            or profile.get('precision') != 'bfloat16'
            or profile.get('history_encoding') != 'reasoning_field'
            or profile.get('history_content_policy') != 'literal'
            or profile.get('transport_policy') != POLICY):
        raise ValueError('Expected the pinned, independent Tucano profile')
    assets = {'config.json', 'tokenizer.json', 'tokenizer_config.json',
              'special_tokens_map.json', 'chat_template.jinja', 'generation_config.json',
              'model.safetensors.index.json'}
    weights = {'model-00001-of-00002.safetensors', 'model-00002-of-00002.safetensors'}
    if (set(profile.get('asset_sha256', {})) != assets
            or set(profile.get('weight_sha256', {})) != weights
            or profile.get('chat_template_sha256') != profile['asset_sha256']['chat_template.jinja']):
        raise ValueError('Complete checkpoint hashes are required')


def verify_assets(profile, model_dir, *, weights=True):
    """CPU tests use weights=False explicitly; serving always verifies weights."""
    validate_profile(profile)
    expected = dict(profile['asset_sha256'])
    if weights:
        expected.update(profile['weight_sha256'])
    for name, wanted in expected.items():
        if Path(name).name != name or digest(Path(model_dir) / name) != wanted:
            raise ValueError('Checkpoint file mismatch: ' + name)
    config = json.loads((Path(model_dir) / 'config.json').read_text())
    if config['max_position_embeddings'] != 4096:
        raise ValueError('Checkpoint context differs from profile')


def parse_output(text, *, thinking, tool_names=()):
    """Explicit spans; tool JSON is opaque to reasoning markers inside strings.

    Malformed/unadvertised calls remain literal content (model output, not a
    transport error). Unclosed thinking remains reasoning. No whitespace trim.
    """
    content, reasoning, calls, warnings = [], [], [], []
    inside = False
    i = 0
    decoder = json.JSONDecoder()
    while i < len(text):
        if not inside and tool_names and text.startswith('<tool_call>', i):
            start = i + len('<tool_call>')
            start += len(text[start:]) - len(text[start:].lstrip())
            try:
                call, end = decoder.raw_decode(text, start)
                end += len(text[end:]) - len(text[end:].lstrip())
                valid = (isinstance(call, dict) and set(call) == {'name', 'arguments'}
                         and call['name'] in tool_names and isinstance(call['arguments'], dict)
                         and text.startswith('</tool_call>', end))
            except (ValueError, TypeError):
                valid = False
            if valid:
                calls.append(dict(id='call_' + uuid.uuid4().hex, type='function',
                                  function=dict(name=call['name'], arguments=json.dumps(
                                      call['arguments'], ensure_ascii=False, separators=(',', ':')))))
                i = end + len('</tool_call>')
                continue
            warnings.append('unparsed_tool_call')
            # A malformed/unknown tool payload is literal output, including any
            # reasoning-like strings inside it. Never manufacture an execution.
            closing = text.find('</tool_call>', start)
            end = len(text) if closing < 0 else closing + len('</tool_call>')
            content.append(text[i:end])
            i = end
            continue
        if thinking and not inside and text.startswith('<think>', i):
            inside = True
            i += len('<think>')
        elif thinking and inside and text.startswith('</think>', i):
            inside = False
            i += len('</think>')
        else:
            (reasoning if inside else content).append(text[i])
            i += 1
    if inside:
        warnings.append('unfinished_reasoning')
    return dict(content=''.join(content), reasoning_content=''.join(reasoning),
                tool_calls=calls, warnings=warnings)


def prepare_request(body, profile, tokenizer):
    validate_profile(profile)
    if not isinstance(body, dict) or body.get('model') != profile['model']:
        raise ValueError('Unexpected candidate model')
    allowed = set(SAMPLING) | {
        'model', 'messages', 'tools', 'tool_choice', 'parallel_tool_calls', 'n',
        'stream', 'stop', 'seed', 'response_format', 'chat_template_kwargs',
        'max_tokens', 'max_completion_tokens', 'max_new_tokens', 'max_output_tokens',
        'user', 'metadata', 'service_tier', 'store', 'structured_outputs',
        'guided_json', 'guided_regex', 'logit_bias', 'ignore_eos',
        'truncate_prompt_tokens', 'min_tokens', 'logprobs', 'frequency_penalty',
        'reasoning_effort', 'extra_body', 'return_token_ids', 'return_prompt_text',
    }
    if set(body) - allowed:
        raise ValueError('Unknown request fields: ' + ', '.join(sorted(set(body) - allowed)))
    for field in ('return_token_ids', 'return_prompt_text'):
        if field in body and type(body[field]) is not bool:
            raise ValueError('Audit flags must be boolean: ' + field)
    # Existing canaries request these diagnostics. The campaign always retains
    # and returns them, including when callers omit the flags or pass False.
    if body.get('parallel_tool_calls') is False:
        raise ValueError('Restricting the number of tool calls is not supported')
    if body.get('stream') or body.get('n', 1) != 1:
        raise ValueError('Only one nonstreaming completion is supported')
    if body.get('response_format') not in (None, {'type': 'text'}):
        raise ValueError('Constrained decoding is not supported')
    for field in ('structured_outputs', 'guided_json', 'guided_regex', 'logit_bias',
                  'ignore_eos', 'truncate_prompt_tokens', 'min_tokens', 'logprobs',
                  'frequency_penalty', 'reasoning_effort', 'extra_body'):
        if body.get(field):
            raise ValueError('Unsupported generation control: ' + field)
    kwargs = body.get('chat_template_kwargs') or {}
    if (set(kwargs) - {'enable_thinking'} or
            ('enable_thinking' in kwargs and kwargs['enable_thinking'] is not profile['enable_thinking'])):
        raise ValueError('Template options cannot change the pinned checkpoint')
    messages = copy.deepcopy(body.get('messages'))
    if not isinstance(messages, list) or not messages:
        raise ValueError('Nonempty messages are required')
    for message in messages:
        if message.get('role') not in ('system', 'user', 'assistant', 'tool'):
            raise ValueError('Unsupported message role')
        if not isinstance(message.get('content'), str) and not (
                message.get('role') == 'assistant' and message.get('content') is None):
            raise ValueError('Only text messages are supported')
        reason = message.get('reasoning_content', message.get('reasoning'))
        if reason is not None:
            if not isinstance(reason, str) or (reason and not profile['enable_thinking']):
                raise ValueError('Unexpected reasoning history')
            message['reasoning_content'] = reason
        for call in message.get('tool_calls') or []:
            function = call['function']
            if isinstance(function['arguments'], str):
                function['arguments'] = json.loads(function['arguments'])
            if not isinstance(function['arguments'], dict):
                raise ValueError('Tool arguments must be an object')
    tools = body.get('tools') or []
    names = []
    for tool in tools:
        if tool.get('type') != 'function' or not isinstance(tool.get('function', {}).get('name'), str):
            raise ValueError('Only named function tools are supported')
        names.append(tool['function']['name'])
    if len(names) != len(set(names)):
        raise ValueError('Duplicate tool names')
    choice = body.get('tool_choice') or 'auto'
    if choice not in ('auto', 'none'):
        raise ValueError('Forced tool choice requires a separate protocol')
    prompt = tokenizer.apply_chat_template(messages, tools=tools or None,
                                           tokenize=False, add_generation_prompt=True)
    ids = tokenizer.encode(prompt, add_special_tokens=False)
    remaining = profile['context_length'] - len(ids)
    if remaining <= 0:
        raise ContextWindowExceeded(len(ids), profile['context_length'])
    stops = body.get('stop') or []
    stops = [stops] if isinstance(stops, str) else stops
    if not isinstance(stops, list) or not all(isinstance(s, str) and s for s in stops):
        raise ValueError('Invalid stop strings')
    raw = dict(model=profile['model'], prompt=ids, **profile['sampling'],
               max_tokens=remaining, n=1, stream=False, echo=False,
               stop=stops, skip_special_tokens=False, spaces_between_special_tokens=False,
               include_stop_str_in_output=True, return_token_ids=True)
    if body.get('seed') is not None:
        if type(body['seed']) is not int:
            raise ValueError('Seed must be an integer')
        raw['seed'] = body['seed']
    return dict(prompt=prompt, prompt_token_ids=ids, messages=messages,
                tool_names=names if choice == 'auto' else [], raw_request=raw)


def interpret_completion(response, prepared, profile, tokenizer):
    if response.get('model') != profile['model'] or len(response.get('choices', [])) != 1:
        raise ValueError('Unexpected completion identity/count')
    choice = response['choices'][0]
    ids = choice.get('token_ids')
    if (not isinstance(ids, list) or not all(type(t) is int and t >= 0 for t in ids)
            or choice.get('prompt_token_ids') != prepared['prompt_token_ids']):
        raise ValueError('Original prompt/output token IDs are required')
    usage = response['usage']
    if (usage['prompt_tokens'] != len(prepared['prompt_token_ids'])
            or usage['completion_tokens'] != len(ids)
            or usage['total_tokens'] != usage['prompt_tokens'] + len(ids)
            or len(ids) > prepared['raw_request']['max_tokens']
            or choice['finish_reason'] not in ('stop', 'length')):
        raise ValueError('Completion usage/finish reason differs from raw IDs')
    # Re-decode actual IDs: never try to reconstruct tokenization from text.
    raw_text = tokenizer.decode(ids, skip_special_tokens=False, spaces_between_special_tokens=False)
    visible_ids = ids[:-1] if ids and ids[-1] == tokenizer.eos_token_id else ids
    visible = tokenizer.decode(visible_ids, skip_special_tokens=False, spaces_between_special_tokens=False)
    stop = choice.get('stop_reason')
    if isinstance(stop, str):
        if stop not in prepared['raw_request']['stop'] or stop not in raw_text:
            raise ValueError('Unknown or missing reported stop string')
        visible = raw_text[:raw_text.index(stop)]
    parsed = parse_output(visible, thinking=profile['enable_thinking'],
                          tool_names=prepared['tool_names'])
    message = dict(role='assistant', content=parsed['content'],
                   reasoning_content=parsed['reasoning_content'])
    if parsed['tool_calls']:
        message['tool_calls'] = parsed['tool_calls']
    finish = choice['finish_reason']
    if parsed['tool_calls'] and finish == 'stop':
        finish = 'tool_calls'
    result = dict(id=response['id'], object='chat.completion', created=response['created'],
                  model=profile['model'], choices=[dict(index=0, message=message,
                      finish_reason=finish, stop_reason=stop, token_ids=ids)], usage=usage,
                  prompt_token_ids=prepared['prompt_token_ids'], prompt_text=prepared['prompt'])
    return result, dict(raw_generated_text=raw_text, visible_text=visible,
                        parse_warnings=parsed['warnings'])


def durable_json(path, value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)
    directory = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def complete(body, profile, tokenizer, audit_dir, upstream):
    prepared = prepare_request(body, profile, tokenizer)
    attempt = uuid.uuid4().hex
    folder = Path(audit_dir) / attempt
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    durable_json(folder / 'request.json', dict(request=body, prepared=prepared,
                 profile=profile, policy=POLICY, started=time.time()))
    try:
        response = upstream(prepared['raw_request'])  # Exactly one dispatch; no retries.
    except Exception as exc:
        durable_json(folder / 'transport_error.json', dict(error_type=type(exc).__name__,
                     outcome='uncertain_or_failed; reconcile before retry', time=time.time()))
        exc.tucano_audit_id = attempt
        raise
    # This must happen BEFORE validation or interpretation, including on failure.
    durable_json(folder / 'raw_response.json', response)
    try:
        result, evidence = interpret_completion(response, prepared, profile, tokenizer)
    except Exception as exc:
        durable_json(folder / 'interpretation_error.json', dict(error_type=type(exc).__name__, time=time.time()))
        exc.tucano_audit_id = attempt
        raise
    result['tucano_audit_id'] = attempt
    durable_json(folder / 'interpreted.json', dict(response=result, **evidence, finished=time.time()))
    return result


def json_http(url, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=21600) as response:
        return json.load(response)


def check_upstream(base, profile, get=json_http):
    url = urlsplit(base)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.query or url.fragment or url.username:
        raise ValueError('Raw vLLM must be reached through a loopback endpoint/tunnel')
    if get(base + '/version').get('version') != VLLM_VERSION:
        raise ValueError('Unexpected vLLM version')
    models = get(base + '/v1/models')['data']
    if len(models) != 1 or models[0]['id'] != profile['model'] or models[0].get('max_model_len') != 4096:
        raise ValueError('Upstream model/context identity mismatch')


def make_handler(profile, tokenizer, audit_dir, upstream):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/health':
                self.send_json(200, dict(status='ready', policy=POLICY))
            elif self.path == '/v1/models':
                self.send_json(200, dict(object='list', data=[dict(id=profile['model'],
                    object='model', max_model_len=4096)]))
            else:
                self.send_json(404, dict(error='Unknown endpoint'))

        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.send_json(404, dict(error='Unknown endpoint'))
                return
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 8 * 1024 * 1024:
                    raise ValueError('Invalid request length')
                body = json.loads(self.rfile.read(length))
                prepare_request(body, profile, tokenizer)  # Reject before dispatch.
            except ContextWindowExceeded as exc:
                self.send_json(400, dict(error=dict(message=str(exc),
                    type='invalid_request_error', code='context_length_exceeded',
                    input_tokens=exc.input_tokens, context_length=exc.context_length),
                    new_model_call=False))
                return
            except (ValueError, KeyError, TypeError, AttributeError):
                self.send_json(400, dict(error='Invalid Tucano request; no generation dispatched'))
                return
            try:
                result = complete(body, profile, tokenizer, audit_dir, upstream)
            except Exception as exc:
                self.send_json(422, dict(error=dict(code='generation_audit_required',
                    message='Generation/interpretation failed; inspect durable attempt before any retry'),
                    retry_allowed=False, dispatch_may_have_occurred=True,
                    tucano_audit_id=getattr(exc, 'tucano_audit_id', None)))
                return
            self.send_json(200, result)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--audit-dir', type=Path, required=True)
    parser.add_argument('--upstream', default='http://127.0.0.1:8000')
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    os.umask(0o077)
    profile = json.loads(args.profile.read_text())
    verify_assets(profile, args.model_dir)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True, trust_remote_code=False)
    tokenizer.chat_template = (args.model_dir / 'chat_template.jinja').read_text()
    base = args.upstream.rstrip('/')
    check_upstream(base, profile)
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    durable_json(args.audit_dir / ('startup-' + uuid.uuid4().hex + '.json'),
                 dict(profile=profile, backend='vllm', version=VLLM_VERSION,
                      policy=POLICY, weights_verified=True, time=time.time()))
    TucanoHTTPServer(('127.0.0.1', args.port), make_handler(profile, tokenizer,
        args.audit_dir, lambda body: json_http(base + '/v1/completions', body))).serve_forever()


if __name__ == '__main__':
    main()
