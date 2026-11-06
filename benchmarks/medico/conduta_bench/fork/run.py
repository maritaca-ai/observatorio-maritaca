#!/usr/bin/env python3
"""Generate closed-book answers and optionally judge them; no manual JSONL required."""
import argparse
import json
import os
from pathlib import Path
import sys
import evaluate
import providers


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider',choices=tuple(providers.PROVIDERS),required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,help='Use the first N questions in dataset order (a pilot, not random sampling).')
    parser.add_argument('--max-tokens',type=int,default=16000)
    parser.add_argument('--temperature',type=float)
    parser.add_argument('--reasoning-effort')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--evaluate',action='store_true',help='Judge generated answers when generation finishes.')
    parser.add_argument('--judge-provider',choices=tuple(providers.PROVIDERS),default='maritaca')
    parser.add_argument('--judge-model')
    parser.add_argument('--judge-max-tokens',type=int,default=8000)
    parser.add_argument('--judge-temperature',type=float)
    parser.add_argument('--judge-reasoning-effort')
    args=parser.parse_args(argv)
    questions=evaluate.read_rows(evaluate.ROOT/'data/questions.jsonl')
    if args.limit is not None:
        if not 1 <= args.limit <= len(questions):
            raise evaluate.EvaluationError('--limit must be between 1 and the dataset size.')
        questions=dict(list(questions.items())[:args.limit])
    specs={}
    for qid,q in questions.items():
        # Intentionally reads only questions: no rubric, answer key, or support file.
        messages=[dict(role='user',content=f"{q['scenario']}\n\n{q['question']}")]
        specs[qid]=providers.prepare(args.provider,args.model,messages,args.max_tokens,args.temperature,args.reasoning_effort)
    judge_model=args.judge_model or ('sabia-4-thinking' if args.judge_provider=='maritaca' else None)
    if args.evaluate:
        providers.prepare(args.judge_provider,judge_model,[],args.judge_max_tokens,args.judge_temperature,args.judge_reasoning_effort)
    if args.dry_run:
        print(json.dumps(dict(questions=len(questions),provider=args.provider,model=args.model,
                             judge_provider=args.judge_provider if args.evaluate else None,api_calls=0)))
        return
    out=args.output.resolve()
    if out==evaluate.ROOT or any(out==evaluate.ROOT/x or evaluate.ROOT/x in out.parents for x in ('data','tests')):
        raise evaluate.EvaluationError('Choose a separate output directory.')
    out.mkdir(parents=True,exist_ok=True)
    path=out/'predictions.jsonl'
    cached=evaluate.read_rows(path) if path.exists() and path.stat().st_size else {}
    for qid,row in cached.items():
        if qid not in specs or row.get('request_sha256')!=evaluate.fingerprint(specs[qid]):
            raise evaluate.EvaluationError('Generation cache does not match these inputs/settings; choose a fresh output directory.')
        if not isinstance(row.get('answer'),str) or not row['answer'].strip():
            raise evaluate.EvaluationError('Invalid cached answer.')
    key=providers.api_key(args.provider) if set(specs)-set(cached) else ''
    # Catch missing judge credentials before paying for generation.
    if args.evaluate:
        providers.api_key(args.judge_provider)
    for qid,spec in specs.items():
        if qid in cached:
            continue
        result=providers.send(spec,key)
        row=dict(id=qid,answer=result['text'],provider=args.provider,model=args.model,
                 returned_model=result['model'],usage=result['usage'],request_sha256=evaluate.fingerprint(spec))
        with path.open('a',encoding='utf-8') as file:
            file.write(json.dumps(row,ensure_ascii=False)+'\n');file.flush();os.fsync(file.fileno())
        print(f'Saved {qid}',flush=True)
    (out/'generation.json').write_text(json.dumps(dict(provider=args.provider,model=args.model,
        condition='closed-book',questions=len(specs),max_tokens=args.max_tokens,temperature=args.temperature,
        reasoning_effort=args.reasoning_effort),indent=2)+'\n')
    if args.evaluate:
        flags=['--predictions',str(path),'--output',str(out/'evaluation'),
               '--judge-provider',args.judge_provider,'--judge-model',judge_model,
               '--judge-max-tokens',str(args.judge_max_tokens)]
        if args.limit:flags+=['--allow-subset']
        if args.judge_temperature is not None:flags+=['--judge-temperature',str(args.judge_temperature)]
        if args.judge_reasoning_effort:flags+=['--judge-reasoning-effort',args.judge_reasoning_effort]
        evaluate.main(flags)

if __name__=='__main__':
    try:
        main()
    except (evaluate.EvaluationError,providers.APIError) as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
    except (ValueError,KeyError,IndexError,TypeError,OSError):
        print('Run failed. Check input files and output permissions; completed calls remain cached.',file=sys.stderr)
        sys.exit(1)
