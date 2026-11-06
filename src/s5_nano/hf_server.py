"""Serial native Transformers generation for checkpoints without native vLLM support.

Uses the checkpoint's own forward/generate implementation with its recurrent
cache, pinned tokenizer/template, BF16 weights and official vLLM output parsers.
This backend is recorded separately; it is never described as native vLLM.
"""
import argparse
import fcntl
import functools
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
import uuid


def parse_reasoning(parser_class, tokenizer, text, request, template_kwargs):
    """Configure the native parser for the rendered mode and retain violations.

    Qwen3's parser defaults to an already-open reasoning block. With thinking
    disabled, a plain completion is final content. An explicitly emitted
    reasoning block must still be preserved so reasoning remains separate
    from the final content used for scoring.
    """
    kwargs = dict(template_kwargs)
    if kwargs['enable_thinking'] is False and ('<think>' in text or '</think>' in text):
        kwargs['enable_thinking'] = True
    return parser_class(tokenizer, chat_template_kwargs=kwargs).extract_reasoning(text, request)


def generation_parameters(body, context_length, prompt_length, expected_thinking=None):
    if body.get('stream') or body.get('n', 1) != 1:
        raise ValueError('Only one nonstreaming completion is supported')
    if body.get('presence_penalty', 0) or body.get('frequency_penalty', 0):
        raise ValueError('Nonzero presence/frequency penalties are unsupported by this backend')
    if body.get('response_format') not in (None, {'type': 'text'}):
        raise ValueError('Constrained decoding is unsupported by this backend')
    requested_thinking = body.get('chat_template_kwargs', {}).get('enable_thinking')
    if type(requested_thinking) is not bool:
        raise ValueError('The thinking mode must be explicitly specified')
    if expected_thinking is not None and requested_thinking is not expected_thinking:
        raise ValueError('Requested thinking mode differs from this server stage')
    remaining = context_length - prompt_length
    if remaining <= 0:
        raise ValueError('Input exceeds the native model context length')
    requested = body.get('max_tokens')
    if requested is not None and (type(requested) is not int or requested < 1 or requested > remaining):
        raise ValueError('Requested output budget exceeds available native context')
    params = dict(max_new_tokens=remaining if requested is None else requested,
                  do_sample=body['temperature'] > 0, use_cache=True,
                  repetition_penalty=body['repetition_penalty'])
    if params['do_sample']:
        params.update(temperature=body['temperature'], top_p=body['top_p'],
                      top_k=max(0, body['top_k']), min_p=body['min_p'])
    stop = body.get('stop') or []
    if isinstance(stop, str):
        stop = [stop]
    if not all(isinstance(s, str) and s for s in stop):
        raise ValueError('Invalid stop strings')
    if stop:
        params['stop_strings'] = stop
    return params


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--served-model-name', required=True)
    parser.add_argument('--chat-template', type=Path, required=True)
    parser.add_argument('--max-model-len', type=int, required=True)
    parser.add_argument('--audit-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--replicas', type=int, default=int(os.environ.get('S5_NANO_HF_REPLICAS', '1')))
    parser.add_argument('--prefill-lock', type=Path)
    parser.add_argument('--enable-thinking', choices=['true', 'false'], default='true')
    args = parser.parse_args()
    args.enable_thinking = args.enable_thinking == 'true'
    if not 1 <= args.replicas <= 16:
        raise ValueError('Native serving supports one to sixteen replicas')
    os.umask(0o077)
    if args.replicas > 1:
        from .hf_pool import serve_replicas
        serve_replicas(args)
        return
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from vllm.reasoning import ReasoningParserManager
    from vllm.tool_parsers import ToolParserManager
    from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=True)
    tokenizer.chat_template = args.chat_template.read_text()
    model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True,
        trust_remote_code=True, dtype=torch.bfloat16, attn_implementation='sdpa').to('cuda').eval()
    if model.config.max_position_embeddings != args.max_model_len:
        raise ValueError('Configured native context differs from checkpoint')
    eos = model.generation_config.eos_token_id
    eos_ids = set(eos if isinstance(eos, list) else [eos])
    reasoning_class = ReasoningParserManager.get_reasoning_parser('qwen3')
    tool_class = ToolParserManager.get_tool_parser('qwen3_coder')
    lock = threading.Lock()
    if args.prefill_lock:
        # Only large prefills share this file lock; independent decode loops
        # retain separate native model instances and recurrent caches.
        original_forward = model.forward

        @functools.wraps(original_forward)
        def forward(*positional, **keyword):
            value = keyword.get('input_ids')
            if value is None:
                value = keyword.get('inputs_embeds')
            if value is None and positional:
                value = positional[0]
            if value is not None and value.shape[1] > 1:
                with args.prefill_lock.open('a') as handle:
                    fcntl.flock(handle, fcntl.LOCK_EX)
                    result = original_forward(*positional, **keyword)
                    torch.cuda.current_stream().synchronize()
                    return result
            return original_forward(*positional, **keyword)

        model.forward = forward
    args.audit_dir.mkdir(parents=True, exist_ok=True)

    def complete(body):
        if body.get('model') != args.served_model_name:
            raise ValueError('Unexpected served model identifier')
        messages = json.loads(json.dumps(body['messages']))
        for message in messages:
            for call in message.get('tool_calls') or []:
                if isinstance(call['function']['arguments'], str):
                    call['function']['arguments'] = json.loads(call['function']['arguments'])
        prompt = tokenizer.apply_chat_template(messages, tools=body.get('tools'), tokenize=False,
            add_generation_prompt=True, **body.get('chat_template_kwargs', {}))
        encoded = tokenizer(prompt, add_special_tokens=False, return_tensors='pt')
        prompt_ids = encoded['input_ids'][0].tolist()
        params = generation_parameters(body, args.max_model_len, len(prompt_ids), args.enable_thinking)
        request = ChatCompletionRequest.model_validate(body)
        identifier, started = uuid.uuid4().hex, time.time()
        with lock, torch.inference_mode():
            if body.get('seed') is not None:
                torch.manual_seed(body['seed'])
            sequences = model.generate(**{k:v.to('cuda') for k,v in encoded.items()},
                tokenizer=tokenizer, **params)
            generated_ids = sequences[0, len(prompt_ids):].tolist()
        visible_ids = generated_ids[:-1] if generated_ids and generated_ids[-1] in eos_ids else generated_ids
        text = tokenizer.decode(visible_ids, skip_special_tokens=False)
        stop_matches = [text.index(stop) for stop in params.get('stop_strings', []) if stop in text]
        stopped = bool(stop_matches) or bool(generated_ids and generated_ids[-1] in eos_ids)
        if stop_matches:
            text = text[:min(stop_matches)]
        reason, content = parse_reasoning(reasoning_class, tokenizer, text, request,
                                          body['chat_template_kwargs'])
        calls = []
        if body.get('tools') and body.get('tool_choice') != 'none' and content:
            parsed = tool_class(tokenizer, tools=request.tools).extract_tool_calls(content, request)
            calls = [call.model_dump(mode='json') for call in parsed.tool_calls]
            content = parsed.content
        message = dict(role='assistant', content=content, reasoning=reason, reasoning_content=reason)
        if calls:
            message['tool_calls'] = calls
        finish = 'length' if not stopped and len(generated_ids) >= params['max_new_tokens'] else 'tool_calls' if calls else 'stop'
        result = dict(id='chatcmpl-'+identifier, object='chat.completion', created=int(started),
                      model=args.served_model_name, choices=[dict(index=0, message=message, finish_reason=finish)],
                      usage=dict(prompt_tokens=len(prompt_ids), completion_tokens=len(generated_ids),
                                 total_tokens=len(prompt_ids)+len(generated_ids)))
        if body.get('return_token_ids'):
            result['prompt_token_ids'] = prompt_ids
            result['choices'][0]['token_ids'] = generated_ids
        if body.get('return_prompt_text'):
            result['prompt_text'] = prompt
        with gzip.open(args.audit_dir/(identifier+'.json.gz'), 'wt') as stream:
            json.dump(dict(request=body, result=result, prompt_token_ids=prompt_ids,
                           generated_token_ids=generated_ids, raw_generated_text=text,
                           started=started, finished=time.time(), generation_parameters=params,
                           backend='transformers_native_generate', dtype='bfloat16', use_cache=True,
                           replica_pid=os.getpid(),replica_count=int(os.environ.get('S5_NANO_HF_POOL_SIZE','1'))), stream)
        return result

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, value):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == '/health':
                self.respond(200, {'status': 'ready', 'backend': 'transformers_native_generate'})
            elif self.path == '/v1/models':
                self.respond(200, dict(object='list', data=[dict(id=args.served_model_name, object='model',
                    created=0, owned_by='local', max_model_len=args.max_model_len)]))
            else:
                self.respond(404, {'error': {'message': 'Unknown endpoint'}})

        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.respond(404, {'error': {'message': 'Unknown endpoint'}})
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                result = complete(body)
                self.respond(200, result)
            except (ValueError, KeyError, TypeError) as exc:
                self.respond(400, {'error': {'message': str(exc), 'type': type(exc).__name__}})
            except Exception as exc:
                self.respond(500, {'error': {'message': str(exc), 'type': type(exc).__name__}})

    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
