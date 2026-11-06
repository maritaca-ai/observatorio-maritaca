"""Rebuild public inputs locally, pinned by revision and SHA-256."""
import ast
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request

REPO=Path(__file__).resolve().parents[2]

def benchmark_dir(name):
 catalog=json.loads((REPO/'benchmarks/catalog.json').read_text())
 return REPO/catalog[name]['directory']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def fetch(url,path,expected):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():
  if sha(path)!=expected:raise ValueError('Cached input checksum mismatch: '+str(path))
  return path
 tmp=path.with_name(path.name+'.download')
 digest=hashlib.sha256()
 try:
  with urllib.request.urlopen(url,timeout=180) as src,tmp.open('wb') as dst:
   while block:=src.read(1024*1024):digest.update(block);dst.write(block)
  if digest.hexdigest()!=expected:raise ValueError('Public input checksum mismatch: '+str(path))
  tmp.chmod(0o600);tmp.replace(path)
 finally:
  if tmp.exists():tmp.unlink()
 return path

def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj);return obj

def prepare_lumi(root):
 lock=json.loads((REPO/'locks/lumi-inputs.json').read_text())
 p=module(REPO/'src/s5_nano/engines/prepare_lumi.py','s5_nano_prepare_lumi')
 p.ROOT=root;p.DATA=root/'data';p.main()
 for task,spec in lock['datasets'].items():
  for name,checksum in spec['files'].items():assert sha(root/'data'/task/name)==checksum
 assert len((root/'data/items.jsonl').read_text().splitlines())==40622
 for name,checksum in lock['sources'].items():assert sha(root/name)==checksum
 return root

def prepare_pt(root):
 lock=json.loads((REPO/'locks/pt-inputs.json').read_text());sources=lock['sources'];jobs=[]
 for name,checksum in lock['files'].items():
  if name.startswith('cases/'):continue
  parts=name.split('/');group=parts[1];tail='/'.join(parts[2:])
  if parts[0]=='sources':
   directory='math_pt' if group=='MATH-PT' else 'assin_rte'
   local=benchmark_dir(directory)/'fork/upstream'/tail
   if local.exists():
    assert sha(local)==checksum
    dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(local,dest);continue
  if parts[0]=='sources':
   spec=sources[group];repo=spec['url'].replace('https://github.com/','')
   url=f'https://raw.githubusercontent.com/{repo}/{spec["revision"]}/{tail}'
  else:
   spec=sources[group];repo=spec['url'].replace('https://huggingface.co/datasets/','')
   url=f'https://huggingface.co/datasets/{repo}/resolve/{spec["revision"]}/{tail}'
  jobs.append((url,root/name,checksum))
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda j:fetch(*j),jobs))
 save(root/'sources.json',sources)
 native=module(REPO/'src/s5_nano/engines/pt_native.py','pt_native');native.R=root;native.POETA=root/'sources/PoETaV2'
 prep=module(REPO/'src/s5_nano/engines/prepare_pt.py','s5_nano_prepare_pt');prep.R=root;prep.main()
 for name,checksum in lock['files'].items():assert sha(root/name)==checksum,name
 return root

def prepare_capitu(root):
 lock=json.loads((REPO/'locks/capitu-inputs.json').read_text());rev=lock['source']['revision'];source=root/'sources/capitu'
 for name,checksum in lock['source_hashes'].items():
  vendored=REPO/'benchmarks/instrucoes/capitu/fork'/name
  if vendored.exists():
   assert sha(vendored)==checksum
   dest=source/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(vendored,dest)
  else:fetch(f'https://raw.githubusercontent.com/maritaca-ai/capitu/{rev}/{name}',source/name,checksum)
 body={'source':lock['source'],'source_hashes':lock['source_hashes'],'counts':lock['counts']}
 body['manifest_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
 save(root/'manifest.json',body);return root

def prepare_public(root):
 lock=json.loads((REPO/'locks/public-inputs.json').read_text());files={}
 for name,checksum in lock['files'].items():
  assert name.startswith('sources/MARCA/'), 'Unexpected public MARCA source'
  if name.endswith(('.md','.txt')) or name.endswith('/LICENSE'):continue
  if name.endswith('.py'):
   source=REPO/'benchmarks/agentico/marca/fork'/name.removeprefix('sources/MARCA/');dest=root/name
   dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
  else:
   url='https://raw.githubusercontent.com/maritaca-ai/MARCA/'+lock['sources']['MARCA']['commit']+'/'+name.removeprefix('sources/MARCA/')
   dest=fetch(url,root/name,checksum)
  files[name]=sha(dest)
 body={'sources':lock['sources'],'protocols':lock['protocols'],'files':files,'adaptations':lock['adaptations']}
 body['manifest_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest();save(root/'manifest.json',body)
 return root

def prepare_exams(root):
 from .rebuild_exams import rebuild_enem,rebuild_bluex
 for name in ['enade_qa','enem_vl','bluex_v2']:
  dest=root/'sources/maritaca-utils/benchmarks'/(name+'_bench');dest.mkdir(parents=True,exist_ok=True)
  shutil.copyfile(benchmark_dir(name)/'fork/native.py',dest/'run_eval.py')
  if name=='bluex_v2':shutil.copyfile(REPO/'benchmarks/provas/bluex_v2/fork/judge_prompt.py',dest/'judge_prompt.py')
 fetch('https://raw.githubusercontent.com/H2IA/ENADE-QA/91674bb98f2e04f812b7c157e81362950e0f9eca/enade_mcqa_hf/data/enade_mcqa_unique_clean.jsonl',root/'sources/maritaca-utils/benchmarks/enade_qa_bench/data/enade_qa.jsonl','6afd6945a3f71d637515020f8d067519f7fa5b8f70b7dcb9895b43ad506caec4')
 rebuild_enem(root);rebuild_bluex(root)
 files={str(p.relative_to(root)):sha(p) for p in (root/'sources').rglob('*') if p.is_file()}
 body={'public_sources':True,'files':files};body['manifest_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest();save(root/'manifest.json',body)
 return root

def prepare_lumen(root):
 lock=json.loads((REPO/'locks/lumen-inputs.json').read_text())
 revision=lock['sources']['lumen']['revision']
 source=root/'sources/lumen'
 for name,checksum in lock['files'].items():
  fetch('https://raw.githubusercontent.com/TropicAI-Research/lumen/'+revision+'/'+name,source/name,checksum)
 body=dict(lock)
 body['manifest_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
 save(root/'manifest.json',body)
 return root

def prepare_prosa(root):
 lock=json.loads((REPO/'locks/prosa-inputs.json').read_text())
 source=root/'sources/Prosa';rev=lock['source']['revision']
 for name,checksum in lock['files'].items():
  dest=source/name
  if name.endswith('.py'):
   original=REPO/'benchmarks/chat/prosa_pt/fork'/name.removeprefix('Prosa-benchmark/')
   assert sha(original)==checksum
   dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
  else:fetch('https://raw.githubusercontent.com/maritaca-ai/Prosa/'+rev+'/'+name,dest,checksum)
 body=dict(lock);body['manifest_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
 save(root/'manifest.json',body)
 return root

def prepare(family,cache):
 import fcntl
 from .prepare_plus import prepare_plus
 os.umask(0o077);root=Path(cache)/'inputs'/family;root.mkdir(parents=True,exist_ok=True)
 with (root/'prepare.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if (root/'prepared.json').exists():
   receipt=json.loads((root/'prepared.json').read_text())
   for name,checksum in receipt['files'].items():assert sha(root/name)==checksum,name
   return root
  {'lumi':prepare_lumi,'pt':prepare_pt,'public':prepare_public,'capitu':prepare_capitu,'exams':prepare_exams,'lumen':prepare_lumen,'plus':prepare_plus,'prosa':prepare_prosa}[family](root)
  files={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and p.name not in ['prepare.lock','authorization.json'] and '__pycache__' not in p.parts}
  save(root/'prepared.json',{'family':family,'files':files,'data_published':False})
  return root
