from s5_nano.runtime_config import POLICY, THINKING, WORKERS, MAX_TOKENS, PROFILE
"""Resumable cases using pinned native prompts, agents, graders and scoring."""

import ast,concurrent.futures,fcntl,hashlib,importlib.util,json,os,sys,time,traceback,types

from pathlib import Path

from statistics import mean

from s5_nano.auditing import OpenAI

R=Path(__file__).resolve().parent

TASK=sys.argv[1]

MODEL=os.environ['S5_NANO_MODEL']

BASE=os.environ['S5_NANO_PROXY_URL']+'/'+TASK+'/v1'

OUT=Path(os.environ['S5_NANO_RESULT_DIR'])/TASK

LABELS={'enade_qa':'ENADE-QA','enem_vl':'Enem-VL · texto','bluex_v2':'BLUEX v2 · texto',}

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)

def native(name,path,definitions=False,hoist=()):
    sys.path.insert(0,str(path.parent))
    if not definitions:
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
    tree=ast.parse(path.read_text());body=[]
    for node in tree.body:
        if isinstance(node,(ast.Import,ast.ImportFrom,ast.ClassDef,ast.FunctionDef)):
            body.append(node)
        elif isinstance(node,ast.Assign):
            try:ast.literal_eval(node.value);body.append(node)
            except (ValueError,TypeError):pass
    if hoist:
        main=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='main')
        body.extend(x for x in main.body if isinstance(x,ast.FunctionDef) and x.name in hoist)
    module=types.ModuleType(name);module.__file__=str(path);sys.modules[name]=module
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),module.__dict__)
    return module

def candidate():return OpenAI(base_url=BASE,api_key=os.environ.get('S5_NANO_MODEL_API_KEY',''),timeout=21600,max_retries=2)

def saved(kind,key,fn):
    path=OUT/kind/(hashlib.sha256(str(key).encode()).hexdigest()+'.json')
    if path.exists():return json.loads(path.read_text())
    value=fn();save(path,value);return value

def parallel(items,fn,workers=WORKERS):
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(fn,item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            save(OUT/'progress.json',dict(time=time.time(),completed=len(results),expected=len(items)))
    return results

def complete(score,n,details):
    checked=0
    with (R/'effective_requests_secondary.jsonl').open() as f:
        for line in f:
            row=json.loads(line)
            if row.get('status')=='forwarding' and row.get('benchmark')==TASK:
                policy=row['applied'];assert policy['enable_thinking'] is THINKING and policy['max_tokens'] == MAX_TOKENS
                assert all(policy[k]==v for k,v in POLICY.items())
                checked+=1
    assert checked>0
    result=dict(status='FINAL',score=score,n=n,source={'protocol':'s5-nano/public-exams','revision_manifest':json.loads((R/'manifest.json').read_text())['manifest_sha256']},**details)
    proof=dict(passed=True,time=time.time(),metric=result,items_sha256=json.loads((R/'manifest.json').read_text())['manifest_sha256'],
       all_requests_checked=True,final_answers_only=True,lumi_reference=None,label=LABELS[TASK],thinking=THINKING,
       comparison_note='Additional benchmark requested separately; no published Lumi reference for this metric.')
    save(OUT/'verified.json',proof)

def run_mc():
    path=R/'sources/maritaca-utils/benchmarks'/f'{TASK}_bench/run_eval.py'
    module=native('native_mc',path)
    questions=module.load_questions();expected={'enade_qa':716,'enem_vl':1988}[TASK]
    assert len(questions)==expected
    client=candidate()
    def one(q):
        def generate():
            response=client.chat.completions.create(model=MODEL,messages=module.build_messages(q),temperature=1)
            message=response.choices[0].message
            return dict(id=q['id'],content=message.content or '',raw=response.model_dump(mode='json'))
        row=saved('responses',q['id'],generate)
        text=row['content']
        prediction=module.extract_answer(text,'ABCDE'[:len(q['options'])]) if TASK=='enade_qa' else module.extract_answer(text)
        gold=q['answer'] if TASK=='enade_qa' else q['resposta']
        return dict(id=q['id'],prediction=prediction,gold=gold,correct=prediction==gold,unknown=prediction is None)
    rows=parallel(questions,one);assert len({str(x['id']) for x in rows})==expected
    save(OUT/'scored_rows.json',rows);correct=sum(x['correct'] for x in rows)
    complete(100*correct/expected,expected,dict(correct=correct,unknown_rate=mean(x['unknown'] for x in rows),metric_name='accuracy_percent',
        protocol='Pinned native prompts/extractors; requested sampler; first valid generation; score final answer only, no reasoning fallback'))

def run_bluex():
    path=R/'sources/maritaca-utils/benchmarks/bluex_v2_bench/run_eval.py'
    module=native('native_bluex',path)
    # Hoist the unchanged native judge function so each case can be saved immediately.
    tree=ast.parse(path.read_text());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    judge=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='judge')
    exec(compile(ast.Module(body=[judge],type_ignores=[]),str(path),'exec'),module.__dict__)
    module.args=types.SimpleNamespace(model_name=MODEL)
    module.judge_client=OpenAI(base_url=module.JUDGE_API_BASE,api_key=os.environ['MARITACA_API_KEY'],timeout=1800,max_retries=2)
    questions=module.load_questions();assert len(questions)==173 and sum(len(q['subquestions']) for q in questions)==395
    client=candidate()
    def question(q):
        lines=[];results=[]
        for sub in q['subquestions']:
            prompt=module.build_inference_prompt(q['question_text'],'\n\n'.join(lines),sub['label'],sub['text'])
            def generate():
                from s5_nano.bluex_context import generate as generate_with_context_policy
                return generate_with_context_policy(client,MODEL,q,sub,prompt,PROFILE['context_length'])
            row=saved('responses',sub['id'],generate)
            lines.extend([f"Item {sub['label']}: {sub['text']}",f"Resposta dada para o item {sub['label']}: {row['response'] or '(nao disponivel)'}"])
            result=saved('judgments',sub['id'],lambda:module.judge(row));results.append(result)
        return results
    rows=[x for group in parallel(questions,question) for x in group]
    assert len(rows)==395 and len({x['id'] for x in rows})==395
    errors=sum(bool(x['judge_error']) for x in rows)
    assert errors/395<=module.MAX_JUDGE_ERROR_RATE,'Native judge error gate failed'
    for row in rows:
        checks=row['criteria_checks']
        if checks:assert abs(row['score']-10*sum(x['is_met'] for x in checks)/len(checks))<1e-10
    save(OUT/'scored_rows.json',rows)
    complete(10*mean(x['score'] for x in rows),395,dict(native_score=mean(x['score'] for x in rows),native_scale='0–10',metric_name='rubric_score_percent',
        judge='sabia-4',judge_errors=errors,generation_errors=sum(bool(x['generation_error']) for x in rows),questions=173))

def main():
    os.umask(0o077);OUT.mkdir(parents=True,exist_ok=True)
    assert TASK in LABELS
    if TASK=='bluex_v2' and '--preflight' not in sys.argv:assert os.environ.get('MARITACA_API_KEY'),'Set MARITACA_API_KEY in the environment'
    if '--preflight' in sys.argv:
        if TASK in ['enade_qa','enem_vl','bluex_v2']:
            module=native('native_preflight',R/'sources/maritaca-utils/benchmarks'/f'{TASK}_bench/run_eval.py')
            count=len(module.load_questions());assert count=={'enade_qa':716,'enem_vl':1988,'bluex_v2':173}[TASK]
        save(OUT/'preflight.json',dict(passed=True,time=time.time(),count=count));return
    with (OUT/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (OUT/'verified.json').exists():return
        save(OUT/'started.json',dict(time=time.time(),pid=os.getpid(),thinking=THINKING))
        {'enade_qa':run_mc,'enem_vl':run_mc,'bluex_v2':run_bluex}[TASK]()

if __name__=='__main__':
    try:main()
    except BaseException as exc:
        save(OUT/'failure.json',dict(time=time.time(),type=type(exc).__name__,detail=str(exc)[:1000],traceback=traceback.format_exc()));raise
