"""Download pinned public model assets into private, caller-owned storage."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


def prepare_model(model_id, spec, output):
    from huggingface_hub import snapshot_download
    target = output / model_id
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot_download(spec['model'], revision=spec['revision'], token=False,
                      local_dir=target, max_workers=4,
                      allow_patterns=['*.safetensors', '*.json', '*.jinja', '*.model', '*.py', '*.txt', 'LICENSE*'])
    files = {}
    for path in sorted(target.rglob('*')):
        if not path.is_file() or '.cache' in path.relative_to(target).parts:
            continue
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            while block := handle.read(8 * 1024 * 1024):
                digest.update(block)
        files[str(path.relative_to(target))] = dict(sha256=digest.hexdigest(), bytes=path.stat().st_size)
    for name, expected in spec['files'].items():
        if name == 'README.md':
            continue
        if files.get(name, {}).get('sha256') != expected:
            raise ValueError('Model metadata differs from pinned sources: '+model_id+'/'+name)
    receipt = dict(model=spec['model'], revision=spec['revision'], files=files,
                   prepared_at=datetime.now(timezone.utc).isoformat(), inference_calls=0)
    path = output / (model_id + '.manifest.json')
    path.write_text(json.dumps(receipt, indent=2) + '\n')
    path.chmod(0o600)
    return dict(model_id=model_id, status='PREPARED', files=len(files),
                bytes=sum(x['bytes'] for x in files.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--models', nargs='+', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.output.is_symlink() or args.output.stat().st_uid != os.getuid():
        raise ValueError('Use owned model storage')
    specs = json.loads(args.lock.read_text())['models']
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(lambda name: prepare_model(name, specs[name], args.output), args.models):
            print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
