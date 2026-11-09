"""Offline protocol, dataset pinning, immutable inputs, and DRACO scoring."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = Path.home() / '.cache/observatorio-maritaca/draco/test.jsonl'
DEFAULT_JUDGE_MODEL = 'S5'
DEFAULT_JUDGE_EFFORT = 'xhigh'
DEFAULT_JUDGE_PROVIDER = 'maritaca'
JUDGE_SYSTEM = (Path(__file__).parent / 'judge_system.txt').read_text().strip()
GENERATOR_SYSTEM = (Path(__file__).parent / 'generator_system.txt').read_text().strip()


def digest(value):
    if isinstance(value, str):
        value = value.encode()
    elif not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def freeze(path, value):
    """Never mix inputs/configurations when resuming an existing run."""
    if path.exists():
        if read_json(path) != value:
            raise ValueError(f'Inputs changed: {path}. Use a new run ID or judge label.')
    else:
        write_json(path, value)


def safe_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
        raise ValueError('IDs must contain only letters, digits, underscore, dot or hyphen')
    return value


def criteria(case):
    rubric = json.loads(case['answer']) if isinstance(case['answer'], str) else case['answer']
    return [dict(c, section=s['id']) for s in rubric['sections'] for c in s['criteria']]


def validate_cases(cases):
    seen = set()
    for case in cases:
        safe_name(case['id'])
        if case['id'] in seen:
            raise ValueError('Duplicate task ID')
        seen.add(case['id'])
        if not isinstance(case['problem'], str) or not case['problem'].strip() or not isinstance(case['domain'], str):
            raise ValueError('Missing query or domain')
        items = criteria(case)
        ids = [(c['section'], c['id']) for c in items]
        if not items or len(ids) != len(set(ids)):
            raise ValueError('Empty rubric or duplicate criterion')
        for c in items:
            if not isinstance(c['weight'], int) or isinstance(c['weight'], bool) or c['weight'] == 0:
                raise ValueError('Criterion weights must be nonzero integers')
            if not isinstance(c['requirement'], str) or not c['requirement'].strip():
                raise ValueError('Missing criterion requirement')
        if sum(c['weight'] for c in items if c['weight'] > 0) <= 0:
            raise ValueError('Rubric has no positive denominator')
    if not cases:
        raise ValueError('Empty dataset')
    return cases


def load_dataset(path=DEFAULT_CACHE):
    manifest = read_json(ROOT / 'dataset_manifest.json')
    if digest(JUDGE_SYSTEM) != manifest['judge_system_sha256']:
        raise ValueError('Judge prompt checksum differs from the protocol manifest')
    path = Path(path)
    if not path.exists():
        with urlopen(manifest['url'], timeout=90) as response:
            payload = response.read()
        if digest(payload) != manifest['sha256']:
            raise ValueError('Downloaded DRACO checksum does not match the pinned manifest')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    payload = path.read_bytes()
    if digest(payload) != manifest['sha256']:
        raise ValueError('DRACO checksum mismatch; no API calls made')
    cases = validate_cases([json.loads(line) for line in payload.splitlines() if line.strip()])
    if len(cases) != manifest['tasks'] or sum(len(criteria(c)) for c in cases) != manifest['criteria']:
        raise ValueError('Dataset counts differ from manifest')
    return cases, manifest


def select_cases(cases, selection='full', seed='draco-per-domain-v1:'):
    if selection == 'full':
        return sorted(cases, key=lambda c: c['id'])
    groups = defaultdict(list)
    for case in cases:
        groups[case['domain']].append(case)
    return [min(groups[d], key=lambda c: digest(seed + c['id'])) for d in sorted(groups)]


def judge_messages(case, text, criterion):
    kind = 'positive' if criterion['weight'] > 0 else 'negative'
    user = (f'<criterion_type>\n{kind}\n</criterion_type>\n'
            f'<criterion>\n{criterion["requirement"]}\n</criterion>\n'
            f'{case["problem"]}\n<response>\n{text}\n</response>')
    return [{'role': 'system', 'content': JUDGE_SYSTEM}, {'role': 'user', 'content': user}]


def parse_grade(text):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    value = json.loads(text)
    if not isinstance(value, dict) or value.get('criterion_status') not in ('MET', 'UNMET'):
        raise ValueError('Judge must return criterion_status MET or UNMET')
    if not isinstance(value.get('explanation'), str) or not value['explanation'].strip():
        raise ValueError('Judge must return a nonempty explanation')
    return {k: value[k] for k in ('criterion_status', 'explanation')}


def score(items, grades):
    if len(items) != len(grades) or not items:
        raise ValueError('Incomplete rubric judgments')
    if any(g not in ('MET', 'UNMET') for g in grades):
        raise ValueError('Invalid criterion status')
    positive = sum(c['weight'] for c in items if c['weight'] > 0)
    if positive <= 0:
        raise ValueError('Rubric has no positive denominator')
    raw = sum(c['weight'] for c, g in zip(items, grades) if g == 'MET')
    return {'raw_score': raw, 'positive_weight_sum': positive,
            'score': 100 * max(0, min(1, raw / positive))}


def report_id(case_id, generator):
    # Generator labels may contain provider/model slashes; never use them as paths.
    return safe_name(case_id) + '_' + digest(generator)[:16]


def store_report(run_dir, case_id, generator, text, **metadata):
    if not isinstance(generator, str) or not generator or not isinstance(text, str):
        raise ValueError('A report needs generator and text strings')
    rid = report_id(case_id, generator)
    record = dict(metadata, report_id=rid, case_id=case_id, generator=generator,
                  text=text, text_sha256=digest(text))
    path = run_dir/'answers'/f'{rid}.json'
    freeze(path, record)
    return record


def reports(run_dir, cases):
    case_ids = {c['id'] for c in cases}
    rows = [read_json(p) for p in sorted((run_dir/'answers').glob('*.json'))]
    for row in rows:
        if row['case_id'] not in case_ids or row['text_sha256'] != digest(row['text']):
            raise ValueError('Report dataset or text hash mismatch')
        if row['report_id'] != report_id(row['case_id'], row['generator']):
            raise ValueError('Report ID mismatch')
    return rows


def checked_grade(path, case, report, index, config):
    row = read_json(path)
    item = criteria(case)[index]
    messages_hash = digest(judge_messages(case, report['text'], item))
    expected = {'report_id': report['report_id'], 'report_sha256': report['text_sha256'],
                'criterion_index': index, 'criterion': item, 'config_sha256': digest(config),
                'messages_sha256': messages_hash}
    if any(row.get(k) != v for k, v in expected.items()):
        raise ValueError(f'Stale or mismatched judgment: {path}')
    parse_grade(json.dumps(row))
    return row


def summarize(run_dir, cases, judge_label):
    folder = run_dir/'judgments'/safe_name(judge_label)
    config = read_json(folder/'config.json')
    rows = reports(run_dir, cases)
    case_map = {c['id']: c for c in cases}
    scored, missing, pairs = [], [], []
    for row in rows:
        case = case_map[row['case_id']]
        grades = []
        for index, criterion in enumerate(criteria(case)):
            path = folder/row['report_id']/f'{index:03d}.json'
            if not path.exists():
                missing.append({'report_id': row['report_id'], 'criterion_index': index})
                continue
            grade = checked_grade(path, case, row, index, config)
            grades.append(grade['criterion_status'])
            pairs.append(dict(report_id=row['report_id'], case_id=case['id'], generator=row['generator'],
                              criterion_index=index, criterion=criterion, **parse_grade(json.dumps(grade))))
        if len(grades) == len(criteria(case)):
            scored.append(dict(report_id=row['report_id'], case_id=case['id'], domain=case['domain'],
                               generator=row['generator'], text_sha256=row['text_sha256'],
                               flags=row.get('flags', []), **score(criteria(case), grades)))
    by_generator = {}
    expected_cases = {c['id'] for c in cases}
    for generator in sorted({r['generator'] for r in rows}):
        sub = [r for r in scored if r['generator'] == generator]
        complete = {r['case_id'] for r in sub} == expected_cases
        by_generator[generator] = {'n_scored': len(sub), 'n_expected': len(cases), 'complete': complete,
            'mean_score': sum(r['score'] for r in sub)/len(sub) if complete else None,
            'partial_mean_score': sum(r['score'] for r in sub)/len(sub) if sub else None,
            'by_domain': {domain: {'n': len([r for r in sub if r['domain'] == domain]),
                'mean_score': sum(r['score'] for r in sub if r['domain'] == domain)/len([r for r in sub if r['domain'] == domain])}
                for domain in sorted({r['domain'] for r in sub})}}
    complete = bool(rows) and not missing and all(x['complete'] for x in by_generator.values())
    summary = {'judge': judge_label, 'config': config, 'complete': complete,
               'n_reports': len(rows), 'n_judgments': len(pairs), 'missing': missing,
               'by_generator': by_generator, 'reports': scored, 'pairs': pairs,
               'generation_configs': [read_json(p) for p in sorted((run_dir/'generation_configs').glob('*.json'))],
               'imported': (run_dir/'import_manifest.json').exists()}
    write_json(folder/'summary.json', summary)
    return summary
