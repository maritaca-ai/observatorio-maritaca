"""Campaign adapter: enforce the requested sampler and retain reasoning history.

The explicit profile controls the output limit for evaluated-model calls.
Public tasks share that profile; native judges retain their own parameters.
Response content remains the final answer; reasoning is recovered only when
rendering a subsequent request. SQLite state and audit are private to this run.
"""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from http.client import HTTPConnection,HTTPSConnection
from urllib.parse import urlsplit
from pathlib import Path
import json,hashlib,sqlite3,threading,time,os,gzip,uuid
from s5_nano.runtime_config import POLICY,THINKING,PROFILE
from s5_nano.history_verification import plain_content, key
from s5_nano.auditing import store as store_http,append as append_http
from s5_nano.message_adaptation import adapt_messages, message_policy, SYSTEM_TO_USER
from s5_nano import gaia_transport_adapter
ROOT=Path(os.environ['S5_NANO_AUDIT_DIR'])
MODEL=os.environ['S5_NANO_MODEL']
UPSTREAM=urlsplit(os.environ['S5_NANO_API_BASE'])
assert UPSTREAM.scheme in ('http','https') and UPSTREAM.hostname and not UPSTREAM.username and not UPSTREAM.password and not UPSTREAM.query and not UPSTREAM.fragment
REPAIR_MODEL=MODEL+'_size_repair_none'
LOCK=threading.Lock()
BUDGET_POLICY="explicit_s5_nano_profile"
ALLOWED_LABELS={'canary','mmlu_pt_high_school','mmlu_pt_undergraduate','global_mmlu_pt','enade_qa','enem_vl','bluex_v2','marca_public','browsecomp_plus','capitu','math_pt_br_mc','broverbs','assin_rte','lumen_pt','prosa_pt'}
GENERATED_HISTORY_TASKS={'browsecomp_plus','capitu','marca_public','lumen_pt'}
ALLOWED_LABELS.update({'magis_bench','oab_bench_full','oab_bench_3941','ifbench','oab_bench','arena_hard_v2','culturalbench','sob',
                       'longbench_v2','harmbench','conduta_bench'})
GENERATED_HISTORY_TASKS.update({'magis_bench','oab_bench_full','oab_bench_3941','oab_bench'})

class HistoryIntegrityError(ValueError):
 """Local evaluation failure; never send an incomplete history to the model."""

def benchmark_label(payload):
 label=payload.get("campaign_benchmark_label")
 if label is not None:
  if label not in ALLOWED_LABELS:raise ValueError("Unknown private dispatch label")
  return label
 return (ROOT/"current_benchmark.txt").read_text().strip() if (ROOT/"current_benchmark.txt").exists() else "canary"


def db():
 c=sqlite3.connect(ROOT/'history_secondary.sqlite',timeout=30)
 c.execute('create table if not exists history (signature text primary key, reasoning text not null)')
 c.execute('create table if not exists tool_history (signature text primary key, reasoning text not null)')
 return c

def tool_signature(message):
 calls=message.get('tool_calls') or []
 ids=[x.get('id') for x in calls]
 if not ids or not all(isinstance(x,str) and x for x in ids):return None
 return hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()

def save_reasoning(messages,answer,conversation_id=None):
 r=answer.get('reasoning_content') or answer.get('reasoning') or ''
 if not isinstance(r,str):raise ValueError('Nontext reasoning response')
 m={k:v for k,v in answer.items() if k in ('role','content','tool_calls')}
 m.setdefault('role','assistant')
 with LOCK,db() as c:
  c.execute('insert or replace into history values (?,?)',(key(messages+[m],conversation_id,strip_thinking_tags=PROFILE.get('history_content_policy')!='literal'),r))
  signature=tool_signature(m)
  if signature:
   row=c.execute('select reasoning from tool_history where signature=?',(signature,)).fetchone()
   if row and row[0]!=r:raise ValueError('Conflicting reasoning for tool call IDs')
   c.execute('insert or ignore into tool_history values (?,?)',(signature,r))
 os.chmod(ROOT/'history_secondary.sqlite',0o600)

def enforce(payload):
 assert POLICY and type(THINKING) is bool, 'Missing explicit profile'
 result=dict(payload); result.update(POLICY)
 if result.get('model') not in (MODEL,REPAIR_MODEL):raise ValueError('Unexpected candidate model')
 if result.get('stream'):raise ValueError('Streaming is not enabled by this evaluation protocol')
 result.pop('reasoning_effort',None)
 extra=result.pop('extra_body',{}) or {}
 for k,v in extra.items():
  if k not in POLICY and k not in ('chat_template_kwargs','enable_thinking','reasoning_effort'): result.setdefault(k,v)
 result.pop('campaign_benchmark_label',None)
 conversation_id=result.pop('campaign_conversation_id',None)
 if conversation_id is not None and (not isinstance(conversation_id,str) or not 1<=len(conversation_id)<=256):
  raise HistoryIntegrityError('Invalid conversation identity')
 if benchmark_label(payload)=='capitu' and conversation_id is None:
  raise HistoryIntegrityError('CAPITU requires an explicit case identity')
 managed=result.pop("campaign_context_managed", False)
 if type(managed) is not bool:raise ValueError("Invalid managed context marker")
 kwargs=dict(extra.get('chat_template_kwargs') or {});kwargs.update(result.get('chat_template_kwargs') or {});kwargs.update(PROFILE.get('chat_template_kwargs',{}));kwargs['enable_thinking']=THINKING
 result['chat_template_kwargs']=kwargs
 counts=dict(context_managed=managed,assistant_turns=0,reasoning_from_request=0,reasoning_from_cache=0,existing_think_tags=0,reasoning_from_tool_call_ids=0,verified_empty_reasoning=0)
 if result.get('model')==REPAIR_MODEL:result['model']=MODEL
 for name in ('max_completion_tokens','max_new_tokens','max_output_tokens'):
  result.pop(name,None)
 result['max_tokens']=PROFILE['max_tokens']
 if 'generation_stop' in PROFILE:result['stop']=list(PROFILE['generation_stop'])
 result.pop('enable_thinking',None)
 counts['budget_exception']=BUDGET_POLICY
 messages=payload.get('messages',[]); rendered=[]
 with LOCK,db() as c:
  for i,m0 in enumerate(messages):
   m=dict(m0)
   if m.get('role')=='assistant':
    counts['assistant_turns']+=1
    if managed:
     if m.get('reasoning_content') or m.get('reasoning'):raise ValueError('Managed reasoning must be rendered before aging')
     rendered.append(m);continue
    r=m.get('reasoning_content') or m.get('reasoning')
    if isinstance(r,str) and r: counts['reasoning_from_request']+=1
    elif PROFILE.get('history_content_policy')!='literal' and isinstance(m.get('content'),str) and '</think>' in m['content']:
     counts['existing_think_tags']+=1;r=None
    else:
     row=c.execute('select reasoning from history where signature=?',(key(messages[:i+1],conversation_id,strip_thinking_tags=PROFILE.get('history_content_policy')!='literal'),)).fetchone()
     r=row[0] if row else None
     if r:counts['reasoning_from_cache']+=1
     elif row is not None:counts['verified_empty_reasoning']+=1
     elif tool_signature(m):
      row=c.execute('select reasoning from tool_history where signature=?',(tool_signature(m),)).fetchone()
      if row:
       r=row[0]
       if r:counts['reasoning_from_tool_call_ids']+=1
       else:counts['verified_empty_reasoning']+=1
    if isinstance(r,str) and (r or PROFILE.get('history_content_policy')=='literal'):
     # Explicit empty reasoning prevents the native template from reparsing
     # literal closing tags in content after a runner has omitted this field.
     content=plain_content(m,strip_thinking_tags=PROFILE.get('history_content_policy')!='literal')
     if not isinstance(content,str):raise ValueError('Nontext assistant reasoning requires explicit handling')
     if PROFILE.get('history_encoding','qwen_think_tags')=='reasoning_field':
      m['content']=content;m['reasoning_content']=r;m.pop('reasoning',None)
     else:
      m['content']='<think>\n'+r+'\n</think>\n\n'+content
      m.pop('reasoning_content',None);m.pop('reasoning',None)
   rendered.append(m)
 if benchmark_label(payload) in GENERATED_HISTORY_TASKS:
  accounted=sum(counts[k] for k in ('reasoning_from_request','reasoning_from_cache','existing_think_tags','reasoning_from_tool_call_ids','verified_empty_reasoning'))
  if managed or accounted!=counts['assistant_turns']:
   raise HistoryIntegrityError('Generated assistant history lacks reasoning provenance')
 if message_policy(PROFILE)==SYSTEM_TO_USER and (result.get('tools') or result.get('functions')):
  raise ValueError('System-to-user representation does not support tools')
 if 'messages' in payload:
  result['messages']=adapt_messages(rendered,PROFILE)
  counts['message_policy']=message_policy(PROFILE)
  counts['folded_system_messages']=len(rendered)-len(result['messages'])
 adapter=PROFILE.get('tool_adapter')
 if adapter is not None:
  if adapter!=gaia_transport_adapter.ADAPTER_ID:raise ValueError('Unknown tool adapter')
  result=gaia_transport_adapter.adapt_request(result)
  counts['tool_adapter']=adapter
 return result,counts

def record_response(request, answer, status, usage=None, finish=None, effective_request=None):
 final=answer.get('content') or ''
 reasoning=answer.get('reasoning_content') or answer.get('reasoning') or ''
 text=final if isinstance(final,str) else json.dumps(final)
 # This is a repetition heuristic, not a semantic diagnosis.
 words=(reasoning+' '+text).split()
 tail=words[-512:]
 grams=[tuple(tail[i:i+12]) for i in range(max(0,len(tail)-11))]
 repeated=bool(len(grams)>=64 and len(set(grams))/len(grams)<0.25)
 record=dict(time=time.time(),status=status,finish_reason=finish,usage=usage,
  empty_final=not text.strip(),has_tool_calls=bool(answer.get('tool_calls')),
  final_chars=len(text),reasoning_chars=len(reasoning),repetition_heuristic=repeated,
  requested_thinking=THINKING,spontaneous_reasoning=bool(reasoning) and not THINKING,
  truncated=finish=='length',benchmark=benchmark_label(request),budget_policy=BUDGET_POLICY)
 raw_id=uuid.uuid4().hex;record['raw_id']=raw_id
 with LOCK:
  raw_dir=ROOT/'raw_api';raw_dir.mkdir(exist_ok=True,mode=0o700)
  with gzip.open(raw_dir/(raw_id+'.json.gz'),'wt') as f:json.dump(dict(request=request,effective_request=effective_request,answer=answer,**record),f,ensure_ascii=False)
  with (ROOT/'response_audit.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')

def audit(data):
 with LOCK:
  with (ROOT/'effective_requests_secondary.jsonl').open('a') as f:f.write(json.dumps(dict(time=time.time(),**data))+'\n')
 os.chmod(ROOT/'effective_requests_secondary.jsonl',0o600)

class Handler(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def do_GET(self):self.forward()
 def do_POST(self):self.forward()
 def forward(self):
  private_label=None
  for label in ALLOWED_LABELS:
   prefix='/'+label+'/'
   if self.path.startswith(prefix):private_label=label;self.path='/'+self.path[len(prefix):];break
  raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
  obj=None; counts={}; applied={}; start=time.monotonic();modified=None;attempt_id=uuid.uuid4().hex
  if raw and self.path.split('?')[0] in ('/v1/chat/completions','/v1/completions'):
   try:
    obj=json.loads(raw);obj.update({'campaign_benchmark_label':private_label} if private_label else {});label=benchmark_label(obj)
    if self.headers.get('X-S5-Nano-Conversation-Id'):obj['campaign_conversation_id']=self.headers['X-S5-Nano-Conversation-Id']
    modified,counts=enforce(obj);raw=json.dumps(modified).encode()
    applied=dict(POLICY,enable_thinking=THINKING,max_tokens=modified.get('max_tokens'),max_completion_tokens=modified.get('max_completion_tokens'),stop=modified.get('stop'))
    audit(dict(status='forwarding',path=self.path,model=obj.get('model'),benchmark=label,budget_policy=BUDGET_POLICY,wire_sha256=hashlib.sha256(raw).hexdigest(),requested={k:obj.get(k) for k in (*POLICY,'chat_template_kwargs','max_tokens','max_completion_tokens','stop')},applied=applied,history=counts,native_budget_fields={k:modified[k] for k in ('max_tokens','max_completion_tokens','stop','reasoning_effort') if k in modified}))
    receipt=store_http(ROOT,attempt_id,'candidate_request',dict(requested=obj,effective=modified,time=time.time(),wire_sha256=hashlib.sha256(raw).hexdigest()))
    append_http(ROOT/'candidate_attempts.jsonl',dict(attempt_id=attempt_id,phase='started',benchmark=label,time=time.time(),**receipt))
   except HistoryIntegrityError:
    receipt=store_http(ROOT,attempt_id,'candidate_request_rejected',dict(requested=obj,time=time.time(),error='history_integrity',new_model_call=False))
    append_http(ROOT/'candidate_attempts.jsonl',dict(attempt_id=attempt_id,phase='rejected',benchmark=label,time=time.time(),new_model_call=False,**receipt))
    audit(dict(status='rejected_history',benchmark=label,attempt_id=attempt_id,new_model_call=False))
    self.send_error(500,'Evaluation history is incomplete; no upstream request was made');return
   except (ValueError,TypeError):self.send_error(400,'Invalid campaign request');return
  headers={k:v for k,v in self.headers.items() if k.lower() not in ('host','connection','content-length','transfer-encoding','authorization','x-s5-nano-conversation-id')}
  credential=os.environ.get('S5_NANO_MODEL_API_KEY')
  if credential:headers['Authorization']='Bearer '+credential
  headers['Content-Length']=str(len(raw))
  conn=(HTTPSConnection if UPSTREAM.scheme=='https' else HTTPConnection)(UPSTREAM.hostname,UPSTREAM.port,timeout=21600)
  upstream_path=UPSTREAM.path.rstrip('/')+self.path.removeprefix('/v1')
  try:
   conn.request(self.command,upstream_path,body=raw or None,headers=headers)
   response=conn.getresponse()
   stream='text/event-stream' in response.getheader('Content-Type','')
   self.send_response(response.status)
   for k,v in response.getheaders():
    if k.lower() not in ('connection','keep-alive','content-length','transfer-encoding','date','server'):self.send_header(k,v)
   if stream:
    self.send_header('Transfer-Encoding','chunked');self.send_header('Connection','close');self.end_headers()
    answer=dict(role='assistant',content='',reasoning_content='');calls={};finished=False;usage=None;finish=None
    while True:
     line=response.readline()
     if not line:break
     self.wfile.write(('%X\r\n'%len(line)).encode()+line+b'\r\n');self.wfile.flush()
     if line.startswith(b'data: [DONE]'):finished=True
     if line.startswith(b'data: ') and not line.startswith(b'data: [DONE]'):
      try:
       event=json.loads(line[6:]);choices=event.get('choices') or []
       if event.get('usage'):usage=event['usage']
       if choices and choices[0].get('index',0)==0:
        delta=choices[0].get('delta') or {}
        if choices[0].get('finish_reason'):finish=choices[0]['finish_reason']
        answer['content']+=delta.get('content') or ''
        answer['reasoning_content']+=delta.get('reasoning_content') or delta.get('reasoning') or ''
        for call in delta.get('tool_calls') or []:
         target=calls.setdefault(call.get('index',0),dict(id='',type='function',function=dict(name='',arguments='')))
         for k in ('id','type'):
          if call.get(k):target[k]=call[k]
         for k in ('name','arguments'):
          if (call.get('function') or {}).get(k):target['function'][k]+=call['function'][k]
      except (ValueError,TypeError):pass
    self.wfile.write(b'0\r\n\r\n');self.wfile.flush();self.close_connection=True
    if calls:answer['tool_calls']=[calls[i] for i in sorted(calls)]
    if obj and response.status==200 and finished:save_reasoning(obj.get('messages',[]),answer,obj.get('campaign_conversation_id'))
    if obj:record_response(obj,answer,response.status,usage,finish,modified)
   else:
    data=response.read()
    if obj:
     import base64
     receipt=store_http(ROOT,attempt_id,'candidate_response',dict(status=response.status,time=time.time(),elapsed_seconds=time.monotonic()-start,wire_body_base64=base64.b64encode(data).decode()))
     append_http(ROOT/'candidate_attempts.jsonl',dict(attempt_id=attempt_id,phase='finished',status=response.status,time=time.time(),elapsed_seconds=time.monotonic()-start,**receipt))
    if obj and response.status==200:
     try:
      parsed=json.loads(data)
      if PROFILE.get('tool_adapter')==gaia_transport_adapter.ADAPTER_ID:
       parsed=gaia_transport_adapter.adapt_response(parsed,obj)
       data=json.dumps(parsed,ensure_ascii=False).encode()
      for choice in parsed.get('choices',[])[:1]:
       if choice.get('message'):
        record_response(obj,choice['message'],response.status,parsed.get('usage'),choice.get('finish_reason'),modified)
        save_reasoning(obj.get('messages',[]),choice['message'],obj.get('campaign_conversation_id'))
     except (ValueError,TypeError):raise
    self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
   if obj:audit(dict(status=response.status,path=self.path,model=obj.get('model'),elapsed_s=round(time.monotonic()-start,3),applied=applied,history=counts))
  except Exception as exc:
   audit(dict(status='error',error_type=type(exc).__name__,path=self.path))
   if obj:append_http(ROOT/'candidate_attempts.jsonl',dict(attempt_id=attempt_id,phase='failed',error_type=type(exc).__name__,time=time.time(),elapsed_seconds=time.monotonic()-start,cost_status='unknown_after_transport_failure'))
   self.close_connection=True
  finally:conn.close()
if __name__=='__main__':
 os.umask(0o077);ROOT.mkdir(exist_ok=True)
 ThreadingHTTPServer.request_queue_size=256
 ThreadingHTTPServer(('127.0.0.1',int(os.environ['S5_NANO_PROXY_PORT'])),Handler).serve_forever()
