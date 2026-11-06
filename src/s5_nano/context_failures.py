"""Explicit model-context failures; transport and infrastructure errors stay errors."""
import re

POLICY_ID = 'capitu-model-context-exhaustion-zero-v1'


def is_context_limit_response(status, body, expected_context=None):
    if status != 400 or not isinstance(body, dict):
        return False
    error = body.get('error', body)
    if not isinstance(error, dict):
        return False
    message = error.get('message', '')
    if message == 'Input exceeds the native model context length':
        return True
    sglang = re.fullmatch(r"The input \((\d+) tokens\) is longer than the model's context length \((\d+) tokens\)\.", message)
    if sglang:
        actual, limit = map(int, sglang.groups())
        return actual >= limit and (expected_context is None or limit == expected_context)
    match = re.search(r"maximum context length is (\d+) tokens.*prompt contains at least (\d+) input tokens", message, re.S)
    if not match:
        return False
    limit, actual = map(int, match.groups())
    return actual > limit and (expected_context is None or limit == expected_context)
