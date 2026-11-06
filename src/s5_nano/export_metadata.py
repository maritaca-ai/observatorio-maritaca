"""Offline read-only source collector; output only in an owned export directory."""
import argparse, base64, concurrent.futures as cf, gzip, hashlib, json, os
from collections import defaultdict
from pathlib import Path

PARAMS = ('temperature','top_p','top_k','min_p','presence_penalty','frequency_penalty',
          'repetition_penalty','max_tokens','max_completion_tokens','max_output_tokens',
          'stop','seed','n','chat_template_kwargs','reasoning_effort','reasoning',
          'response_format','text','tool_choice','parallel_tool_calls','verbosity')
REPLAY = {'global_mmlu_pt','mmlu_pt_high_school','mmlu_pt_undergraduate'}
def read(p):
    with gzip.open(p,'rt') if str(p).endswith('.gz') else open(p) as f:return json.load(f)
def lines(p):
    if not p.exists():return
    with p.open() as f:
        for l in f:
            if l.strip():yield json.loads(l)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def params(req):
    out={k:req[k] for k in PARAMS if k in req}
    if isinstance(req.get('extra_body'),dict):out.update(params(req['extra_body']))
    return out
def message(raw):
    return (raw.get('choices') or [{}])[0].get('message',{}) if isinstance(raw,dict) else {}
def sig(msg,usage):
    return digest([msg.get('content'),msg.get('reasoning_content') or msg.get('reasoning'),msg.get('tool_calls'),usage])
def canon_usage(u):
    if not isinstance(u,dict):return None
    return [u.get('prompt_tokens',u.get('input_tokens')),u.get('completion_tokens',u.get('output_tokens')),u.get('total_tokens')]
def basic_sig(msg,u):return digest([msg.get('content'),canon_usage(u)])

class WireIndex:
    def __init__(self,base,task):
        self.by_signature=defaultdict(list);self.basic=defaultdict(list)
        for p in (base/'runtime/raw_api').glob('*.json.gz'):
            r=read(p)
            if r.get('benchmark')=='canary' or r.get('status')!=200:continue
            msg=r.get('answer') or {};u=r.get('usage');req=r.get('effective_request')
            if not isinstance(req,dict):continue
            row={'request':req,'usage':u,'finish_reason':r.get('finish_reason'),
                 'requested':r.get('request'), 'message':msg}
            self.by_signature[sig(msg,u)].append(row)
            self.basic[basic_sig(msg,u)].append(row)
    def match(self,raw,request=None):
        msg=message(raw);u=raw.get('usage')
        found=self.by_signature.get(sig(msg,u),[]) or self.basic.get(basic_sig(msg,u),[])
        if request and len(found)>1:
            exact=[r for r in found if r['requested'].get('messages')==request.get('messages')]
            if exact:found=exact
        if not found:return None
        # A reused answer can have repeated identical logs; ambiguous distinct inputs stay unknown.
        if len({digest(r['request']) for r in found})>1:return None
        return found[-1]

def native_meta(row,index=None,legacy=False):
    raw=row.get('raw') or row.get('response') or {}
    if not isinstance(raw,dict):raw={}
    req=row.get('identity',{}).get('request') or row.get('request')
    wire=index.match(raw,req) if index and raw.get('choices') else None
    actual=wire['request'] if wire else req
    msg=message(raw)
    usage=raw.get('usage') or row.get('usage') or row.get('token_usage_details')
    if usage is None and 'total_tokens' in row:
        usage={k:row[k] for k in ('prompt_tokens','completion_tokens','total_tokens','reasoning_tokens') if k in row}
    if usage is None and 'total_prompt_tokens' in row:
        usage={'prompt_tokens':row['total_prompt_tokens'],'completion_tokens':row['total_completion_tokens'],
               'total_tokens':row['total_prompt_tokens']+row['total_completion_tokens']}
    final=msg.get('content')
    if final is None:
        for key in ('final','content','assistant_response','response'):
            if isinstance(row.get(key),str):final=row[key];break
    out={'final':final,'reasoning':msg.get('reasoning_content') or msg.get('reasoning'),
         'usage':usage,'parameters':params(actual) if actual else None,
         'parameter_source':'effective_request' if wire else 'recorded_request' if legacy else 'native_request_before_proxy' if actual else None,
         'messages':actual.get('messages') if actual else None,
         'tools':actual.get('tools') if actual else None,
         'finish_reason':(raw.get('choices') or [{}])[0].get('finish_reason') or row.get('finish_reason'),
         'error':row.get('error'),'context_exhausted':row.get('model_context_exhausted',False)}
    for key in ('turns','api_trace','conversation','conversation_generated','tool_outputs','tool_call_counts','total_cost'):
        if key in row:out[key]=row[key]
    if 'messages' in row and out['messages'] is None:out['trajectory']=row['messages']
    return out

def collect(spec,outdir):
    root=Path(spec['root']);task=spec['task'];source_task=spec.get('source_task',task)
    if source_task=='capitu_conversations':source_task='capitu'
    mf=root/'run_manifest.json';manifest=read(mf) if mf.exists() else {}
    base=Path(spec.get('generation_root') or manifest.get('generation_source') or manifest.get('historical_generation_location') or root)
    name=f"{spec['model_id']}--{spec['mode']}--{task}{spec.get('part','')}"
    target=outdir/(name+'.jsonl.gz')
    if target.exists():return {'name':name,'cached':True}
    legacy=bool(spec.get('legacy_scoring'))
    if task in REPLAY:
        if legacy:
            prov=read(root/'provenance.json');base=Path(prov['historical_generation_location'])
        else:base=base/'runtime'
        files=list((base/'responses'/task).glob('*/*.json.gz'))
        rows=((str(r['id']),r) for p in files for r in [read(p)])
        wire=None
    else:
        folder=base/'results'/source_task
        if not folder.exists() and base.name==source_task:folder=base
        scorefile=root/'results'/source_task/'scored_rows.json'
        if not scorefile.exists():scorefile=root/'scored_rows.json'
        scores=read(scorefile) if scorefile.exists() else []
        byhash={}
        for s in scores:
            if 'key' in s and isinstance(s['key'],list):qid=':'.join(map(str,s['key']));byhash[digest(s['key'])]=qid
            else:
                qid=s.get('id',s.get('question_id',s.get('uid',s.get('key'))))
                if qid is not None:byhash[hashlib.sha256(str(qid).encode()).hexdigest()]=str(qid)
        jobs=folder/'frozen_jobs.json'
        if jobs.exists():
            byhash.update({digest([j['dataset'],j['question']['id']]):j['dataset']+':'+str(j['question']['id']) for j in read(jobs)})
        def key(r,p):
            if p.stem in byhash:return byhash[p.stem]
            return str(r.get('identity',{}).get('case',r.get('conversation_hash',r.get('query_id',r.get('key',r.get('id',p.stem))))))
        files=list((folder/'responses').glob('*.json'))
        rows=((key(r,p),r) for p in files for r in [read(p)])
        wire=WireIndex(base,task)
    n=matched=0
    with gzip.open(target.with_suffix('.partial'),'wt',compresslevel=3) as out:
        for qid,row in rows:
            meta=native_meta(row,wire,legacy=task in REPLAY)
            turn=row.get('identity',{}).get('turn',0)
            out.write(json.dumps({'kind':'generation','case_id':qid,'turn':turn,**meta},ensure_ascii=False,separators=(',',':'))+'\n')
            n+=1;matched+=meta['parameter_source'] in ('effective_request','recorded_request')
        # Selected judgment caches; no attempts or superseded recovery history.
        judgefolder=root/'results'/source_task/'judgments'
        if not judgefolder.exists() and root.name==source_task:judgefolder=root/'judgments'
        for p in judgefolder.glob('*.json'):
            j=read(p);qid=j.get('identity',{}).get('case',j.get('query_id',j.get('conversation_hash',j.get('id'))))
            if qid is None:continue
            out.write(json.dumps({'kind':'judgment','case_id':str(qid),'record':j},ensure_ascii=False,separators=(',',':'))+'\n')
        if task=='prosa_pt':
            sp=root/'results/prosa_pt/scored_rows.json'
            for s in read(sp):
                e=s.get('entry',s)
                if not e:continue
                qid=str(e.get('conversation_hash',s.get('id')))
                attempt=e.get('judge_attempt')
                jp=base/'results/prosa_pt/judge_raw'/qid/(str(attempt)+'.json')
                if jp.exists():out.write(json.dumps({'kind':'judge_raw','case_id':qid,'record':read(jp)},ensure_ascii=False,separators=(',',':'))+'\n')
    target.with_suffix('.partial').rename(target)
    return {'name':name,'generations':n,'applied_parameters':matched,'bytes':target.stat().st_size,'source':str(base)}
