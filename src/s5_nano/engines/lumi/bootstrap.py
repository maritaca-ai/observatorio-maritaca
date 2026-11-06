import json,os
from pathlib import Path
from s5_nano.runtime_config import POLICY,THINKING
R=Path(__file__).resolve().parent
RUN=os.environ['S5_NANO_MODEL']
def save(name,value):
 p=R/name;p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
