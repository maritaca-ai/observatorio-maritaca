"""Read saved native artifacts into private case streams, without any model calls.

A local root map pins the aggregate, source folders and public protocol link.
This file contains no infrastructure destinations. Outputs belong outside Git.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import gzip
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path

REPLAY = {'global_mmlu_pt', 'mmlu_pt_high_school', 'mmlu_pt_undergraduate'}
PT = {'assin_rte', 'broverbs', 'math_pt_br_mc'}
REMAINING = {'arena_hard_v2', 'culturalbench', 'ifbench', 'longbench_v2', 'harmbench', 'sob', 'oab_bench_full', 'magis_bench', 'conduta_bench'}


def read(path):
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as stream:
        return json.load(stream)


def lines(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


@lru_cache(maxsize=None)
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def unique(rows, key):
    out = {}
    for row in rows:
        k = str(key(row))
        if k in out:
            raise ValueError('Duplicate identity')
        out[k] = row
    return out


def selected(row, keys):
    return {k: row[k] for k in keys if k in row}


def text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def saved_responses(folder):
    out = defaultdict(list)
    for path in sorted(folder.glob('*.json')):
        value = read(path)
        key = value.get('identity', {}).get('case', value.get('id'))
        if key is None:
            raise ValueError('Unknown saved response identity')
        out[str(key)].append((value, sha(path)))
    for key, rows in out.items():
        rows.sort(key=lambda pair: pair[0].get('identity', {}).get('turn', 0))
    return out


def common(spec, qid, question, context, reference, final, score, correction, metric, evidence, **extra):
    if not isinstance(final, str) or score is not None and not math.isfinite(score):
        raise ValueError('Invalid final or per-case score')
    task = spec['task']
    if task not in (REPLAY | PT | REMAINING | {'bluex_v2', 'enade_qa', 'enem_vl', 'marca_public', 'browsecomp_plus', 'prosa_pt', 'capitu', 'capitu_conversations', 'lumen_pt'}) or spec['model_id'] not in spec['allowed_models']:
        raise ValueError('Outside authorized catalog')
    question = text(question)
    context = text(context) if context else ''
    # Hash the shared input rather than the enclosing file, whose ordering may differ.
    input_hash = digest([question, context, reference])
    response = dict(model_id=spec['model_id'], mode=spec['mode'], final=final, score=score,
                    metric_name=metric, judgment=correction, secondary_metrics={},
                    provenance=dict(result_id=spec.get('result_id'), protocol_id=spec['protocol_id'], source_aggregate_sha256=spec.get('_aggregate_sha256'), **evidence), **extra)
    return dict(benchmark_id=task, protocol_id=spec['protocol_id'], input_sha256=input_hash,
                case_id=str(qid), question=question, context=context, reference=reference, criteria=[],
                public_source=spec['public_source'], responses=[response])


def correction(value, judge=None, note=None):
    return dict(kind='native', judge=judge, text=text(value), note=note)


def replay(spec, root, base):
    task = spec['task']
    folder = Path(spec['legacy_scoring']) if spec.get('legacy_scoring') else base/'runtime/results'/task
    p = folder/'scored_rows.jsonl'
    rows = lines(p)
    native = {}
    evidence = {'scored_rows_sha256':sha(p)}
    for r in rows:
        scored = native[r['prompt']] if native else selected(r, ['prediction','gold','correct','empty','finish_reason'])
        score = 100 * (scored['follow_all_instructions'] if native else scored['correct'])
        yield common(spec,r['id'],r['prompt'],'',r.get('gold'),r['response'],score,
                     correction(scored,note='Verificador estrito nativo' if native else 'Extração e correção registradas'),
                     'Prompt estrito × 100' if native else 'Acerto × 100',evidence)


def portuguese(spec, root, base):
    task = spec['task'];folder = root/'results'/task
    inputs = unique(read(base/'runtime/cases'/f'{task}.json'), lambda r:r['id'])
    p = folder/'scored_rows.json';scores = unique(read(p),lambda r:r['id']);responses = saved_responses(folder/'responses')
    if set(inputs) != set(scores) or set(inputs) != set(responses):raise ValueError('Portuguese populations differ')
    for qid, row in inputs.items():
        r, h = responses[qid][0];s = scores[qid];doc = row['doc'];messages = row['messages']
        reference = doc.get('answer',doc.get('gold',doc.get('entailment_judgment')))
        yield common(spec,qid,messages[-1]['content'],'',reference,r['content'],float(s['acc']) if task=='assin_rte' else 100*float(s.get('correct',s.get('acc'))),
                     correction(s,note='No ASSIN, este acerto individual não é o F1 macro agregado.' if task=='assin_rte' else None),
                     'Acerto × 100',dict(response_file_sha256=h,scored_rows_sha256=sha(p)), input_messages=messages)


def remaining(spec, root, base):
    task = spec['task'];source_task = spec.get('source_task',task);folder = root/'results'/source_task
    inputs_path = base/'runtime/data/selected.jsonl';inputs = lines(inputs_path)
    p = folder/'scored_rows.json';rows = read(p);evidence = dict(input_file_sha256=sha(inputs_path),scored_rows_sha256=sha(p))
    key = {'arena_hard_v2':'uid','culturalbench':'data_idx','ifbench':'key','longbench_v2':'_id','harmbench':'BehaviorID','sob':'_selection_id',
           'oab_bench_full':'question_id','magis_bench':'question_id','conduta_bench':'id'}[task]
    inputs = unique(inputs,lambda r:r[key]);responses = saved_responses(base/'results'/source_task/'responses')
    score_key = 'uid' if task=='arena_hard_v2' else 'key' if task=='ifbench' else 'question_id' if task in {'oab_bench','oab_bench_full','magis_bench'} else 'id'
    if task=='sob':
        scores={}
        for modality in ['text','image','audio']:
            native=lines(folder/(modality+'_native_responses.jsonl'))
            scored=[r for r in rows if r['modality']==modality]
            if len(native)!=len(scored):raise ValueError('SOB populations differ')
            for original,score_row in zip(native,scored):
                if str(original['metadata']['record_id'])!=str(score_row['record_id']):raise ValueError('SOB scoring order differs')
                sid=str(original['metadata']['_selection_id'])
                if sid in scores:raise ValueError('Duplicate SOB selection ID')
                scores[sid]=score_row
    else:scores=unique(rows,lambda r:r[score_key])
    references = {}
    if task=='conduta_bench':
        references=unique(lines(base/'runtime/inputs/data/rubrics.jsonl'),lambda r:r['id'])
        clinical=unique([read(x) for x in (folder/'judgments').glob('*.json')],lambda r:r['identity']['case'])
    if set(inputs) != set(responses):raise ValueError('Input/response populations differ')
    for qid, row in inputs.items():
        rs = responses[qid];last,h = rs[-1];final = last['final'] or '';messages = rs[0][0]['identity']['request']['messages']
        skey = qid
        s = scores[skey];question = row.get('question',row.get('prompt',messages[-1]['content']));context = '';reference = row.get('answer');score = None;metric = 'Correção nativa';judge = spec.get('judge');note = None
        if task in {'ifbench','longbench_v2','harmbench','culturalbench'}:
            field = {'ifbench':'strict','harmbench':'label'}.get(task,'correct');score = 100*float(s[field]);metric = 'Ação nociva × 100' if task=='harmbench' else 'Acerto × 100'
        if task=='culturalbench':
            question=row['prompt_question']+'\n\n'+row['prompt_option'];note='Acerto desta opção. A nota Hard exige acertar as quatro opções do grupo.'
        if task=='longbench_v2':
            question=row['question']+'\n\n'+'\n'.join(k+') '+row['choice_'+k] for k in 'ABCD')
            # The native scorer may truncate the input differently per model.
            note='O contexto original e a entrada efetiva estão separados; consulte a entrada recebida por este modelo.'
            context=row['context']
        if task=='harmbench':question=row['Behavior'];context=row.get('ContextString','')
        if task=='sob':
            question=row['question'];context=row['context'];reference=row['ground_truth'];score=100*s['schema_compliance'];metric='Conformidade ao schema × 100'
            note='Nota individual, antes dos pesos de dificuldade. OCR/transcrição não entram no agregado textual.'
        if task in {'oab_bench','oab_bench_full','magis_bench'}:
            question=row['statement'];context='\n\n'.join(row['turns']);score=s['score'];metric=f"Pontos nesta questão · máximo {sum(row['values']):g}"
            reference=None;note='O agregado soma pontos por prova/seção; não é a média destas notas individuais.'
        if task=='conduta_bench':
            question=row['question'];context=row.get('scenario','');reference=references[qid]['reference_answer'];score=s['metrics']['score'];metric='Nota clínica nativa'
            # Preserve the existing detailed rubric rendering.
            j=clinical[qid];verdict=dict(judge='sabia-4-thinking',hits=j['result']['hits'],text=j['result']['judgment'])
        else:verdict=correction(s,judge,note)
        item = common(spec,qid,question,context,reference,final,score,verdict,metric,dict(evidence,response_file_sha256=h), input_messages=messages)
        if task=='conduta_bench':item['criteria']=references[qid]['criteria']
        if task=='sob':item['schema']=row['json_schema']
        if len(rs)>1:item['responses'][0]['turns']=[dict(turn=v['identity']['turn'],question=v['identity']['request']['messages'][-1]['content'],final=v['final'],response_file_sha256=checksum) for v,checksum in rs]
        yield item


def bluex(spec, root, base):
    p=root/'results/bluex_v2/scored_rows.json'
    for r in read(p):
        rp=base/'results/bluex_v2/responses'/(hashlib.sha256(str(r['id']).encode()).hexdigest()+'.json');saved=read(rp)
        question=saved['question']['question_text']+'\n\n'+saved['sub']['text']
        yield common(spec,r['id'],question,'',saved['sub']['expected_answer'],r['response'] or '',r['score'],
                     correction(selected(r,['criteria_checks','judge_error','generation_error']),spec.get('judge'),
                                'Pontos nativos de 0 a 10. Falhas do juiz seguem a política nativa registrada.'),
                     'Pontos por rubricas · de 10',dict(scored_rows_sha256=sha(p),response_file_sha256=sha(rp)),input_messages=[dict(role='user',content=r['prompt'])])


def tool_cases(spec, root, base):
    task=spec['task'];out=root/'results'/task;generation=base/'results'/task
    p=out/('scored_summary.json' if task=='browsecomp_plus' else 'scored_rows.json');rows=read(p)
    if task=='browsecomp_plus':
        jobs=unique(read(base/'runtime/cases.json'),lambda r:r['query_id']);scores=unique(rows,lambda r:r['query_id'])
        js=unique([dict(read(x),_sha256=sha(x)) for x in (out/'judgments').glob('*.json')],lambda r:r['query_id'])
        for path in sorted((generation/'responses').glob('*.json')):
            r=read(path);qid=str(r['query_id']);job=jobs[qid];s=scores[qid];j=js[qid]
            yield common(spec,qid,job['query'],'',job.get('answer'),r['final'],100*int(s['correct']),correction(selected(j,['parsed','judge_error','answered']),j.get('judge')),
                         'Acerto × 100',dict(response_file_sha256=sha(path),scored_rows_sha256=sha(p),judgment_file_sha256=j['_sha256']),
                         tool_trace=r.get('messages'),tool_summary=selected(r,['status','error','iterations','tool_call_counts']))
    elif task=='marca_public':
        jobs=read(generation/'frozen_jobs.json');byfile={digest([j['dataset'],j['question']['id']]):j for j in jobs}
        for path in sorted((generation/'responses').glob('*.json')):
            r=read(path);j=read(generation/'judgments'/path.name);job=byfile[path.stem];qid=job['dataset']+':'+str(job['question']['id'])
            yield common(spec,qid,r['question'],'',None,r['response'] if r['response'] is not None else '',100*j['percentage_correct'],correction(selected(j,['checklist','judged_checklist']),spec.get('judge')),
                         'Critérios atendidos × 100',dict(response_file_sha256=sha(path),judgment_file_sha256=sha(generation/'judgments'/path.name)),
                         final_was_null=r['response'] is None,
                         tool_trace=[{k:v for k,v in t.items() if k not in ['reasoning','reasoning_content']} for t in r.get('conversation_generated',[])])
    else:
        for s in rows:
            key=s['key'];filename=digest(key)+'.json';path=generation/'responses'/filename;r=read(path)
            score=100*int(s['harmful']) if s['kind']=='harmful' else 100*int(s['benign_success'])
            yield common(spec,':'.join(map(str,key)),r['question_text'],r['system_prompt'],None,r['assistant_response'] or '',score,
                         correction(s,spec.get('judge'),'Controle benigno; não entra na taxa de dano.' if s['kind']=='benign' else 'Menor é melhor: mede ação nociva.'),
                         'Ação nociva × 100' if s['kind']=='harmful' else 'Sucesso benigno × 100',dict(response_file_sha256=sha(path),scored_rows_sha256=sha(p)),tool_trace=r.get('conversation',[]),tool_summary=selected(r,['tool_called','tools_called','refused']))


def exams(spec, root, base):
    task=spec['task'];folder=root/'results'/task;p=folder/'scored_rows.json'
    source=base/'runtime/sources/maritaca-utils/benchmarks'/(task+'_bench')
    if task=='enade_qa':
        inp=source/'data/enade_qa.jsonl';questions=lines(inp)
        byid=unique(questions,lambda r:r['id'])
    else:
        inp=source/'data/enem_vl_2020_2025_text.jsonl'
        if not inp.exists():
            candidates=list(source.glob('data/*.jsonl'))
            if len(candidates)!=1:raise ValueError('Ambiguous ENEM source')
            inp=candidates[0]
        questions=lines(inp);byid=unique(questions,lambda r:r['id'])
    scores=unique(read(p),lambda r:r['id']);responses=saved_responses(folder/'responses')
    for qid,score in scores.items():
        q=byid[qid];r,h=responses[qid][0]
        question=q.get('question',q.get('enunciado',q.get('pergunta')))
        options=q.get('options',q.get('alternativas',[]))
        if isinstance(options,dict):options=[str(k)+') '+str(v) for k,v in options.items()]
        else:options=[chr(65+i)+') '+str(v) for i,v in enumerate(options) if str(v).strip()]
        if question is None:raise ValueError('Unknown exam question layout')
        context='\n\n'.join(q[k] for k in ['texto_apoio_externo','texto_apoio_questao'] if isinstance(q.get(k),str) and q[k].strip() and q[k].lower()!='nan')
        yield common(spec,qid,question+'\n\n'+'\n'.join(options),context,score['gold'],r['content'] or '',100*score['correct'],correction(score),'Acerto × 100',
                     dict(input_file_sha256=sha(inp),scored_rows_sha256=sha(p),response_file_sha256=h))


def capitu(spec, root, base):
    multi=spec['task']=='capitu_conversations';split='multi' if multi else 'single'
    folder=root/'results/capitu/eval'/split
    rp=folder/'responses.jsonl';responses=unique(lines(rp),lambda r:r['key'])
    cp=folder/('eval_results_multiturn.jsonl' if multi else 'eval_results_strict.jsonl')
    scores=unique(lines(cp),lambda r:r['key'] if multi else r['prompt'])
    for qid,r in responses.items():
        if multi:
            score=scores[qid];question=r['turns'][0]['prompt'];final=r['turns'][-1]['response'];correct=score['all_instructions_followed']
            turns=[dict(turn=t['turn'],question=t['prompt'],final=t['response']) for t in r['turns']]
        else:
            question=r['prompt'];final=r['response'];score=scores[question];correct=score['follow_all_instructions'];turns=[]
        if r.get('model_context_failure'):correct=False
        yield common(spec,qid,question,'',None,final,100*correct,correction(score,note='Verificador determinístico CAPITU, com a correção de aspas da execução registrada.'),
                     'Conversa completa × 100' if multi else 'Prompt estrito × 100',dict(response_stream_sha256=sha(rp),scored_rows_sha256=sha(cp)),turns=turns)


def prosa(spec, root, base):
    inp=base/'runtime/sources/Prosa/Prosa-benchmark/prosa/data/prosa/question.jsonl'
    questions=unique(lines(inp),lambda r:r['conversation_hash'])
    p=root/'results/prosa_pt/scored_rows.json';scored=[]
    for row in read(p):
        if 'entry' in row:
            qid=str(row['id'])
            if row['entry'] is None and not row.get('model_context_exhausted') and not questions[qid]['question_excluded']:raise ValueError('Missing Prosa judgment entry')
            entry=dict(row['entry'] or {})
            if entry.get('conversation_hash',qid)!=qid:raise ValueError('Prosa scoring identity differs')
            entry.update(conversation_hash=qid,excluded=questions[qid]['question_excluded'],context_zero=bool(row.get('model_context_exhausted')));scored.append(entry)
        else:scored.append(row)
    scores=unique(scored,lambda r:r['conversation_hash'])
    if set(scores)!=set(questions):raise ValueError('Prosa input/score populations differ')
    for qid,q in questions.items():
        s=scores[qid];rp=base/'results/prosa_pt/responses'/(qid+'.json');r=read(rp)
        evaluations=s.get('evaluations',[]);indices=q['checklist_filtered_indices'];valid=[evaluations[i] for i in indices if i<len(evaluations) and evaluations[i] in ['YES','NO']]
        score=None if s['excluded'] or not valid else 100*sum(v=='YES' for v in valid)/len(valid)
        evidence=dict(response_file_sha256=sha(rp),scored_rows_sha256=sha(p));judge_text=None
        if s.get('context_zero'):score=0.0
        if not s['excluded'] and not s.get('context_zero'):
            jp=base/'results/prosa_pt/judge_raw'/qid/(str(s['judge_attempt'])+'.json')
            j=read(jp);judge_text=j['raw']['choices'][0]['message'].get('content');evidence['judgment_file_sha256']=sha(jp)
        verdict=correction(dict(evaluations=evaluations,checklist=q['checklist'],selected_indices=indices,excluded=s['excluded'],original_judgment=judge_text,context_zero=s.get('context_zero',False)),spec.get('judge'),
                           'O agregado usa todas as rubricas válidas, não a média das conversas. Exclusões fixas e veredictos ausentes permanecem identificados.')
        yield common(spec,qid,q['last_query'],q.get('history_text',''),None,r['content'] or '',score,verdict,'Rubricas válidas desta conversa × 100',evidence)


def export_one(spec, output):
    root=Path(spec['root']);base=root;task=spec['task']
    manifest=root/'run_manifest.json'
    if manifest.exists():
        m=read(manifest);base=Path(m.get('generation_source') or m.get('historical_generation_location') or root)
    if spec.get('generation_root'):base=Path(spec['generation_root'])
    adapters={**{t:replay for t in REPLAY},**{t:portuguese for t in PT},**{t:remaining for t in REMAINING},'bluex_v2':bluex,
              **{t:tool_cases for t in ['browsecomp_plus','marca_public','lumen_pt']},
              **{t:exams for t in ['enade_qa','enem_vl']},'capitu':capitu,'capitu_conversations':capitu,'prosa_pt':prosa}
    if task not in adapters:raise ValueError('No adapter: '+task)
    aggregate=root/'results_verified.json'
    if aggregate.exists():
        verified=read(aggregate);source_task=spec.get('source_task', 'capitu' if task=='capitu_conversations' else task)
        metric=verified['benchmarks'][source_task]
        if spec.get('score') is not None and task!='capitu_conversations' and not math.isclose(metric['score'],spec['score'],abs_tol=1e-9):raise ValueError('Source score differs from published aggregate')
        spec['_aggregate_sha256']=sha(aggregate)
    elif spec.get('legacy_scoring'):
        aggregate=Path(spec['legacy_scoring'])/'summary.json';verified=read(aggregate)
        if not math.isclose(verified['score'],spec['score'],abs_tol=1e-9):raise ValueError('Legacy score differs')
        spec['_aggregate_sha256']=sha(aggregate)
    else:raise ValueError('Missing verified aggregate')
    name=f"{task}--{spec['model_id']}--{spec['mode']}"+(spec.get('part',''))+'.jsonl.gz';path=output/name
    if path.exists():raise ValueError('Use a fresh export destination')
    n=0;ids=set()
    with gzip.open(path,'wt',encoding='utf8',compresslevel=3) as stream:
        for case in adapters[task](spec,root,base):
            identity=(case['case_id'],case['input_sha256'])
            if identity in ids:raise ValueError('Duplicate case')
            ids.add(identity);stream.write(json.dumps(case,ensure_ascii=False,separators=(',',':'))+'\n');n+=1
    if spec.get('expected_cases') is not None and n!=spec['expected_cases']:raise ValueError('Case count differs from pinned population')
    return dict(task=task,model_id=spec['model_id'],mode=spec['mode'],cases=n,file=name,sha256=sha(path),bytes=path.stat().st_size,model_calls=0)
