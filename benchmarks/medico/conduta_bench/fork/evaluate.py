#!/usr/bin/env python3
"""Standalone CondutaBench evaluator (Python 3.10+, standard library only)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import providers

ROOT = Path(__file__).resolve().parent


class EvaluationError(ValueError):
    """A safe, user-facing validation or API error."""


def read_rows(path):
    records = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            raise EvaluationError('Each JSONL record needs a string id.')
        if row['id'] in records:
            raise EvaluationError('Duplicate record id.')
        records[row['id']] = row
    if not records:
        raise EvaluationError('Empty input file.')
    return records


def validate_hits(hits, size):
    if not isinstance(hits, dict) or set(hits) != {str(i) for i in range(size)}:
        raise EvaluationError('Judgment must cover every criterion exactly once (zero-based string keys).')
    if any(type(value) is not bool for value in hits.values()):
        raise EvaluationError('Judgment values must be JSON booleans.')
    return hits


def score(criteria, hits):
    validate_hits(hits, len(criteria))
    positive = [i for i,c in enumerate(criteria) if c['weight'] > 0]
    triggered = [i for i,c in enumerate(criteria) if c['weight'] < 0 and hits[str(i)]]
    maximum = sum(criteria[i]['weight'] for i in positive)
    if maximum <= 0:
        raise EvaluationError('Rubric must contain positive weight.')
    return dict(
        score=100*sum(c['weight'] for i,c in enumerate(criteria) if hits[str(i)])/maximum,
        correct=all(hits[str(i)] for i,c in enumerate(criteria) if c['type']=='essencial') and not triggered,
        complete=all(hits[str(i)] for i in positive) and not triggered,
        negative=bool(triggered),
        harm=any(criteria[i]['impact']=='pode_piorar' for i in triggered),
    )


def request(question, rubric, answer, model):
    criteria = '\n'.join(
        f'{i}. [{c["type"]} {c["weight"]:+d}] {c["text"]}'
        for i,c in enumerate(rubric['criteria'])
    )
    prompt = (
        'Voce e um avaliador medico rigoroso. Avalie a RESPOSTA DO MODELO contra a RUBRICA '
        'de uma questao de conduta clinica.\n\n'
        f'PERGUNTA:\n{question["scenario"]}\n{question["question"]}\n\n'
        f'GABARITO (conduta correta):\n{rubric["reference_answer"]}\n\n'
        f'RUBRICA (criterios):\n{criteria}\n\n'
        "Para CADA criterio diga se foi 'atingido' pela resposta do modelo. Para criterios "
        'negativos (erro_grave/acao_proibida), atingido=true significa que a resposta COMETEU '
        'aquele erro. Seja literal: so marque um criterio positivo como atingido se a resposta '
        'realmente o satisfaz.\n\n'
        f'RESPOSTA DO MODELO:\n<resposta>\n{answer}\n</resposta>\n\n'
        'Responda APENAS com JSON: {"criterios":[{"i":0,"atingido":true,'
        '"evidencia":"..."}],"comentario":"..."}'
    )
    return dict(model=model, messages=[dict(role='user',content=prompt)],temperature=0,max_tokens=8000,service_tier='auto')


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def parse_judgment(content, size):
    text = content.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n',1)[1].rsplit('```',1)[0].strip()
    data = json.loads(text)
    if not isinstance(data,dict) or not isinstance(data.get('criterios'),list):
        raise EvaluationError('Invalid judge response.')
    hits = {}
    for c in data['criterios']:
        if not isinstance(c,dict) or type(c.get('i')) is not int or str(c['i']) in hits:
            raise EvaluationError('Invalid or duplicate criterion index.')
        hits[str(c['i'])] = c.get('atingido')
    return validate_hits(hits,size)


def call_judge(payload, key):
    return providers.send(payload,key)['text']


def summarize(records):
    def aggregate(rows):
        return dict(n=len(rows), **{k:sum(r['metrics'][k] for r in rows)/len(rows)*(1 if k=='score' else 100)
                                   for k in ('score','correct','complete','negative','harm')})
    return dict(overall=aggregate(records),by_guideline={g:aggregate([r for r in records if r['guideline_id']==g])
                                                       for g in sorted({r['guideline_id'] for r in records})})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--predictions',type=Path,help='JSONL: {"id":"anf001","answer":"..."}')
    mode.add_argument('--judgments',type=Path,help='Offline JSONL: {"id":"anf001","hits":{"0":true,...}}')
    parser.add_argument('--output',type=Path,required=True,help='Local output directory; do not publish evaluation outputs.')
    parser.add_argument('--allow-subset',action='store_true',help='Explicitly allow incomplete coverage of the benchmark.')
    parser.add_argument('--dry-run',action='store_true',help='Validate input without API calls or writes.')
    parser.add_argument('--judge-provider',choices=tuple(providers.PROVIDERS),default='maritaca')
    parser.add_argument('--judge-model')
    parser.add_argument('--judge-max-tokens',type=int,default=8000)
    parser.add_argument('--judge-temperature',type=float)
    parser.add_argument('--judge-reasoning-effort')
    args=parser.parse_args(argv)
    if not args.judge_model:
        if args.judge_provider!='maritaca' and args.predictions:
            raise EvaluationError('--judge-model is required for non-Maritaca providers.')
        args.judge_model='sabia-4-thinking'
    if args.judge_temperature is None and args.judge_provider=='maritaca':
        args.judge_temperature=0
    if args.predictions:
        providers.prepare(args.judge_provider,args.judge_model,[],args.judge_max_tokens,args.judge_temperature,args.judge_reasoning_effort)
    questions=read_rows(ROOT/'data/questions.jsonl')
    rubrics=read_rows(ROOT/'data/rubrics.jsonl')
    expected=set(questions)
    inputs=read_rows(args.predictions or args.judgments)
    if not set(inputs)<=expected or (set(inputs)!=expected and not args.allow_subset):
        raise EvaluationError('Input IDs do not match the benchmark; use --allow-subset for an intentional partial evaluation.')
    for qid,row in inputs.items():
        if args.predictions:
            if not isinstance(row.get('answer'),str):
                raise EvaluationError('Every prediction needs a string answer (empty answers are allowed).')
        else:
            validate_hits(row.get('hits'),len(rubrics[qid]['criteria']))
    if args.dry_run:
        print(json.dumps(dict(valid=True,questions=len(inputs),expected=len(expected),api_calls=0)))
        return
    # Refuse accidental overwrites of bundled source/data or caller inputs.
    output=args.output.resolve()
    if output == ROOT or any(output == (ROOT/x) or (ROOT/x) in output.parents for x in ('data','guidelines','tests')):
        raise EvaluationError('Choose a separate output directory.')
    for name in ('judgments.jsonl','scores.jsonl','summary.json'):
        if (output/name).resolve() == (args.predictions or args.judgments).resolve():
            raise EvaluationError('Output would overwrite the input file.')
    args.output.mkdir(parents=True,exist_ok=True)
    cache_path=args.output/'judgments.jsonl'
    cache=read_rows(cache_path) if cache_path.exists() and cache_path.stat().st_size else {}
    payloads={qid:providers.prepare(args.judge_provider,args.judge_model,
              request(questions[qid],rubrics[qid],row['answer'],args.judge_model)['messages'],
              args.judge_max_tokens,args.judge_temperature,args.judge_reasoning_effort)
              for qid,row in inputs.items()} if args.predictions else {}
    # Validate all cache fingerprints before making any paid request.
    for qid,cached in cache.items():
        if qid not in payloads or cached.get('request_sha256')!=fingerprint(payloads[qid]):
            if args.predictions:
                raise EvaluationError('Stale or incompatible cache; choose a fresh output directory.')
        if args.predictions:
            validate_hits(cached.get('hits'),len(rubrics[qid]['criteria']))
    key=providers.api_key(args.judge_provider) if args.predictions and set(inputs)-set(cache) else ''
    records=[]
    for qid,row in inputs.items():
        if args.judgments:
            hits=row['hits']
        elif qid in cache:
            hits=cache[qid]['hits']
        else:
            payload=payloads[qid]
            hits=parse_judgment(call_judge(payload,key),len(rubrics[qid]['criteria']))
            cached=dict(id=qid,hits=hits,judge_model=args.judge_model,judge_provider=args.judge_provider,request_sha256=fingerprint(payload))
            with cache_path.open('a',encoding='utf-8') as file:
                file.write(json.dumps(cached,ensure_ascii=False)+'\n')
                file.flush()
                os.fsync(file.fileno())
        records.append(dict(id=qid,guideline_id=questions[qid]['guideline_id'],metrics=score(rubrics[qid]['criteria'],hits)))
    summary=summarize(records)
    summary.update(expected_questions=len(expected),coverage_pct=100*len(inputs)/len(expected),
                   judgment_source='provided' if args.judgments else args.judge_model,
                   judge_provider=None if args.judgments else args.judge_provider,
                   judge_settings=None if args.judgments else dict(max_tokens=args.judge_max_tokens,
                       temperature=args.judge_temperature,reasoning_effort=args.judge_reasoning_effort))
    (args.output/'scores.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary['overall'],indent=2))


if __name__=='__main__':
    try:
        main()
    except (EvaluationError,providers.APIError) as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
    except (ValueError,KeyError,IndexError,TypeError,OSError):
        # Avoid dumping remote payloads, private responses, or credentials in tracebacks.
        print('Evaluation failed. Check input coverage/schema, cache compatibility, API key and connectivity. Successful judgments remain cached.',file=sys.stderr)
        sys.exit(1)
