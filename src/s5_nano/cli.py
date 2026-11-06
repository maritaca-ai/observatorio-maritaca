"""Prepare and execute the selected native protocols."""
import argparse,json,os
from pathlib import Path
from .prepare import REPO,prepare

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','preflight','run'])
 catalog=json.loads((REPO/'benchmarks/catalog.json').read_text())
 p.add_argument('--benchmark',choices=list(catalog),required=True);p.add_argument('--cache',type=Path,default=REPO/'.cache')
 p.add_argument('--profile',type=Path);p.add_argument('--model');p.add_argument('--api-base',default='http://127.0.0.1:8000/v1')
 p.add_argument('--output',type=Path);p.add_argument('--workers',type=int,default=4)
 p.add_argument('--tokenizer');p.add_argument('--chat-template');p.add_argument('--marca-snapshot',type=Path)
 p.add_argument('--task',action='append');p.add_argument('--allow-chat-adapter',action='store_true')
 a=p.parse_args(argv);os.umask(0o077);a.cache=a.cache.resolve()
 if a.command=='prepare':
  family=catalog[a.benchmark]['family']
  if family=='remaining':
   from .remaining_inputs import prepare as remaining
   remaining(a.benchmark,a.cache)
  else:prepare(family,a.cache)
  return
 if not all([a.profile,a.model,a.output]):p.error('profile, model and output are required')
 if a.workers<1:p.error('workers must be positive')
 if a.benchmark in ['mmlu_pt','global_mmlu_pt'] and not a.allow_chat_adapter:p.error('Recorded MMLU protocol requires --allow-chat-adapter')
 a.output=a.output.resolve();a.profile=a.profile.resolve()
 from .runtime import execute
 execute(a.benchmark,a,preflight=a.command=='preflight')
if __name__=='__main__':main()
