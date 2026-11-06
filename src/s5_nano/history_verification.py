"""Verify preserved assistant history against original private HTTP responses."""
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path


def plain_content(m, *, strip_thinking_tags=True):
 c=m.get('content') or ''
 if strip_thinking_tags and m.get('role')=='assistant' and isinstance(c,str) and '</think>' in c:
  c=c.split('</think>',1)[1].lstrip('\n')
 return c

def key(messages,conversation_id=None, *, strip_thinking_tags=True):
 canon=[]
 for m in messages:
  n={k:v for k,v in m.items() if k in ('role','content','name','tool_call_id','tool_calls') and v is not None}
  n['content']=plain_content(m,strip_thinking_tags=strip_thinking_tags)
  if not n.get('tool_calls'):n.pop('tool_calls',None)
  if n.get('tool_calls'):
   n['tool_calls']=json.loads(json.dumps([{k:v for k,v in x.items() if k!='index'} for x in n['tool_calls']]))
   for call in n['tool_calls']:
    arguments=call.get('function',{}).get('arguments')
    if isinstance(arguments,str):
     try:call['function']['arguments']=json.loads(arguments)
     except ValueError:pass
  canon.append(n)
 value=canon if conversation_id is None else dict(conversation_id=conversation_id,messages=canon)
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def signature(messages):
    clean = []
    for message in messages:
        if message.get('tool_calls') or message.get('tool_call_id'):
            raise ValueError('This verifier supports CAPITU text conversations only')
        clean.append(dict(role=message['role'], content=message.get('content') or ''))
    return json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def verify_capitu_history(runtime, profile, expected_responses=500, expected_history_turns=300):
    records, hashes = [], {}
    for path in sorted((Path(runtime) / 'raw_api').glob('*.json.gz')):
        raw = path.read_bytes()
        row = json.loads(gzip.decompress(raw))
        if row.get('benchmark') != 'capitu':
            continue
        records.append(row)
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
    if len(records) != expected_responses:
        raise ValueError('Unexpected number of original CAPITU responses')
    origins = defaultdict(list)
    for row in records:
        if row['status'] != 200 or row['finish_reason'] not in ('stop', 'length'):
            raise ValueError('Unfinished originating response')
        request, effective, answer = row['request'], row['effective_request'], row['answer']
        if effective['chat_template_kwargs'].get('enable_thinking') is not profile['enable_thinking']:
            raise ValueError('Effective reasoning mode differs')
        if effective.get('max_tokens') != profile['max_tokens']:
            raise ValueError('Effective output limit differs')
        if any(effective.get(k) != v for k, v in profile['sampling'].items()):
            raise ValueError('Effective sampling differs')
        if len(request['messages']) != len(effective['messages']):
            raise ValueError('Message history length differs')
        trace = answer.get('reasoning_content') or answer.get('reasoning') or ''
        if not isinstance(trace, str):
            raise ValueError('Nontext originating reasoning')
        origins[signature(request['messages'] + [answer])].append((row['time'], trace))
    counts = dict(responses=len(records), assistant_history_turns=0,
                  nonempty_reasoning_retained=0, verified_empty_reasoning_history=0,
                  responses_without_reasoning=sum(not (r['answer'].get('reasoning_content') or r['answer'].get('reasoning')) for r in records))
    for row in records:
        original = row['request']['messages']
        for index, (message, effective) in enumerate(zip(original, row['effective_request']['messages'])):
            if message['role'] != 'assistant':
                if message != effective:
                    raise ValueError('Non-assistant message changed')
                continue
            counts['assistant_history_turns'] += 1
            known = {trace for timestamp, trace in origins[signature(original[:index + 1])] if timestamp < row['time']}
            if not known:
                raise ValueError('Assistant turn has no originating HTTP response')
            trace = effective.get('reasoning_content') or effective.get('reasoning') or ''
            final = effective.get('content') or ''
            if profile.get('history_encoding', 'qwen_think_tags') == 'qwen_think_tags' and '</think>' in final:
                if not final.startswith('<think>\n'):
                    raise ValueError('Unexpected reasoning encoding')
                trace, final = final[len('<think>\n'):].split('\n</think>\n\n', 1)
            if final != (message.get('content') or '') or trace not in known:
                raise ValueError('Original reasoning or final answer was lost or changed')
            counts['nonempty_reasoning_retained' if trace else 'verified_empty_reasoning_history'] += 1
    if counts['assistant_history_turns'] != expected_history_turns:
        raise ValueError('Unexpected number of assistant history turns')
    return dict(passed=True, **counts, source_response_sha256=hashes,
                operation='verify_original_history_without_generation_or_modification')


def verify_capitu_instances(source, conversations, *, strict=True, split="multi", include_origins=False):
    """Bind history to each saved case/turn, even when final texts are equal."""
    source=Path(source);origins=defaultdict(list);hashes={}
    if split not in ('single','multi'):raise ValueError('Unknown CAPITU split')
    for path in (source/'runtime/raw_api').glob('*.json.gz'):
        raw=path.read_bytes();row=json.loads(gzip.decompress(raw))
        if row.get('benchmark')!='capitu':continue
        hashes[str(path.relative_to(source))]=hashlib.sha256(raw).hexdigest()
        row['_origin_path']=str(path.relative_to(source))
        origins[signature(row['request']['messages']+[row['answer']])].append(row)
    proof=dict(passed=True,matched_turns=0,history_turns=0,errors=[],source_sha256=hashes)
    if include_origins:proof['origins']=[]
    for conversation in conversations:
        messages=[];previous=[]
        for turn in conversation['turns']:
            messages.append(dict(role='user',content=turn['prompt']))
            current=messages+[dict(role='assistant',content=turn['response'])]
            path=source/'results/capitu/turns'/split/str(conversation['key'])/(str(turn['turn'])+'.json')
            if not path.exists():
                if turn.get('generated') is False:continue
                raise ValueError('Saved CAPITU turn is missing')
            raw=path.read_bytes();cache=json.loads(raw)
            hashes[str(path.relative_to(source))]=hashlib.sha256(raw).hexdigest()
            if cache.get('generated') is False:continue
            wanted=hashlib.sha256(json.dumps(dict(messages=messages,system=None),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if cache['signature']!=wanted or cache['content']!=turn['response']:
                raise ValueError('Saved CAPITU case/turn identity differs')
            scope=f'capitu:{split}:{conversation["key"]}'
            candidates=[r for r in origins[signature(current)]
                if r['status']==200 and r['finish_reason'] in ('stop','length') and r['time']<=cache['time']
                and r['request'].get('campaign_conversation_id',scope)==scope
                and all((r.get('usage') or {}).get(k)==cache['usage'].get(k)
                        for k in ['prompt_tokens','completion_tokens','total_tokens'])]
            expected={r['answer'].get('reasoning_content') or r['answer'].get('reasoning') or '' for r in candidates}
            if not candidates or len(expected)!=1:
                proof['errors'].append(dict(case_key=conversation['key'],turn=turn['turn'],reason='unproven_origin'))
            else:
                proof['matched_turns']+=1
                if include_origins:
                    proof['origins'].append(dict(case_key=conversation['key'],turn=turn['turn'],
                        files=[r['_origin_path'] for r in candidates]))
            for index,traces in previous:
                proof['history_turns']+=1;actual=set()
                for row in candidates:
                    message=row['effective_request']['messages'][index]
                    text=message.get('content') or ''
                    trace=message.get('reasoning_content') or message.get('reasoning') or ''
                    if text.startswith('<think>\n') and '\n</think>\n\n' in text:
                        trace,text=text[len('<think>\n'):].split('\n</think>\n\n',1)
                    if text!=(messages[index].get('content') or ''):
                        proof['errors'].append(dict(case_key=conversation['key'],turn=turn['turn'],reason='changed_final'))
                    actual.add(trace)
                if len(actual)!=1 or len(traces)!=1 or actual!=traces:
                    proof['errors'].append(dict(case_key=conversation['key'],turn=turn['turn'],history_index=index,reason='wrong_case_reasoning'))
            previous.append((len(messages),expected));messages=current
    proof['passed']=not proof['errors']
    if strict and not proof['passed']:
        raise ValueError('CAPITU history differs from its originating case/turn; withhold the conversation score')
    return proof
