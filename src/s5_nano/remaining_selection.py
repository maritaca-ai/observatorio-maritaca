"""Deterministic public selections shared by execution and offline verification."""
import hashlib
import json
import csv
import io
import zipfile
from collections import defaultdict

def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_bytes(path, digest):
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == digest, f"Source hash changed: {path.name}")
    return data


def read_rows(path, item):
    """Decode pinned public containers without changing their row order."""
    if path.suffix == '.parquet':
        import pyarrow.parquet as pq
        rows = pq.read_table(path).to_pylist()
    elif path.suffix == '.json':
        rows = json.loads(path.read_text())
    elif path.suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            # The authors publish this dataset passphrase in their README.
            content = archive.read(item['member'], pwd=item['public_zip_passphrase'].encode())
        require(hashlib.sha256(content).hexdigest() == item['member_sha256'], 'ZIP member changed')
        rows = list(csv.DictReader(io.StringIO(content.decode('utf-8'))))
    else:
        with path.open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream) if path.suffix == '.csv' else
                        (json.loads(line) for line in stream if line.strip()))
    if 'modality' in item:
        for index, row in enumerate(rows):
            row['_modality'] = item['modality']
            # Native SOB IDs repeat; preserve every source row and its position.
            row['_selection_id'] = f"{item['modality']}:{index}:{row['record_id']}"
    return rows


def select(rows, spec, benchmark, seed):
    require(len(rows) == spec['population_rows'], 'Population count changed')
    ids = [str(row[spec['id_field']]) for row in rows]
    require(len(set(ids)) == len(ids), 'Duplicate source IDs')
    method = spec['method']
    if method == 'prefix_filter':
        rows = [r for r in rows if str(r[spec['field']]).split(spec['separator'])[0] in spec['values']]
    elif method == 'field_filter':
        rows = [r for r in rows if r[spec['field']] in spec['values']]
    elif method == 'stratified_sha256':
        groups = defaultdict(list)
        for row in rows:
            groups[row[spec['field']]].append(row)
        n, total = spec['selected_rows'], len(rows)
        quotas = {g: n * len(v) // total for g, v in groups.items()}
        remainder_order = sorted(groups, key=lambda g: (-(n * len(groups[g]) % total), g))
        for group in remainder_order[:n - sum(quotas.values())]:
            quotas[group] += 1
        require(quotas == spec['quotas'], 'Stratification quotas changed')
        rows = [r for group in sorted(groups) for r in sorted(
            groups[group], key=lambda r: hashlib.sha256(
                f"{seed}:{benchmark}:{r[spec['id_field']]}".encode()).digest())[:quotas[group]]]
    else:
        require(method == 'all', 'Unknown selection method')
    ids = sorted(str(r[spec['id_field']]) for r in rows)
    digest = hashlib.sha256(json.dumps(ids, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    require(len(rows) == spec['selected_rows'], 'Selected count changed')
    require(digest == spec['selected_ids_sha256'], 'Selected IDs changed')
    return rows
