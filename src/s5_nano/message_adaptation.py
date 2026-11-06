"""Explicit, versioned message representation; never edit a benchmark prompt."""
from copy import deepcopy

SYSTEM_TO_USER = 'system_to_first_user_v1'


def message_policy(profile):
    policy = profile.get('message_policy', 'native')
    if policy not in ('native', SYSTEM_TO_USER):
        raise ValueError('Unknown message representation policy')
    return policy


def adapt_messages(messages, profile):
    """Fold one leading text system into the first user, only when opted in.

    Keep the original request for history/cache identity. Apply this once to
    the effective request after restoring assistant reasoning. Unsupported
    shapes fail locally rather than losing fields, instructions, or tools.
    """
    policy = message_policy(profile)
    result = deepcopy(messages)
    if policy == 'native':
        return result
    if not isinstance(result, list) or not result:
        raise ValueError('System adaptation requires a nonempty message list')
    for message in result:
        if (not isinstance(message, dict)
                or message.get('role') not in ('system', 'user', 'assistant')
                or not isinstance(message.get('content'), str)
                or message.get('tool_calls') or message.get('tool_call_id')):
            raise ValueError('System adaptation supports text conversations without tools only')
    positions = [i for i, m in enumerate(result) if m['role'] == 'system']
    if not positions:
        return result
    if (positions != [0] or len(result) < 2 or result[1]['role'] != 'user'
            or set(result[0]) != {'role', 'content'}):
        raise ValueError('System adaptation requires one plain leading system followed by user')
    result[1]['content'] = result[0]['content'] + '\n\n' + result[1]['content']
    return result[1:]
