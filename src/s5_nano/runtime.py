"""Materialize isolated, resumable runs from pinned public inputs."""
import fcntl,hashlib,json,os,shutil,socket,subprocess,sys,time,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from contextvars import ContextVar
from .prepare import REPO,prepare,save,sha
from .runtime_config import read_profile
CANARY_AUDIT_ROOT=ContextVar('canary_audit_root',default=None)

def freeze(path,identity):
 path=Path(path)
 if path.exists():
  if json.loads(path.read_text())!=identity:raise ValueError('Run identity changed; use a new output directory')
 else:save(path,identity)

def nltk_data(cache):
 # Multiple model lanes may initialize the same pinned linguistic resources.
 # Hold one cache-level lock across download and extraction, not just rename.
 cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
 with (cache/'nltk-prepare.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  return _nltk_data_locked(cache)

def _nltk_data_locked(cache):
 import zipfile
 from .prepare import fetch
 root=Path(cache)/'nltk';lock=json.loads((REPO/'locks/nltk.json').read_text())
 for name,spec in lock['files'].items():
  archive=fetch(spec['url'],Path(cache)/'nltk-archives'/name,spec['sha256'])
  destination=root/Path(name).parent
  if (destination/Path(name).stem).exists():continue
  destination.mkdir(parents=True,exist_ok=True)
  with zipfile.ZipFile(archive) as z:
   for member in z.namelist():
    if not (destination/member).resolve().is_relative_to(destination.resolve()):raise ValueError('Unsafe NLTK archive path')
   z.extractall(destination)
 return root

def select_tasks(spec,tasks=None):
 if tasks is None:return spec
 if spec['family']!='lumi' or not tasks or len(set(tasks))!=len(tasks) or not set(tasks)<=set(spec['tasks']):
  raise ValueError('Select unique complete tasks from the requested Lumi-family benchmark')
 selected=[(t,n) for t,n in zip(spec['tasks'],spec['expected_counts'],strict=True) if t in tasks]
 return dict(spec,tasks=[t for t,n in selected],expected_counts=[n for t,n in selected])

def install(benchmark,cache,output,profile,model,api_base,marca_snapshot=None,tasks=None):
 spec=select_tasks(json.loads((REPO/'benchmarks/catalog.json').read_text())[benchmark],tasks)
 if spec['family']=='remaining':
  from .remaining_inputs import prepare as prepare_remaining
  inputs=prepare_remaining(benchmark,cache)
 else:inputs=prepare(spec['family'],cache)
 root=Path(output)/benchmark;runtime=root/'runtime';runtime.mkdir(parents=True,exist_ok=True)
 files={str(p.relative_to(REPO)):sha(p) for folder in ['src/s5_nano','benchmarks','locks'] for p in (REPO/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
 identity=dict(schema_version=1,benchmark=spec,model=model,profile=profile,api_base=api_base,input_receipt_sha256=sha(inputs/'prepared.json'),code=files,dependencies_sha256=sha(REPO/'requirements.lock'),scorer_dependencies_sha256=sha(REPO/'requirements-scorer.lock'))
 identity['marca_snapshot_sha256']=sha(marca_snapshot) if marca_snapshot and benchmark=='marca' else None
 if spec['family']=='plus':identity['plus_dependencies_sha256']=sha(REPO/'requirements-plus.lock')
 if spec['family']=='remaining':identity['remaining_dependencies_sha256']=sha(REPO/'requirements-remaining.lock')
 if benchmark=='harmbench':identity['harm_scorer_dependencies_sha256']=sha(REPO/'requirements-harm-scorer.lock')
 freeze(root/'run_manifest.json',identity);freeze(runtime/'run_manifest.json',identity)
 if marca_snapshot and benchmark=='marca':
  destination=root/'results/marca_public/frozen_jobs.json';destination.parent.mkdir(parents=True,exist_ok=True)
  if destination.exists():assert sha(destination)==sha(marca_snapshot),'Frozen MARCA questions/checklists differ'
  else:shutil.copyfile(marca_snapshot,destination)
 freeze(root/'profile.json',profile)
 engine=REPO/'src/s5_nano/engines'/spec['family']
 for p in engine.glob('*.py'):
  target=runtime/p.name
  if target.exists():assert sha(target)==sha(p),'Run code changed'
  else:shutil.copyfile(p,target)
 if spec['family']=='pt':shutil.copyfile(REPO/'src/s5_nano/engines/pt_native.py',runtime/'pt_native.py')
 for p in inputs.iterdir():
  if p.name in ['manifest.json','prepared.json','prepare.lock','authorization.json','data'] or p.name.startswith('.'):continue
  target=runtime/p.name
  if not target.exists():target.symlink_to(p.resolve(),target_is_directory=p.is_dir())
 if spec['family']=='lumi':
  data=runtime/'data';data.mkdir(exist_ok=True)
  tasks=spec['tasks'];manifest=json.loads((inputs/'manifest.json').read_text())
  manifest['evaluation_protocol']=select_tasks(json.loads((REPO/spec['directory']/'protocol.json').read_text()),tasks)
  manifest['counts']={t:manifest['counts'][t] for t in tasks};manifest['datasets']={t:manifest['datasets'][t] for t in tasks}
  manifest['total']=sum(manifest['counts'].values())
  for t in tasks:
   if not (data/t).exists():(data/t).symlink_to(inputs/'data'/t,target_is_directory=True)
  selected=b''.join(line for line in (inputs/'data/items.jsonl').read_bytes().splitlines(keepends=True) if json.loads(line)['task'] in tasks)
  p=data/'items.jsonl'
  if p.exists():assert p.read_bytes()==selected
  else:p.write_bytes(selected)
  manifest['items_sha256']=sha(p);save(runtime/'manifest.json',manifest)
 else:
  if (inputs/'data').exists() and not (runtime/'data').exists():(runtime/'data').symlink_to(inputs/'data',target_is_directory=True)
  shutil.copyfile(inputs/'manifest.json',runtime/'manifest.json')
 return spec,root,runtime

def post(base,path,payload):
 from .model_identity import expected_model,verify_response_model
 audit_root=CANARY_AUDIT_ROOT.get()
 if audit_root is None:raise ValueError('Direct canary requires an explicit audit directory')
 model=expected_model(payload,payload.get('extra_body'))
 req=urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=1800) as response:raw=json.load(response)
 verify_response_model(raw,model,audit_root,source='completed_direct_canary',request=payload)
 return raw

def generation_prompt_ids(response):
 """Read actual server evidence from either supported OpenAI response shape."""
 top=response.get('prompt_token_ids')
 choices=response.get('choices') or []
 per_choice=choices[0].get('prompt_token_ids') if len(choices)==1 else None
 if top is not None and per_choice is not None and top!=per_choice:
  raise ValueError('Conflicting generation prompt token IDs')
 tokens=top if top is not None else per_choice
 if not (isinstance(tokens,list) and tokens and all(type(t) is int for t in tokens)):
  raise ValueError('Server must return the actual generation prompt token IDs')
 return tokens

def claim_run(root, runtime):
 """A rerun must not repeat a successful or uncertain canary implicitly."""
 from .remaining_core import claim_dispatch
 for name in ['candidate_attempts.jsonl','http_attempts.jsonl']:
  ledger=runtime/name
  if ledger.exists() and ledger.stat().st_size:
   raise RuntimeError('Existing run attempts require audited continuation; canary will not be repeated')
 if (runtime/'canary_verified.json').exists() or (root/'results_verified.json').exists():
  raise RuntimeError('Existing run results require audited continuation; canary will not be repeated')
 claim_dispatch(root,'run',sha(root/'run_manifest.json'))

def canary(runtime,base,api_base,model,profile,tokenizer_path,template_path):
 """Prove mode, enforced sampler, tool history and exact server tokenization."""
 from transformers import AutoTokenizer
 expected=profile['enable_thinking']
 tokenizer=AutoTokenizer.from_pretrained(tokenizer_path,local_files_only=True)
 tokenizer.chat_template=Path(template_path).read_text()
 assert sha(template_path)==profile['chat_template_sha256'],'Chat template differs from the profile'
 tools=[dict(type='function',function=dict(name='saldo',description='Consulta saldo fictício.',parameters=dict(type='object',properties={'conta':{'type':'integer'}},required=['conta'])))]
 messages=[dict(role='user',content='Use a ferramenta saldo para consultar o saldo fictício da conta 17. Depois diga o valor obtido.')]
 first=post(base,'/canary/v1/chat/completions',dict(model=model,messages=messages,tools=tools,temperature=0,max_tokens=1,chat_template_kwargs={'enable_thinking':not expected}))
 answer=first['choices'][0]['message'];reason=answer.get('reasoning') or answer.get('reasoning_content') or ''
 assert answer.get('tool_calls'),'Canary tool call did not match'
 messages.append({k:v for k,v in answer.items() if k in ['role','content','tool_calls']})
 messages.extend(dict(role='tool',tool_call_id=t['id'],content='500 reais') for t in answer['tool_calls'])
 second=post(base,'/canary/v1/chat/completions',dict(model=model,messages=messages,tools=tools,temperature=0,max_tokens=1,chat_template_kwargs={'enable_thinking':not expected},return_token_ids=True,return_prompt_text=True))
 msg=second['choices'][0]['message']
 assert msg.get('content') and second['choices'][0]['finish_reason']=='stop'
 rendered=json.loads(json.dumps(messages))
 if reason:
  if profile.get('history_encoding','qwen_think_tags')=='reasoning_field':rendered[1]['reasoning_content']=reason
  else:rendered[1]['content']='<think>\n'+reason+'\n</think>\n\n'+(rendered[1].get('content') or '')
 template_kwargs=dict(profile.get('chat_template_kwargs',{}),enable_thinking=expected)
 # Inspect the actual generation prompt. The separate /tokenize route may
 # normalize tool schemas differently from chat generation on some backends.
 tokens=generation_prompt_ids(second)
 for m in rendered:
  for call in m.get('tool_calls') or []:
   if isinstance(call['function']['arguments'],str):call['function']['arguments']=json.loads(call['function']['arguments'])
 if profile.get('tool_adapter'):
  from .gaia_transport_adapter import adapt_request
  transport=adapt_request(dict(messages=rendered,tools=tools))
  rendered=transport['messages'];render_tools=transport.get('tools')
 else:render_tools=tools
 prompt=tokenizer.apply_chat_template(rendered,tools=render_tools,tokenize=False,add_generation_prompt=True,**template_kwargs)
 save(runtime/'canary_prompt_diagnostic.json',dict(local_prompt=prompt,server_prompt=second.get('prompt_text'),server_token_ids=tokens,local_token_ids=tokenizer.encode(prompt,add_special_tokens=False)))
 assert tokens==tokenizer.encode(prompt,add_special_tokens=False)
 if second.get('prompt_text') is not None:assert second['prompt_text']==prompt
 assert second['usage']['prompt_tokens']==len(tokens)
 if profile.get('history_encoding','qwen_think_tags')=='qwen_think_tags':assert prompt.endswith('<think>\n') is expected
 if reason:assert reason in prompt
 rows=[json.loads(line) for line in (runtime/'effective_requests_secondary.jsonl').read_text().splitlines()]
 applied=[r['applied'] for r in rows if r.get('status')=='forwarding' and r.get('benchmark')=='canary']
 assert len(applied)>=2
 for a in applied:
  assert a['enable_thinking'] is expected and a['max_tokens']==profile['max_tokens']
  assert all(a[k]==v for k,v in profile['sampling'].items())
 save(runtime/'canary_verified.json',dict(passed=True,time=time.time(),thinking_received=expected,actual_prompt_tokens_match=True,prompt_evidence='generation_response_prompt_token_ids',preset=profile['sampling'],max_tokens=profile['max_tokens'],template_sha256=sha(template_path),chat_template_kwargs=template_kwargs,rendered_prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),first_reasoning_chars=len(reason),second_reasoning_chars=len(msg.get('reasoning') or msg.get('reasoning_content') or '')))

def execute(benchmark,args,preflight=False):
 profile=read_profile(args.profile);url=urlsplit(args.api_base)
 if profile.get('model') and profile['model']!=args.model:raise ValueError('Model does not match the explicitly selected profile')
 if url.scheme not in ['http','https'] or not url.hostname or url.username or url.password or url.query or url.fragment:raise ValueError('Use an API base without credentials or query strings')
 spec,root,runtime=install(benchmark,args.cache,args.output,profile,args.model,args.api_base,getattr(args,'marca_snapshot',None),getattr(args,'task',None))
 lock=(root/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if (root/'results_verified.json').exists():
  result=json.loads((root/'results_verified.json').read_text())
  if result.get('status')!='FINAL' or result.get('profile')!=profile:raise ValueError('Stored final result has a different protocol')
  return
 env=dict(os.environ,S5_NANO_PROFILE=str((root/'profile.json').resolve()),S5_NANO_MODEL=args.model,S5_NANO_BENCHMARK=benchmark,S5_NANO_WORKERS=str(args.workers),S5_NANO_API_BASE=args.api_base,S5_NANO_AUDIT_DIR=str(runtime),S5_NANO_RESULT_DIR=str(root/'results'),S5_NANO_SCORER_PYTHON=str(Path(args.cache)/'scorer-venv/bin/python'),S5_NANO_PROXY_URL='http://127.0.0.1:1',WANDB_MODE='disabled',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(REPO/'src'),NLTK_DATA=str(nltk_data(args.cache)))
 if args.tokenizer:env['S5_NANO_TOKENIZER']=str(Path(args.tokenizer).resolve())
 if args.chat_template:env['S5_NANO_CHAT_TEMPLATE']=str(Path(args.chat_template).resolve())
 def worker(task,extra=()):
  argv=[sys.executable,str(runtime/('run_eval.py' if spec['family']=='lumi' else 'worker.py'))]
  if spec['family'] not in ['lumi','capitu']:argv.append(task)
  with (root/(task+('.preflight.log' if preflight else '.log'))).open('ab') as stream:
   proc=subprocess.run(argv+list(extra),cwd=runtime,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
  if proc.returncode:raise RuntimeError('Benchmark failed; preserved logs in '+str(root))
 if preflight:
  if spec['family']=='plus':env.setdefault('OPENAI_API_KEY','unused-local-bm25-preflight')
  if spec['family']=='lumi':
   manifest=json.loads((runtime/'manifest.json').read_text())
   assert list(manifest['counts'].values())==spec['expected_counts']
  else:
   for task in spec['tasks']:worker(task,['--preflight'])
  save(root/'preflight.json',dict(passed=True,model_or_judge_calls=0));return
 if not args.tokenizer or not args.chat_template:raise ValueError('run requires tokenizer and chat template for exact prompt validation')
 claim_run(root,runtime)
 with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
 base='http://127.0.0.1:'+str(port);env.update(S5_NANO_PROXY_URL=base,S5_NANO_PROXY_PORT=str(port))
 with (root/'proxy.log').open('ab') as stream:
  proxy=subprocess.Popen([sys.executable,'-m','s5_nano.proxy'],cwd=runtime,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
 token=CANARY_AUDIT_ROOT.set(runtime)
 try:
  deadline=time.time()+30
  while time.time()<deadline:
   if proxy.poll() is not None:raise RuntimeError('Proxy failed; inspect proxy.log')
   try:
    with socket.create_connection(('127.0.0.1',port),timeout=1):break
   except OSError:time.sleep(.1)
  else:raise TimeoutError('Proxy readiness')
  from .remaining_canary import uses_text_canary
  if uses_text_canary(benchmark,spec['family'],profile):
   from .remaining_canary import canary as run_canary
  elif profile.get('transport_policy')=='tucano_raw_completion_v1' and benchmark in {'marca','lumen','browsecomp_plus'}:
   from .tucano_tool_canary import canary as run_canary
  else:run_canary=canary
  run_canary(runtime,base,args.api_base,args.model,profile,args.tokenizer,args.chat_template)
  if spec['family']=='lumi':
   save(runtime/'scorer_ready.json',dict(ready=True,python=sys.version,nltk_pinned=True));worker(spec['tasks'][0])
   result=json.loads((runtime/'results.json').read_text());proofs={t:json.loads((runtime/'results'/t/'verified.json').read_text()) for t in spec['tasks']}
  else:
   for task in spec['tasks']:worker(task)
   proofs={t:json.loads((root/'results'/t/'verified.json').read_text()) for t in spec['tasks']}
   result=dict(status='FINAL',model=args.model,benchmarks={t:p['metric'] for t,p in proofs.items()})
  assert all(p['passed'] and p['thinking'] is profile['enable_thinking'] and p['metric']['status']=='FINAL' for p in proofs.values())
  result.update(profile=profile,independent_verification=dict(passed=True),time=time.time())
  save(root/'results_verified.json',result)
 finally:
  from .proxy_drain import drain_proxy
  try:drain_proxy(runtime,proxy)
  finally:CANARY_AUDIT_ROOT.reset(token)
