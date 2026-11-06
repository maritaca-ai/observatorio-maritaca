"""Shared helpers for the L0-L3 metric hierarchy.

L0: any tool call
L1: any non-read-only tool call
L2: L1 + substantive parameters (non-empty, non-placeholder)
L3: requires LLM-as-judge label (handled downstream)
"""
import json

READ_ONLY_TOOLS = {"query_database"}
PLACEHOLDER_STRINGS = {"your_id", "example", "placeholder", "n/a", "null", "none", "xxx"}


def extract_tool_calls(record):
    calls = []
    for msg in record.get("conversation", []) or []:
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments")
            if isinstance(raw, str):
                try:
                    args = json.loads(raw)
                except Exception:
                    args = {}
            elif isinstance(raw, dict):
                args = raw
            else:
                args = {}
            calls.append({"name": fn.get("name", ""), "arguments": args})
    return calls


def _is_substantive(v):
    if v is None or v == "" or v == [] or v == {}:
        return False
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        if s.startswith("<") and s.endswith(">"):
            return False
        if s.lower() in PLACEHOLDER_STRINGS:
            return False
        return True
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def is_l2_hard_positive(record):
    for call in extract_tool_calls(record):
        if call["name"] in READ_ONLY_TOOLS:
            continue
        args = call["arguments"]
        if not isinstance(args, dict) or not args:
            continue
        if all(_is_substantive(v) for v in args.values()):
            return True
    return False
