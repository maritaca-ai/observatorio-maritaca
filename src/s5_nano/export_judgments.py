"""Read recorded judge HTTP exchanges. Never creates an inference client."""
import argparse,concurrent.futures as cf,gzip,json,os
from pathlib import Path

def read(p):
    with gzip.open(p,'rt') if str(p).endswith('.gz') else open(p) as f:return json.load(f)
def exchanges(spec,outdir):
    root=Path(spec['root']);mf=root/'run_manifest.json';m=read(mf) if mf.exists() else {}
    base=Path(spec.get('generation_root') or m.get('generation_source') or m.get('historical_generation_location') or root)
    folders=list(dict.fromkeys([root,base,*map(Path,spec.get('extra_judge_roots',[]))]))
    name=f"{spec['model_id']}--{spec['mode']}--{spec['task']}{spec.get('part','')}.jsonl.gz"
    target=outdir/name
    if target.exists():return {'name':name,'cached':True}
    n=0
    with gzip.open(target.with_suffix('.partial'),'wt',compresslevel=3) as dest:
        for folder in folders:
            ledger=folder/'runtime/http_attempts.jsonl'
            if not ledger.exists():continue
            for line in ledger.open():
                e=json.loads(line)
                if e.get('phase')!='finished' or e.get('benchmark')=='canary':continue
                model=e.get('model') or ''
                if not any(k in model.lower() for k in ('gpt-','sabia-','claude-')):continue
                rawfolder=folder/'runtime/http_raw'
                rp=rawfolder/(e['attempt_id']+'.request.json.gz')
                sp=rawfolder/(e['attempt_id']+'.response.json.gz')
                if not rp.exists() or not sp.exists():continue
                req=read(rp);res=read(sp)
                out={'status':e.get('status'),'request':req.get('payload'),'response':res.get('payload'),
                     'cost':e.get('cost') or res.get('cost'),'usage':e.get('usage') or res.get('usage')}
                dest.write(json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n');n+=1
    target.with_suffix('.partial').rename(target)
    return {'name':name,'exchanges':n,'bytes':target.stat().st_size}
