"""Verify text and history without requiring tool use."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from .message_adaptation import adapt_messages, message_policy, SYSTEM_TO_USER


TEXT_BENCHMARKS = frozenset({'ifbench', 'sob', 'culturalbench',
                           'longbench_v2', 'oab_bench', 'oab_bench_3941', 'oab_bench_full',
                           'magis_bench', 'arena_hard_v2', 'harmbench', 'conduta_bench'})
TUCANO_TEXT_BENCHMARKS = frozenset({'capitu', 'assin_rte', 'broverbs', 'math_pt',
    'enade_qa', 'enem_vl', 'bluex_v2', 'mmlu_pt', 'global_mmlu_pt',
    'prosa_pt'})


def uses_text_canary(benchmark, family, profile):
    return family == 'remaining' or (
        (profile.get('transport_policy') == 'tucano_raw_completion_v1'
         or message_policy(profile) == SYSTEM_TO_USER
         or profile.get('model') in {'AIInstituteLNCC/manaca-1b-instruct',
                                    'latam-gpt/Llama-3.1-70B-LatamGPT-SFT-1.0'})
        and benchmark in TUCANO_TEXT_BENCHMARKS)


def sha(value):
    return hashlib.sha256(value).hexdigest()




def rendered_history(messages, profile):
    rendered = deepcopy(messages)
    for message in rendered:
        if message.get('role') != 'assistant':
            continue
        reasoning = message.get('reasoning_content') or message.get('reasoning')
        if not reasoning:
            continue
        if profile.get('history_encoding', 'qwen_think_tags') == 'reasoning_field':
            message['reasoning_content'] = reasoning
            message.pop('reasoning', None)
        else:
            message['content'] = '<think>\n' + reasoning + '\n</think>\n\n' + (message.get('content') or '')
            message.pop('reasoning_content', None)
            message.pop('reasoning', None)
    return adapt_messages(rendered, profile)


def canary(runtime, base, api_base, model, profile, tokenizer_path, template_path):
    from transformers import AutoTokenizer
    from .runtime import post, save, generation_prompt_ids

    runtime = Path(runtime)
    task = runtime.parent.name
    if task not in TEXT_BENCHMARKS and not uses_text_canary(task, '', profile):
        raise ValueError('Unsupported remaining-benchmark canary scope')
    # Private checkpoints select their served name explicitly on the CLI. Their
    # frozen profiles intentionally contain no public Hub model identifier.
    if not isinstance(model, str) or not model or (profile.get('model') and profile['model'] != model):
        raise ValueError('Canary model differs from profile')
    if (runtime / 'canary_verified.json').exists():
        raise RuntimeError('Existing canary requires audit; no repeated dispatch')
    for name in ['candidate_attempts.jsonl', 'http_attempts.jsonl']:
        if (runtime / name).exists() and (runtime / name).stat().st_size:
            raise RuntimeError('Existing canary attempts require audit; no repeated dispatch')
    template = Path(template_path).read_bytes()
    if sha(template) != profile['chat_template_sha256']:
        raise ValueError('Canary template differs from profile')
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    tokenizer.chat_template = template.decode()
    messages = [dict(role='system', content='Responda em português.'),
                dict(role='user', content='Diga uma frase curta sobre uma árvore.')]
    if profile.get('model') == 'AIInstituteLNCC/manaca-1b-instruct' and message_policy(profile) == 'native':
        # The native Manaca profile rejects system roles. Probe supported text
        # without applying the separately declared system-folding variant.
        messages = [dict(role='user', content='Responda em português. Diga uma frase curta sobre uma árvore.')]
    followup = 'Agora resuma sua frase em poucas palavras.'
    # The pinned Gemma4 template (also used by Nemotron Bolt) adds a space
    # after list-valued system text. vLLM's native OpenAI content format wraps
    # a string in text parts before rendering. Use that explicit shape in this
    # synthetic probe so the independent local render sees the same input.
    # Benchmark messages, model profiles and the original template are unchanged.
    if profile.get('reasoning_parser') == 'gemma4':
        messages[0]['content'] = [dict(type='text', text=messages[0]['content'])]
    diagnostics = []
    expected = profile['enable_thinking']
    for turn in range(2):
        request = dict(model=model, messages=messages, temperature=0, max_tokens=1,
                       chat_template_kwargs={'enable_thinking': not expected},
                       return_token_ids=True, return_prompt_text=True)
        response = post(base, '/canary/v1/chat/completions', request)
        answer = response['choices'][0]['message']
        # This gate verifies transport, profile and rendered history, not answer
        # quality. Empty finals and context-limited output are native outcomes;
        # benchmark scoring must handle them without changing the generation.
        if answer.get('role') != 'assistant' or any(
                answer.get(key) is not None and not isinstance(answer[key], str)
                for key in ('content', 'reasoning_content', 'reasoning')):
            raise ValueError('Canary returned an invalid assistant text message')
        finish_reason = response['choices'][0]['finish_reason']
        if finish_reason not in ('stop', 'length') or answer.get('tool_calls'):
            raise ValueError('Canary did not return a terminal text response')
        prompt = tokenizer.apply_chat_template(rendered_history(messages, profile), tokenize=False,
            add_generation_prompt=True, **dict(profile.get('chat_template_kwargs', {}), enable_thinking=expected))
        tokens = generation_prompt_ids(response)
        save(runtime / ('canary_prompt_diagnostic_' + str(turn) + '.json'), dict(
            local_prompt=prompt, server_prompt=response.get('prompt_text'), server_token_ids=tokens,
            local_token_ids=tokenizer.encode(prompt, add_special_tokens=False)))
        if tokens != tokenizer.encode(prompt, add_special_tokens=False) or response['usage']['prompt_tokens'] != len(tokens):
            raise ValueError('Canary generation tokenization differs')
        if response.get('prompt_text') is not None and response['prompt_text'] != prompt:
            raise ValueError('Canary generation prompt differs')
        if profile.get('history_encoding', 'qwen_think_tags') == 'qwen_think_tags' and prompt.endswith('<think>\n') is not expected:
            raise ValueError('Canary rendered thinking mode differs')
        diagnostics.append(dict(turn=turn, tokens=len(tokens), prompt_sha256=sha(prompt.encode()),
            finish_reason=finish_reason, final_chars=len(answer.get('content') or ''),
            reasoning_chars=len(answer.get('reasoning_content') or answer.get('reasoning') or '')))
        if turn == 0:
            messages.append({k: v for k, v in answer.items() if k in ('role', 'content', 'reasoning_content', 'reasoning')})
            messages.append(dict(role='user', content=followup))
    rows = [json.loads(line) for line in (runtime / 'effective_requests_secondary.jsonl').read_text().splitlines()]
    applied = [row['applied'] for row in rows if row.get('status') == 'forwarding' and row.get('benchmark') == 'canary']
    if len(applied) != 2:
        raise ValueError('Unexpected canary dispatch count; audit required')
    for values in applied:
        if 'generation_stop' in profile and values.get('stop') != profile['generation_stop']:
            raise ValueError('Effective canary stop sequences differ')
        if (values['enable_thinking'] is not expected or values['max_tokens'] != profile['max_tokens'] or
                any(values[key] != value for key, value in profile['sampling'].items())):
            raise ValueError('Effective canary profile differs')
    save(runtime / 'canary_verified.json', dict(passed=True, time=time.time(),
        scope='text_system_history',
        thinking_received=expected, actual_prompt_tokens_match=True, preset=profile['sampling'],
        max_tokens=profile['max_tokens'], template_sha256=profile['chat_template_sha256'], turns=diagnostics))
