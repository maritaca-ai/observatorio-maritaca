"""Native HarmBench classifier and copyright metrics in their pinned CPU environment."""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from .auditing import OpenAI
from .remaining_core import claim_dispatch, definitions, digest, save


def classifier_client(url):
    return OpenAI(base_url=url, api_key=os.environ.get('S5_NANO_CLASSIFIER_API_KEY', ''),
                  timeout=1800, max_retries=0)


def prepare_transport(root, output):
    """Legacy classifier attempts cannot silently become new judge dispatches."""
    marker = output / 'classifier_transport.json'
    policy = dict(version=1, sdk_retries=0, exclusive_judgment_claims=True)
    if marker.exists():
        if json.loads(marker.read_text()) != policy:
            raise ValueError('HarmBench classifier transport identity changed')
        return True
    paths = {root / 'http_attempts.jsonl', output / 'classifier_audit/http_attempts.jsonl'}
    if os.environ.get('S5_NANO_AUDIT_DIR'):
        paths.add(Path(os.environ['S5_NANO_AUDIT_DIR']) / 'http_attempts.jsonl')
    for path in paths:
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip() and json.loads(line).get('model') == 'harmbench-classifier':
                    return False
    save(marker, policy)
    return True


def score_row(output, row, completion, tokenizer, native, classifier, params, allow_dispatch):
    identifier = row['BehaviorID']
    path = output / 'native_judgments' / (identifier + '.json')
    original_sha = __import__('hashlib').sha256(completion['generation'].encode()).hexdigest()
    if path.exists():
        record = json.loads(path.read_text())
        if record['original_final_sha256'] != original_sha:
            raise ValueError('HarmBench judgment generation changed')
        return record
    data = [dict(completion)]
    tokens = tokenizer.encode(data[0]['generation'], max_length=512, truncation=True)
    data[0]['generation'] = tokenizer.decode(tokens, skip_special_tokens=True)
    if 'hash_check' in row['Tags']:
        verdict = native.compute_results_hashing(row, data)
    else:
        if not allow_dispatch:
            raise RuntimeError('Legacy HarmBench classifier attempts require audit; no new dispatch')
        claim_dispatch(output, 'harm_judgment', digest(str(identifier)))
        verdict = native.compute_results_classifier(row, data, classifier, params)
    record = dict(id=identifier, original_final_sha256=original_sha, result=verdict,
                  clipped_tokens=len(tokens), label=verdict[0]['label'])
    save(path, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--classifier')
    parser.add_argument('--url')
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    import spacy
    from datasketch import MinHash
    nlp = spacy.load('en_core_web_sm')
    nlp.max_length = 10000000
    native = definitions(args.root / 'sources/eval_utils.py',
        ['tokenize', 'compute_hashes_with_sliding_window', 'check_output_with_sliding_window',
         'LLAMA2_CLS_PROMPT', 'compute_results_hashing', 'compute_results_classifier'],
        dict(nlp=nlp, MinHash=MinHash, tqdm=lambda rows: rows))
    behaviors = [json.loads(line) for line in (args.root / 'data/selected.jsonl').open()]
    os.chdir(args.root / 'inputs')
    if args.preflight:
        classifier = SimpleNamespace(generate=lambda prompts, params, **kw:
            [SimpleNamespace(outputs=[SimpleNamespace(text='no')]) for _ in prompts])
        for row in behaviors:
            data = [dict(generation='', test_case='Synthetic')]
            result = native.compute_results_hashing(row, data) if 'hash_check' in row['Tags'] else native.compute_results_classifier(row, data, classifier, None)
            assert result[0]['label'] == 0
        save(args.output / 'native_preflight.json', dict(passed=True, n=320, model_or_judge_calls=0))
        return
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.classifier, local_files_only=True)
    tokenizer.truncation_side = 'right'
    allow_dispatch = prepare_transport(args.root, args.output)
    client = classifier_client(args.url)
    completions = json.loads((args.output / 'native_completions.json').read_text())
    params = dict(temperature=0.0, max_tokens=1)
    class Classifier:
        def generate(self, prompts, ignored_params, **kwargs):
            result = client.completions.create(model='harmbench-classifier', prompt=prompts, **params)
            return [SimpleNamespace(outputs=[SimpleNamespace(text=choice.text)]) for choice in result.choices]
    classifier = Classifier()
    results = []
    for row in behaviors:
        identifier = row['BehaviorID']
        record = score_row(args.output, row, completions[identifier][0], tokenizer,
                           native, classifier, params, allow_dispatch)
        results.append(record)
    save(args.output / 'native_scored_rows.json', results)


if __name__ == '__main__':
    main()
