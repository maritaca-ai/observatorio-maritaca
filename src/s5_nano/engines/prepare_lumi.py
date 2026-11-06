"""Pin public benchmark inputs; retain all raw inputs privately."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
PINS={
 'mmlu_pt_high_school':('mmlu-pt/mmlu-pt-high-school-full','b29d6ca3887d250114b543974fa8845a3143e229'),
 'mmlu_pt_undergraduate':('mmlu-pt/mmlu-pt-undergraduate-full','98cc293cd60c3779c2b1da1dd5abb3b47d9dee42'),
 'global_mmlu_pt':('CohereForAI/Global-MMLU','0e619dbeb34206cd48705a1a0ea7fb21cae09993'),
}
HARNESS_SHA='d6de81643928d653435c431bae19945d41d32520'
EXPECTED={'mmlu_pt_high_school':7233,'mmlu_pt_undergraduate':19347,
          'global_mmlu_pt':14042}

def fetch(url,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with urllib.request.urlopen(url,timeout=120) as r:body=r.read()
        temp=path.with_suffix(path.suffix+'.tmp');temp.write_bytes(body);temp.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def parse_alternatives(value):
    if not isinstance(value,str):return value
    try:return json.loads(value)
    except json.JSONDecodeError:pass
    # The release serializes a Python-style dictionary, including literal
    # newlines and unescaped LaTeX. Decode quoted values without interpreting
    # LaTeX backslashes as Python control/unicode escapes.
    parts=[];i=0
    while i<len(value):
        if value[i] not in "\"'":parts.append(value[i]);i+=1;continue
        quote=value[i];i+=1;chars=[]
        while i<len(value):
            c=value[i]
            if c==quote:i+=1;break
            if c=='\\' and i+1<len(value) and value[i+1] in (quote,'\\'):
                chars.append(value[i+1]);i+=2
            else:chars.append(c);i+=1
        else:raise ValueError('Unterminated dataset string')
        parts.append(json.dumps(''.join(chars),ensure_ascii=False))
    return json.loads(''.join(parts))

def main():
    import pyarrow.parquet as pq
    DATA.mkdir(exist_ok=True)
    manifest={'datasets':{},'sources':{}}
    raw={}
    for task,(repo,rev) in PINS.items():
        meta=DATA/task/'metadata.json'
        fetch(f'https://huggingface.co/api/datasets/{repo}/revision/{rev}',meta)
        info=json.loads(meta.read_text())
        paths=[f['rfilename'] for f in info['siblings']]
        if task == 'global_mmlu_pt':paths=[p for p in paths if p.startswith('pt/') and p.endswith('.parquet')]
        else:paths=[p for p in paths if p.endswith('.parquet')]
        files={}
        def get(p):
            dest=DATA/task/p
            return p,fetch(f'https://huggingface.co/datasets/{repo}/resolve/{rev}/{p}',dest)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:files=dict(pool.map(get,paths))
        raw[task]={}
        for p in paths:
            if p.endswith('.parquet'):
                split=Path(p).name.split('-00000')[0]
                raw[task][split]=pq.read_table(DATA/task/p).to_pylist()
            else:
                with (DATA/task/p).open() as f:raw[task]['test']=[json.loads(l) for l in f]
        manifest['datasets'][task]={'repo':repo,'revision':rev,'files':files,
            'counts':{k:len(v) for k,v in raw[task].items()}}
    examples=[]
    # Native Portuguese-MMLU release has no held-out dev split: use 0-shot, all rows.
    for task in ['mmlu_pt_high_school','mmlu_pt_undergraduate']:
        for split,rows in raw[task].items():
            for idx,row in enumerate(rows):
                alternatives=parse_alternatives(row['alternatives'])
                if isinstance(alternatives,dict) and 'text' in alternatives:
                    # Use every supplied choice in its published order. Some
                    # redundant label arrays contain an unused fifth label;
                    # never truncate, deduplicate, or drop the choice texts.
                    options='\n'.join(f'{chr(65+i)}. {text}' for i,text in enumerate(alternatives['text']))
                    assert str(row['answer']).upper() in 'ABCDEFGHIJ'[:len(alternatives['text'])]
                elif isinstance(alternatives,dict):
                    options='\n'.join(f'{str(k).strip()}. {v}' for k,v in alternatives.items())
                else:
                    options='\n'.join(f'{chr(65+i)}. {v}' for i,v in enumerate(alternatives))
                gold=str(row['answer']).strip().upper()
                assert len(gold)==1 and gold in 'ABCDEFGHIJ',(task,split,idx,gold)
                prompt='Responda à questão de múltipla escolha. Termine com "Resposta: X", substituindo X pela letra da alternativa correta.\n\n'+row['statement'].strip()+'\n'+options
                examples.append(dict(task=task,id=f'{split}/{idx}',prompt=prompt,gold=gold,group=split,fewshot=0))
    def global_item(row):
        return row['question'].strip()+'\n'+'\n'.join(f'{k.upper()}. {row["option_"+k]}' for k in 'abcd')+'\nAnswer:'
    for row in raw['global_mmlu_pt']['test']:
        dev=[d for d in raw['global_mmlu_pt']['dev'] if d['subject']==row['subject']]
        assert len(dev)==5,(row['subject'],len(dev))
        prompt='Answer the multiple-choice question. End your response with "Answer: X", where X is the correct option letter.\n\n'
        prompt+='\n\n'.join(global_item(d)+' '+d['answer'] for d in dev)+'\n\n'+global_item(row)
        examples.append(dict(task='global_mmlu_pt',id=str(row['sample_id']),prompt=prompt,gold=row['answer'],group=row['subject'],fewshot=5))
    assert len({(x['task'],x['id']) for x in examples})==len(examples)
    counts={t:sum(x['task']==t for x in examples) for t in EXPECTED}
    assert counts==EXPECTED,counts
    p=DATA/'items.jsonl'
    p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in examples))
    manifest.update(counts=counts,total=len(examples),items_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
        harness_source_revision=HARNESS_SHA,
        protocol={'mmlu_pt':'Full official splits, 0-shot generative answer accuracy; no test demonstrations',
                  'global_mmlu':'Full Portuguese test, 5 official dev examples per subject, generative answer accuracy',
                  'comparison':'Lumi scores are publisher-reported; identical versions/protocol cannot be established from its card'})
    save(ROOT/'manifest.json',manifest)
    print(json.dumps({'counts':counts,'total':len(examples),'items_sha256':manifest['items_sha256']}))

if __name__=='__main__':main()
