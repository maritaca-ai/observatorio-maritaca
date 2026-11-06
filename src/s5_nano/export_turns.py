"""Match final saved conversation turns to recorded outbound requests, offline."""
import concurrent.futures as cf,gzip,json,os
from pathlib import Path
from .export_metadata import read,params,digest

def signature(m):return digest([m.get('content'),m.get('reasoning') or m.get('reasoning_content'),m.get('tool_calls')])
def process(spec,root):
    name=f"{spec['model_id']}--{spec['mode']}--{spec['task']}{spec.get('part','')}.jsonl.gz"
    source=root/'native'/name;target=root/'tool-meta'/name
    if target.exists():return {'name':name,'cached':True}
    if not source.exists():return {'name':name,'absent':True}
    base=Path(spec['root']);manifest=read(base/'run_manifest.json') if (base/'run_manifest.json').exists() else {}
    base=Path(spec.get('generation_root') or manifest.get('generation_source') or manifest.get('historical_generation_location') or base)
    by_message={};by_capitu={};count=0
    for p in (base/'runtime/raw_api').glob('*.json.gz'):
        x=read(p)
        if x.get('status')!=200 or x.get('benchmark')=='canary':continue
        m=x.get('answer') or {};req=x.get('effective_request')
        if not req:continue
        v={'parameters':params(req),'usage':x.get('usage'),'messages':req.get('messages'),'tools':req.get('tools'),
           'finish_reason':x.get('finish_reason'),'final':m.get('content'),'reasoning':m.get('reasoning_content') or m.get('reasoning')}
        key=signature(m)
        by_message[key]=v if key not in by_message or by_message[key]==v else None
        u=x.get('usage') or {}
        key=digest([m.get('content'),u.get('prompt_tokens'),u.get('completion_tokens')])
        by_capitu[key]=v if key not in by_capitu or by_capitu[key]==v else None
    with gzip.open(source,'rt') as src,gzip.open(target.with_suffix('.partial'),'wt',compresslevel=3) as dest:
        for l in src:
            row=json.loads(l)
            if row['kind']!='generation':continue
            matched=[]
            if row.get('turns'):
                for t in row['turns']:
                    v=by_capitu.get(digest([t.get('response'),t.get('prompt_tokens'),t.get('completion_tokens')]))
                    if v:matched.append(v)
            else:
                trace=row.get('trajectory') or row.get('conversation_generated') or row.get('conversation') or []
                for m in trace:
                    if not isinstance(m,dict) or m.get('role')!='assistant':continue
                    v=by_message.get(signature(m))
                    if v:matched.append(v)
            if matched:
                count+=1;dest.write(json.dumps({'case_id':row['case_id'],'turns':matched},ensure_ascii=False,separators=(',',':'))+'\n')
    target.with_suffix('.partial').rename(target)
    return {'name':name,'cases_with_wire':count}
