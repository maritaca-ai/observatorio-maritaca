"""Boundary tests for profile enforcement, history and frozen run identities."""
import importlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from s5_nano.prepare import REPO
from s5_nano.runtime import freeze
from s5_nano.runtime_config import read_profile

class ProtocolTests(unittest.TestCase):
 def test_conduta_http_route_enforces_profile_and_records_benchmark(self):
  from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
  from threading import Thread
  from urllib.request import Request,urlopen
  from urllib.parse import urlsplit
  for mode in ['thinking','instruct']:
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
    proxy=self.proxy(mode,folder);seen=[]
    class Upstream(BaseHTTPRequestHandler):
     def do_POST(self):
      payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
      seen.append((self.path,payload))
      body=json.dumps(dict(model=proxy.MODEL,choices=[dict(message=dict(role='assistant',content='Synthetic final',reasoning_content=''),finish_reason='stop')],usage=dict(prompt_tokens=10,completion_tokens=5))).encode()
      self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
     def log_message(self,*args):pass
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    proxy.UPSTREAM=urlsplit('http://127.0.0.1:'+str(upstream.server_port)+'/v1')
    forwarding=ThreadingHTTPServer(('127.0.0.1',0),proxy.Handler)
    threads=[Thread(target=s.serve_forever,daemon=True) for s in [upstream,forwarding]]
    for thread in threads:thread.start()
    try:
     payload=dict(model=proxy.MODEL,messages=[dict(role='user',content='Synthetic case')],temperature=0,max_tokens=1)
     request=Request('http://127.0.0.1:'+str(forwarding.server_port)+'/conduta_bench/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
     with urlopen(request,timeout=10) as response:self.assertEqual(response.status,200)
     self.assertEqual(seen[0][0],'/v1/chat/completions')
     for key,value in proxy.PROFILE['sampling'].items():self.assertEqual(seen[0][1][key],value)
     self.assertEqual(seen[0][1]['max_tokens'],proxy.PROFILE['max_tokens'])
     self.assertIs(seen[0][1]['chat_template_kwargs']['enable_thinking'],mode=='thinking')
     events=[json.loads(line) for line in (Path(folder)/'effective_requests_secondary.jsonl').read_text().splitlines()]
     self.assertEqual([e['benchmark'] for e in events if e['status']=='forwarding'],['conduta_bench'])
    finally:
     for server in [forwarding,upstream]:server.shutdown();server.server_close()
     for thread in threads:thread.join(timeout=3)
 def proxy(self,mode,folder):
  env={'S5_NANO_PROFILE':str(REPO/f'profiles/models/qwen3.5-4b/{mode}.json'),'S5_NANO_MODEL':'Qwen/Qwen3.5-4B','S5_NANO_AUDIT_DIR':folder,'S5_NANO_API_BASE':'http://127.0.0.1:8000/v1'}
  with patch.dict(os.environ,env):
   for name in ['s5_nano.runtime_config','s5_nano.proxy']:sys.modules.pop(name,None)
   return importlib.import_module('s5_nano.proxy')
 def test_instruct_forces_wire_profile(self):
  with tempfile.TemporaryDirectory() as d:
   proxy=self.proxy('instruct',d)
   request=dict(model=proxy.MODEL,messages=[dict(role='user',content='synthetic')],temperature=0,top_p=.1,max_tokens=1,max_completion_tokens=2,reasoning_effort='high',stop=['Q:'],extra_body=dict(top_k=1,reasoning_effort='low',chat_template_kwargs=dict(enable_thinking=True)))
   got,_=proxy.enforce(request)
   self.assertEqual(got['temperature'],.7);self.assertEqual(got['top_p'],.8);self.assertEqual(got['top_k'],20)
   self.assertFalse(got['chat_template_kwargs']['enable_thinking']);self.assertEqual(got['max_tokens'],32768)
   self.assertNotIn('max_completion_tokens',got);self.assertNotIn('reasoning_effort',got);self.assertEqual(got['stop'],['Q:'])
   self.assertEqual(request['temperature'],0)
 def test_history_survives_tool_argument_reserialization(self):
  with tempfile.TemporaryDirectory() as d:
   proxy=self.proxy('thinking',d);messages=[dict(role='user',content='synthetic')]
   answer=dict(role='assistant',content=None,reasoning='synthetic reasoning',tool_calls=[dict(id='fixture',type='function',function=dict(name='lookup',arguments='{"n":1}'))])
   proxy.save_reasoning(messages,answer);clean={k:v for k,v in answer.items() if k!='reasoning'}
   clean['tool_calls'][0]['function']['arguments']='{ "n": 1 }'
   got,counts=proxy.enforce(dict(model=proxy.MODEL,messages=messages+[clean,dict(role='tool',tool_call_id='fixture',content='synthetic result')]))
   self.assertIn('synthetic reasoning',got['messages'][1]['content']);self.assertEqual(counts['reasoning_from_cache'],1)
 def test_declared_generation_stops_override_request_without_mutation(self):
  with tempfile.TemporaryDirectory() as d:
   proxy=self.proxy('instruct',d)
   stops=['\n### Instrução:','\n### Resposta:','</s>']
   proxy.PROFILE['generation_stop']=stops
   request=dict(model=proxy.MODEL,messages=[dict(role='user',content='synthetic')],stop=['wrong'],extra_body={'stop':['also wrong']})
   got,_=proxy.enforce(request)
   self.assertEqual(got['stop'],stops)
   self.assertEqual(request['stop'],['wrong'])
   self.assertIsNot(got['stop'],stops)
 def test_invalid_declared_generation_stops_are_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   original=json.loads((REPO/'profiles/models/qwen3.5-4b/instruct.json').read_text())
   path=Path(d)/'profile.json'
   for value in [None,[],[''],['ok',1],'stop']:
    path.write_text(json.dumps(dict(original,generation_stop=value)))
    with self.assertRaises(ValueError):read_profile(path)
 def test_instruct_preserves_spontaneous_reasoning_without_changing_mode(self):
  with tempfile.TemporaryDirectory() as d:
   proxy=self.proxy('instruct',d)
   answer=dict(role='assistant',content='synthetic',reasoning='unexpected')
   proxy.save_reasoning([],answer)
   got,counts=proxy.enforce(dict(model=proxy.MODEL,messages=[dict(role='assistant',content='synthetic')]))
   self.assertEqual(counts['reasoning_from_cache'],1)
   self.assertIn('unexpected',got['messages'][0]['content'])
   self.assertEqual(answer['content'],'synthetic')
   self.assertFalse(got['chat_template_kwargs']['enable_thinking'])
 def test_empty_reasoning_is_distinct_from_missing_history(self):
  with tempfile.TemporaryDirectory() as d:
   proxy=self.proxy('thinking',d);messages=[dict(role='user',content='synthetic')]
   answer=dict(role='assistant',content='synthetic answer',reasoning_content='')
   request=dict(model=proxy.MODEL,messages=messages+[answer,dict(role='user',content='follow up')])
   _,missing=proxy.enforce(request)
   self.assertEqual(missing['verified_empty_reasoning'],0)
   proxy.save_reasoning(messages,answer)
   got,known=proxy.enforce(request)
   self.assertEqual(known['verified_empty_reasoning'],1)
   self.assertEqual(known['reasoning_from_cache'],0)
   self.assertEqual(got['messages'][1]['content'],answer['content'])
   self.assertTrue(got['chat_template_kwargs']['enable_thinking'])
 def test_no_cross_model_or_mode_cache_reuse(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'manifest.json';freeze(p,dict(model='candidate',mode='thinking'))
   freeze(p,dict(model='candidate',mode='thinking'))
   with self.assertRaises(ValueError):freeze(p,dict(model='candidate',mode='instruct'))
   with self.assertRaises(ValueError):freeze(p,dict(model='competitor',mode='thinking'))
 def test_profiles_are_explicit(self):
  for p in (REPO/'profiles/models').rglob('*.json'):
   v=read_profile(p);self.assertIn(v['mode'],['thinking','instruct']);self.assertIs(v['enable_thinking'],v['mode']=='thinking')
