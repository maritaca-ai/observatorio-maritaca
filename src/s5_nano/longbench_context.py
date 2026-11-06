"""Offline validation of native LongBench truncation and serialized context."""
import hashlib
import json
from types import SimpleNamespace


def input_budget(profile, context_policy):
    context = profile['context_length']
    budget = context_policy['input_budgets'].get(str(context))
    if type(budget) is not int or not 0 < budget < context:
        raise ValueError('LongBench needs an explicit input budget below the profile context')
    return budget


def render_native_context(native, prompt, tokenizer, model, profile, budget):
    """Capture the pinned native request without ever creating a model client.

    Validate after native encode/truncate/decode AND chat serialization. Empty
    template overhead alone cannot bound tokenization at the splice boundary.
    Native max_new_tokens=128 is retained as request provenance; the campaign
    proxy still applies profile.max_tokens, including null (context bounded).
    """
    requests = []

    def capture(**request):
        requests.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=''))])

    native.model_map = {model: model}
    native.maxlen_map = {model: budget}
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
    native.query_llm(prompt, model, tokenizer, client, temperature=.1, max_new_tokens=128)
    if len(requests) != 1:
        raise ValueError('Native LongBench serialization did not produce exactly one request')
    request = requests[0]
    if request['model'] != model:
        raise ValueError('Native LongBench model identity changed')
    kwargs = dict(profile.get('chat_template_kwargs', {}), enable_thinking=profile['enable_thinking'])
    ids = tokenizer.apply_chat_template(request['messages'], tokenize=True,
                                       add_generation_prompt=True, return_dict=False, **kwargs)
    if not isinstance(ids, list) or any(type(token) is not int for token in ids):
        raise ValueError('LongBench serialization must return a flat list of token IDs')
    remaining = profile['context_length'] - len(ids)
    output_limit = profile['max_tokens']
    required = 1 if output_limit is None else output_limit
    if type(required) is not int or required < 1 or remaining < required:
        raise ValueError('LongBench serialized prompt leaves insufficient profile generation space')
    original = len(tokenizer.encode(prompt))
    evidence = dict(original_prompt_tokens=original, input_budget_tokens=budget,
                    truncated=original > budget, effective_prompt_tokens=len(ids),
                    generation_space=remaining, profile_max_tokens=output_limit,
                    native_requested_max_tokens=request['max_tokens'],
                    serialized_tokens_sha256=hashlib.sha256(json.dumps(ids).encode()).hexdigest())
    return request, evidence
