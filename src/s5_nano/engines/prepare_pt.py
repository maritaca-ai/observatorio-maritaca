"""Freeze public inputs and native prompts once; no inference or publication."""
import hashlib
import json
import os
from pathlib import Path
import random

import pandas as pd
import pt_native

R = Path(__file__).resolve().parent


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def doc_id(doc):
    return str(doc.get('id', doc.get('sentence_pair_id')))


def make_chat(native, obj, docs, task_name, shots, limit=None, exclude_current=False):
    obj.set_inference_model_category(native.ModelCategory.CHAT_MODEL)
    obj._training_docs = None
    obj._fewshot_docs = None
    descriptions = json.loads((R/'sources/PoETaV2/description.json').read_text())
    description = descriptions.get(task_name, descriptions.get(task_name.replace('_greedy',''),''))
    assert description
    selected = []
    original = obj.fewshot_examples
    def examples(k, rnd, prompt_mode, doc):
        if exclude_current:
            # BRoverbs paper: one different example per evaluated item, never itself.
            assert k == 1
            pool = [d for d in obj.training_docs() if doc_id(d) != doc_id(doc)]
            result = rnd.sample(pool, k)
        else:
            result = original(k=k, rnd=rnd, prompt_mode=prompt_mode, doc=doc)
        selected[:] = [doc_id(d) for d in result]
        assert doc_id(doc) not in selected
        return result
    obj.fewshot_examples = examples
    docs = list(docs)
    rnd = random.Random(42)
    rnd.shuffle(docs)
    rows = []
    for doc in docs[:limit] if limit is not None else docs:
        context = obj.fewshot_context(doc=doc, num_fewshot=shots, prompt_mode='dynamic-random',
            rnd=rnd, description=description, conversation_template='chatgpt', prompt_as_single_user_message=False)
        messages = json.loads(context)
        # Match PoETa's public OpenAI-compatible chat adapter.
        if messages[0] == {'role':'system','content':'You are a helpful assistant.'}:
            messages = messages[1:]
        assert messages[-1]['role'] == 'user'
        rows.append(dict(id=doc_id(doc), doc=doc, messages=messages, fewshot_ids=list(selected),
                         native_task=task_name, native_stop=['\n'], applied_http_stop=None))
    return rows


def main():
    os.umask(0o077)
    native = pt_native.load()
    builder, _ = pt_native.math_functions()
    raw = json.loads((R/'data/math_pt/ptbr_multiple_choice_test.json').read_text())
    assert isinstance(raw,list) and len(raw)==638
    math_rows = []
    for i, doc in enumerate(raw):
        _, prompt = builder('multiple-choice', doc['problem'], doc['choices'])
        math_rows.append(dict(id=str(i), doc=doc, messages=[dict(role='user',content=prompt)], fewshot_ids=[]))
    write(R/'cases/math_pt_br_mc.json', math_rows)

    bro_rows = []
    classes = {'history_to_proverb':native.BroverbsHistoryToProverbTaskGreedy,
               'proverb_to_history':native.BroverbsProverbToHistoryTaskGreedy}
    for direction, cls in classes.items():
        raw = pd.read_parquet(R/f'data/broverbs/data/{direction}-00000-of-00001.parquet').to_dict('records')
        assert len(raw)==579
        obj = object.__new__(cls)
        docs = []
        for i, row in enumerate(raw):
            alternatives = list(row['alternatives'])
            assert len(alternatives)==5 and len(set(alternatives))==5
            item = dict(id=i, input=row['input'], target_scores={s:int(j==row['correct_index']) for j,s in enumerate(alternatives)})
            docs.append(obj._process_doc(item))
        obj.dataset = {'train': docs}
        rows = make_chat(native, obj, docs, 'broverbs_'+direction+'_greedy',1,exclude_current=True)
        for row in rows:
            row.update(id=direction+'/'+row['id'],direction=direction)
        bro_rows.extend(rows)
    write(R/'cases/broverbs.json',bro_rows)

    class LocalAssin(native.ASSIN_RTE_GREEDY):
        def download(self,*args,**kwargs):
            self.dataset = {s:pd.read_parquet(R/f'data/assin2/data/{s}-00000-of-00001.parquet').to_dict('records')
                            for s in ('train','test')}
    assin = LocalAssin()
    assert len(assin.dataset['test'])==2448 and len(assin.dataset['train'])==6500
    ass_rows = make_chat(native,assin,assin.test_docs(),'assin_rte_greedy',18,limit=300)
    write(R/'cases/assin_rte.json',ass_rows)
    tasks = {'math_pt_br_mc':math_rows,'broverbs':bro_rows,'assin_rte':ass_rows}
    protocols = {
        'math_pt_br_mc':dict(n=638,fewshot=0,subset='ptbr_multiple_choice/test',primary_metric='accuracy',
            prompt='Native MATH-PT ptbr prompt',parser='Native notebook boxed-letter extraction, final answer only'),
        'broverbs':dict(n=1158,per_direction=579,fewshot=1,seed=42,primary_metric='mean of both direction accuracies',
            paper='https://arxiv.org/abs/2509.08960',
            prompt_and_parser='Public PoETa v2 chat prompt builder and native letter parser',
            adaptation='Full public HF splits and one different example per question per BRoverbs paper; not PoETa 300-item/5-shot subset'),
        'assin_rte':dict(n=300,full_test_n=2448,fewshot=18,seed=42,subset='PoETa v2 canonical 300 after seed-42 test shuffle',
            primary_metric='macro F1',secondary_metric='accuracy',parser='Native strict sim/não string comparison')}
    manifest = dict(sources=json.loads((R/'sources.json').read_text()),protocols=protocols,
        tasks=list(tasks),paid_judge=False,
        chat_stop_policy='Public PoETa chat path does not apply newline stop or post-split; full final content only, reasoning excluded',
        prompt_adaptation='Only public definitions needed for these tasks loaded; optional unrelated harness backends not imported',
        files={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('sources','data','cases')
               for p in sorted((R/folder).rglob('*')) if p.is_file() and '__pycache__' not in p.parts})
    manifest['manifest_sha256'] = hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    write(R/'manifest.json',manifest)
    print(json.dumps(dict(counts={k:len(v) for k,v in tasks.items()},total=sum(len(v) for v in tasks.values()),
        manifest_sha256=manifest['manifest_sha256'],paid_judge=False)))


if __name__=='__main__': main()
