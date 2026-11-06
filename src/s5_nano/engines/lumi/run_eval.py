from s5_nano.runtime_config import THINKING, WORKERS, MAX_TOKENS, PROFILE
"""Resumable local inference. Never replace a valid response or expose raw data."""
import asyncio
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import traceback
import aiohttp
from bootstrap import POLICY,RUN,save

R=Path(__file__).resolve().parent

def result_path(item):
    digest=hashlib.sha256(item['id'].encode()).hexdigest()
    return R/'responses'/item['task']/digest[:2]/(digest+'.json.gz')

def body_for(item):
    body=dict(model=RUN,messages=[{'role':'user','content':item['prompt']}],
              max_tokens=MAX_TOKENS,chat_template_kwargs={'enable_thinking':THINKING},**POLICY)
    if item.get('stop'):body['stop']=item['stop']
    return body

def load_existing(item):
    p=result_path(item)
    if not p.exists():return None
    with gzip.open(p,'rt') as f:row=json.load(f)
    assert row['id']==item['id'] and row['task']==item['task']
    assert row['prompt_sha256']==hashlib.sha256(item['prompt'].encode()).hexdigest()
    assert row['request']==body_for(item),'Existing response used another protocol'
    assert row['response']['model']==RUN
    return row

async def main():
    os.umask(0o077)
    lock=(R/'generation.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert json.loads((R/'canary_verified.json').read_text())['passed']
    manifest=json.loads((R/'manifest.json').read_text())
    data=R/'data/items.jsonl'
    assert hashlib.sha256(data.read_bytes()).hexdigest()==manifest['items_sha256']
    with data.open() as f:items=[json.loads(l) for l in f]
    counts={k:0 for k in manifest['counts']};failed=[];started=time.time();queue=asyncio.Queue()
    tucano=(PROFILE or {}).get('transport_policy')=='tucano_raw_completion_v1'
    stop_dispatch=asyncio.Event()
    totals=dict(completion_tokens=0,prompt_tokens=0,empty_finals=0,length_finishes=0,with_reasoning=0)
    def record(item,row):
        counts[item['task']]+=1
        response=row['response'];message=response['choices'][0]['message'];usage=response.get('usage',{})
        totals['completion_tokens']+=usage.get('completion_tokens',0)
        totals['prompt_tokens']+=usage.get('prompt_tokens',0)
        totals['empty_finals']+=not bool((message.get('content') or '').strip())
        totals['with_reasoning']+=bool(message.get('reasoning') or message.get('reasoning_content'))
        totals['length_finishes']+=response['choices'][0]['finish_reason']=='length'
    for item in items:
        old=load_existing(item)
        if old:record(item,old)
        else:queue.put_nowait(item)
    def progress(stage):
        save('progress.json',dict(stage=stage,time=time.time(),started=started,completed=counts,
              expected=manifest['counts'],total_completed=sum(counts.values()),total=manifest['total'],
              pending=manifest['total']-sum(counts.values()),failures=len(failed),usage=totals,
              checkpoint=None,thinking=THINKING,max_tokens=MAX_TOKENS,concurrency=WORKERS))
    async def observer():
        while True:progress('GENERATING');await asyncio.sleep(10)
    async def worker(session):
        while True:
            if stop_dispatch.is_set():return
            try:item=queue.get_nowait()
            except asyncio.QueueEmpty:return
            body=body_for(item);p=result_path(item);p.parent.mkdir(parents=True,exist_ok=True)
            errors=[]
            attempts=1 if tucano else 3
            for attempt in range(attempts):
                try:
                    t=time.time()
                    async with session.post(os.environ['S5_NANO_PROXY_URL']+'/'+item['task']+'/v1/chat/completions',json=body) as response:
                        raw=await response.read()
                        if response.status!=200:raise RuntimeError(f'HTTP {response.status}: {raw[:1000]!r}')
                        data=json.loads(raw)
                    assert data['model']==RUN
                    assert len(data['choices'])==1 and data['choices'][0]['finish_reason'] in ('stop','length')
                    assert data['choices'][0]['message'].get('role')=='assistant'
                    row=dict(task=item['task'],id=item['id'],prompt_sha256=hashlib.sha256(item['prompt'].encode()).hexdigest(),
                         request=body,response=data,started=t,finished=time.time(),transport_attempt=attempt+1,prior_transport_errors=errors)
                    assert not p.exists(),'Concurrent duplicate generation'
                    tmp=p.with_suffix('.tmp')
                    with gzip.open(tmp,'wt',encoding='utf-8') as f:json.dump(row,f,ensure_ascii=False)
                    tmp.replace(p);record(item,row);break
                except Exception as e:
                    errors.append(dict(time=time.time(),type=type(e).__name__,detail=str(e)[:1500]))
                    if tucano:stop_dispatch.set()
                    if attempt<attempts-1:await asyncio.sleep(2**attempt)
            else:
                failed.append(dict(task=item['task'],id=item['id'],errors=errors))
                save('transport_failures.json',failed)
            queue.task_done()
    timeout=aiohttp.ClientTimeout(total=None,connect=60,sock_read=14400)
    async with aiohttp.ClientSession(timeout=timeout,connector=aiohttp.TCPConnector(limit=WORKERS)) as session:
        observer_task=asyncio.create_task(observer())
        await asyncio.gather(*(worker(session) for _ in range(WORKERS)))
        observer_task.cancel()
    progress('GENERATION_COMPLETE' if not failed else 'INCOMPLETE_TRANSPORT_FAILURES')
    assert not failed,'Transport failures retained for missing-only recovery'
    assert counts==manifest['counts']
    save('generation_verified.json',dict(time=time.time(),counts=counts,usage=totals,items_sha256=manifest['items_sha256'],
         all_responses_preserved=True,empty_answers_included=True,protocol=POLICY,max_tokens=MAX_TOKENS,thinking=THINKING))
    import score_results
    score_results.main()

if __name__=='__main__':
    try:asyncio.run(main())
    except BaseException as e:
        save('runner_failure.json',dict(time=time.time(),type=type(e).__name__,detail=str(e),traceback=traceback.format_exc()))
        raise
