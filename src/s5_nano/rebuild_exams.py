"""Recreate the exact text subsets from the authors' public releases."""
import hashlib,json
from pathlib import Path
from .prepare import fetch

def write_rows(path,rows,checksum):
 data=''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows).encode()
 if hashlib.sha256(data).hexdigest()!=checksum:raise ValueError('Rebuilt subset differs from the frozen campaign: '+str(path))
 path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o600)

def rebuild_enem(root):
 source=fetch('https://www.kaggle.com/api/v1/datasets/download/andersonlbsoares/enem-v-questions/dataset.json?datasetVersionNumber=4',root/'raw/enem_v4.json','1e96064414b00ce3953502dd9aa8abd3927d66f85f47878cb736d20fd6a35eb8')
 fields=['id','ano','idioma','prova','numero_questao','area','texto_apoio_externo','texto_apoio_questao','enunciado','alternativas','resposta']
 rows=[{k:x[k] for k in fields} for x in json.loads(source.read_text()) if 2020<=int(x['ano'])<=2025 and not x['imagens_extraidas'] and x['resposta']!='ANULADA']
 assert len(rows)==1988 and len({x['id'] for x in rows})==1988
 write_rows(root/'sources/maritaca-utils/benchmarks/enem_vl_bench/data/enem_vl_2020_2025_text.jsonl',rows,'8a8b1b4db2ed4231e9eeb95108f1d25a5c4c644cf81d95efdbdac38ae3c63981')

def rebuild_bluex(root):
 import pyarrow.parquet as pq
 source=fetch('https://huggingface.co/datasets/Tropic-AI/BLUEX-v2/resolve/9284b8cc1bf97abe9eb99bc915e6d390b560fe39/data/train-00000-of-00001.parquet',root/'raw/bluex_v2.parquet','9f976ddeabeb1d223043f2529024c866a7e98b62547393230d47010c810320d6')
 grouped={}
 for x in pq.read_table(source).to_pylist():
  if x['images'] or '[IMAGE' in x['expected_answer']:continue
  q=grouped.setdefault(x['question_id'],{k:x[k] for k in ['question_id','university','year','subject','question_text']}|{'subquestions':[]})
  q['question_text']=q['question_text'].strip()
  q['subquestions'].append({'id':x['id'],'label':x['subquestion_label'],'text':x['subquestion_text'].strip(),'expected_answer':x['expected_answer'].strip(),'criteria':x['marking_criteria']})
 rows=sorted(grouped.values(),key=lambda x:x["question_id"]);assert len(rows)==173 and sum(len(x['subquestions']) for x in rows)==395
 write_rows(root/'sources/maritaca-utils/benchmarks/bluex_v2_bench/data/bluex_v2_text.jsonl',rows,'3bdd4f2d5ff8d016ec55d3aa8bc909dc0c00a8a78a0cbc165dc3b2df955b98a9')
