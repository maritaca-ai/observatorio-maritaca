from s5_nano.runtime_config import THINKING
'Freeze a complete benchmark only after auditing every saved final answer.'
import hashlib, json, time
from pathlib import Path
from bootstrap import save
from run_eval import load_existing
from score_results import extract_answer
R = Path(__file__).resolve().parent

def lines(path):
    with path.open() as f:
        return [json.loads(line) for line in f]

def verify(task):
    manifest = json.loads((R / 'manifest.json').read_text())
    items = [x for x in lines(R / 'data/items.jsonl') if x['task'] == task]
    dest = R / 'results' / task
    records_list = lines(dest / 'scored_rows.jsonl')
    records = {x['id']: x for x in records_list}
    metric = json.loads((dest / 'final.json').read_text())
    assert len(items) == len(records_list) == len(records) == manifest['counts'][task] == metric['n']
    assert set(records) == {x['id'] for x in items}
    native = None
    correct = empty = length = invalid = reasoning = 0
    for item in items:
        raw = load_existing(item)
        assert raw is not None
        choice = raw['response']['choices'][0]
        msg = choice['message']
        text = msg.get('content') or ''
        record = records[item['id']]
        assert record['response'] == text and record['prompt'] == item['prompt']
        assert record['gold'] == item['gold'] and record['group'] == item['group']
        assert record['empty'] == (not bool(text.strip()))
        assert record['finish_reason'] == choice['finish_reason']
        if native is not None:
            row = native[item['prompt']]
            original = inputs[item['prompt']]
            assert row['response'] == text and row['instruction_id_list'] == original['instruction_id_list']
            flags = row['follow_instruction_list']
            assert len(flags) == len(original['instruction_id_list']) and all((type(v) is bool for v in flags))
            assert type(row['follow_all_instructions']) is bool and row['follow_all_instructions'] == all(flags)
            correct += all(flags)
        else:
            prediction = extract_answer(task, text)
            assert record['prediction'] == prediction and record['correct'] == (prediction == item['gold'])
            correct += prediction == item['gold']
            invalid += prediction is None
        empty += not bool(text.strip())
        length += choice['finish_reason'] == 'length'
        reasoning += bool(msg.get('reasoning') or msg.get('reasoning_content'))
    assert correct == metric['correct'] and empty == metric['empty_finals'] and (length == metric['length_finishes'])
    assert metric['score'] == 100 * correct / len(items)
    if native is None:
        assert invalid == metric['invalid_extractions']
    proof = dict(thinking=THINKING, passed=True, time=time.time(), metric=metric, items_sha256=manifest['items_sha256'], scored_rows_sha256=hashlib.sha256((dest / 'scored_rows.jsonl').read_bytes()).hexdigest(), all_requests_checked=True, final_answers_only=True, thinking_responses=reasoning, lumi_reference=None, comparison_note=manifest['protocol']['comparison'])
    save(f'results/{task}/verified.json', proof)
    return proof
if __name__ == '__main__':
    import sys
    print(json.dumps(verify(sys.argv[1]), ensure_ascii=False))
