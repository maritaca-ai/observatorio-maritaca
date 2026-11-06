from s5_nano.runtime_config import POLICY, THINKING, WORKERS, MAX_TOKENS, PROFILE
"""Durable public Portuguese evaluations on the configured model endpoint."""
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

from s5_nano.auditing import OpenAI
import pt_native

R = Path(__file__).resolve().parent
TASK = sys.argv[1] if len(sys.argv)>1 else None
LABELS = {'math_pt_br_mc':'MATH-PT · PT-BR múltipla escolha', 'broverbs':'BRoverbs · média das duas modalidades',
          'assin_rte':'ASSIN 2 RTE · macro F1 · PoETa 300'}
OUT = Path(os.environ['S5_NANO_RESULT_DIR'])/str(TASK)
MODEL = os.environ['S5_NANO_MODEL']


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    tmp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def verify_inputs():
    manifest=json.loads((R/'manifest.json').read_text())
    body={k:v for k,v in manifest.items() if k!='manifest_sha256'}
    assert hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()==manifest['manifest_sha256']
    assert TASK in manifest['tasks'] and manifest['paid_judge'] is False
    for name,checksum in manifest['files'].items():
        assert hashlib.sha256((R/name).read_bytes()).hexdigest()==checksum, name
    cases=json.loads((R/'cases'/(TASK+'.json')).read_text())
    assert len(cases)==manifest['protocols'][TASK]['n'] and len({x['id'] for x in cases})==len(cases)
    return manifest,cases


def response_for(row,client,manifest):
    path=OUT/'responses'/(digest(row['id'])+'.json')
    expected=digest(dict(messages=row['messages'],model=MODEL,preset=POLICY,thinking=THINKING,max_tokens=MAX_TOKENS))
    if path.exists():
        value=json.loads(path.read_text())
        assert value['request_sha256']==expected and value['manifest_sha256']==manifest['manifest_sha256']
        return value
    response=client.chat.completions.create(model=MODEL,messages=row['messages'],temperature=1.,top_p=.95,
        max_tokens=MAX_TOKENS,extra_body=dict(top_k=20,min_p=0.,presence_penalty=1.5,repetition_penalty=1.,
            chat_template_kwargs={'enable_thinking':THINKING}))
    choice=response.choices[0]
    value=dict(id=row['id'],content=choice.message.content or '',finish_reason=choice.finish_reason,
        request_sha256=expected,manifest_sha256=manifest['manifest_sha256'],raw=response.model_dump(mode='json'))
    save(path,value)
    return value


def independently_verify(task,rows,metric):
    n=len(rows)
    if task in ('math_pt_br_mc','broverbs'):
        assert abs(metric['score']-100*sum(x['correct'] for x in rows)/n)<1e-10
    else:
        pairs=[x['f1'] for x in rows]
        scores=[]
        for label in sorted({gold for pred,gold in pairs}):
            tp=sum(p==label and g==label for p,g in pairs)
            fp=sum(p==label and g!=label for p,g in pairs)
            fn=sum(p!=label and g==label for p,g in pairs)
            scores.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.)
        assert abs(metric['score']-100*sum(scores)/len(scores))<1e-10
        assert abs(metric['accuracy']-100*sum(p==g for p,g in pairs)/n)<1e-10


def main():
    assert TASK in LABELS
    os.umask(0o077)
    OUT.mkdir(parents=True,exist_ok=True)
    manifest,cases=verify_inputs()
    assert json.loads((R/'run_manifest.json').read_text())['profile']['enable_thinking'] is THINKING
    native=pt_native.load()
    if '--preflight' in sys.argv:
        # Exercise native scorers over every public test row with its golden final answer.
        scored=[]
        for row in cases:
            doc=row['doc']
            gold=({'math_pt_br_mc':lambda:'\\boxed{'+doc['answer']+'}',
                   'broverbs':lambda:doc['gold'],
                   'assin_rte':lambda:['Não','Sim'][doc['entailment_judgment']]}[TASK])()
            scored.append(pt_native.score_case(TASK,row,gold,native))
        metric=pt_native.aggregate(TASK,scored,native)
        assert abs(metric['score']-100)<1e-10
        independently_verify(TASK,scored,metric)
        save(OUT/'preflight.json',dict(passed=True,time=time.time(),n=len(cases),
            public_sources=True,all_golden_answers_score_100=True,paid_judge=False))
        return
    with (OUT/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (OUT/'verified.json').exists():return
        save(OUT/'started.json',dict(time=time.time(),pid=os.getpid(),thinking=THINKING,paid_judge=False,n=len(cases)))
        client=OpenAI(base_url=os.environ['S5_NANO_PROXY_URL']+'/'+TASK+'/v1',api_key=os.environ.get('S5_NANO_MODEL_API_KEY',''),timeout=21600,max_retries=2)
        def one(row):
            value=response_for(row,client,manifest)
            result=pt_native.score_case(TASK,row,value['content'],native)
            return dict(id=row['id'],**result,empty_final=not value['content'].strip(),truncated=value['finish_reason']=='length')
        rows=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for future in concurrent.futures.as_completed([pool.submit(one,row) for row in cases]):
                rows.append(future.result())
                save(OUT/'progress.json',dict(time=time.time(),completed=len(rows),expected=len(cases)))
        assert {x['id'] for x in rows}=={x['id'] for x in cases}
        metric=pt_native.aggregate(TASK,rows,native)
        independently_verify(TASK,rows,metric)
        checked=0
        for line in (R/'effective_requests_secondary.jsonl').read_text().splitlines():
            item=json.loads(line)
            if item.get('status')=='forwarding' and item.get('benchmark')==TASK:
                assert all(item['applied'][k]==v for k,v in POLICY.items())
                assert item['applied']['enable_thinking'] is THINKING and item['applied']['max_tokens'] == MAX_TOKENS
                assert item['applied']['stop'] == PROFILE.get('generation_stop') and item['native_budget_fields'].get('reasoning_effort') is None
                checked+=1
        assert checked>=len(cases)
        metric.update(status='FINAL',n=len(rows),judge=None,paid_judge=False,
            empty_final=sum(x['empty_final'] for x in rows),truncated=sum(x['truncated'] for x in rows),
            protocol=manifest['protocols'][TASK],sources=manifest['sources'],audited_requests=checked,
            public_benchmark_sources=True)
        save(OUT/'scored_rows.json',rows)
        save(OUT/'verified.json',dict(passed=True,time=time.time(),metric=metric,
            items_sha256=manifest['manifest_sha256'],all_requests_checked=True,final_answers_only=True,
            independent_aggregation_checked=True,label=LABELS[TASK],thinking=THINKING,lumi_reference=None,
            comparison_note='Public Portuguese benchmark; explicit model profile overrides greedy defaults.'))


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        save(OUT/'failure.json',dict(time=time.time(),error_type=type(exc).__name__,detail=str(exc)[:1000],traceback=traceback.format_exc()))
        raise
