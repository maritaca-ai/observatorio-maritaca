"""Score final answers only; preserve complete denominators and source provenance."""
import fcntl, gzip, hashlib, json, os, re, subprocess, sys, time
from collections import defaultdict
from pathlib import Path
from bootstrap import save
R = Path(__file__).resolve().parent
from s5_nano.answers import extract_answer

def score():
    from run_eval import load_existing
    manifest = json.loads((R / 'manifest.json').read_text())
    with (R / 'data/items.jsonl').open() as f:
        items = [json.loads(l) for l in f]
    groups = defaultdict(list)
    for item in items:
        groups[item['task']].append(item)
    result = {'model': os.environ['S5_NANO_MODEL'], 'checkpoint': None, 'time': time.time(), 'benchmarks': {}, 'lumi_reference': manifest.get('lumi_reference', {}), 'protocol': manifest['protocol']}
    for task, rows in groups.items():
        cached = R / 'results' / task / 'verified.json'
        if cached.exists():
            proof = json.loads(cached.read_text())
            assert proof['passed'] and proof['items_sha256'] == manifest['items_sha256']
            assert proof['metric']['source'] == manifest['datasets'][task]
            result['benchmarks'][task] = proof['metric']
            continue
        records = []
        missing = []
        for item in rows:
            response = load_existing(item)
            if response is None:
                missing.append(item['id'])
                continue
            msg = response['response']['choices'][0]['message']
            text = msg.get('content') or ''
            prediction = extract_answer(task, text)
            records.append(dict(id=item['id'], prompt=item['prompt'], response=text, gold=item['gold'], prediction=prediction, correct=prediction == item['gold'], group=item['group'], empty=not bool(text.strip()), finish_reason=response['response']['choices'][0]['finish_reason']))
        if missing:
            result['benchmarks'][task] = dict(status='INCOMPLETE', completed=len(records), expected=len(rows))
            continue
        dest = R / 'results' / task
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'scored_rows.jsonl').write_text(''.join((json.dumps(x, ensure_ascii=False) + '\n' for x in records)))
        correct = sum((x['correct'] for x in records))
        invalid = sum((x['prediction'] is None for x in records))
        result['benchmarks'][task] = dict(status='FINAL', correct=correct, n=len(records), score=100 * correct / len(records), protocol_id=manifest['evaluation_protocol']['protocol_id'], invalid_extractions=invalid, empty_finals=sum((x['empty'] for x in records)), length_finishes=sum((x['finish_reason'] == 'length' for x in records)), source=manifest['datasets'][task], fewshot=rows[0]['fewshot'])
        save(f'results/{task}/final.json', result['benchmarks'][task])
        from verify_milestone import verify
        verify(task)
    if all((x['status'] == 'FINAL' for x in result['benchmarks'].values())):
        result['overall'] = sum((x['score'] for x in result['benchmarks'].values())) / len(result['benchmarks'])
        result['status'] = 'FINAL'
    else:
        result['status'] = 'INCOMPLETE'
    save('results.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('protocol', 'lumi_reference')}, ensure_ascii=False))

def main():
    with (R / 'scoring.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        score()
if __name__ == '__main__':
    main()
