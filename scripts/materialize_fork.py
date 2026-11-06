"""Prepare a source fork and optional public inputs in ignored storage only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def safe_child(root, name):
    rel = Path(name)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Unsafe relative path')
    result = root / rel
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes destination')
    return result


def verify(path, spec):
    size = path.stat().st_size
    if spec.get('size') is not None and size != spec['size']:
        raise ValueError('Input size mismatch: ' + path.name)
    sha256 = hashlib.sha256()
    blob = hashlib.sha1(b'blob ' + str(size).encode() + b'\0')
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha256.update(chunk)
            blob.update(chunk)
    if spec.get('sha256') and sha256.hexdigest() != spec['sha256']:
        raise ValueError('SHA-256 mismatch: ' + path.name)
    if spec.get('git_blob_sha1') and blob.hexdigest() != spec['git_blob_sha1']:
        raise ValueError('Git blob mismatch: ' + path.name)


def copy_verified(source, target, spec):
    verify(source, spec)
    if target.exists():
        verify(target, spec)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.copying')
    with source.open('rb') as src, temp.open('xb') as dst:
        shutil.copyfileobj(src, dst)
    temp.chmod(0o600)
    temp.replace(target)
    return True


def fetch(target, spec):
    if target.exists():
        verify(target, spec)
        return False
    url = spec['url']
    if not url.startswith(('https://raw.githubusercontent.com/', 'https://huggingface.co/')):
        raise ValueError('Expected a pinned public source')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=target.name + '.', suffix='.download', dir=target.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, 'wb') as dst, urllib.request.urlopen(url, timeout=60) as src:
            shutil.copyfileobj(src, dst)
        verify(temp, spec)
        temp.chmod(0o600)
        temp.replace(target)
    except BaseException:
        if temp.exists():
            temp.unlink()
        raise
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--with-inputs', action='store_true')
    parser.add_argument('--input-cache', type=Path,
                        help='Reuse already downloaded original files, verified by the lock')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-z0-9_]+', args.benchmark):
        parser.error('Invalid benchmark identifier')
    matches = list((ROOT / 'benchmarks').glob('*/' + args.benchmark + '/upstream.lock.json'))
    if len(matches) != 1:
        parser.error('Unknown benchmark')
    lock_path = matches[0]
    lock = json.loads(lock_path.read_text())
    if lock.get('schema_version') != 2:
        parser.error('For an integrated benchmark, use s5-nano prepare and its documented adapter')
    target = (args.output or ROOT / '.runs/forks' / args.benchmark).resolve()
    ignored = [(ROOT / name).resolve() for name in ['.cache', '.runs']]
    if not any(target.is_relative_to(p) and target != p for p in ignored):
        parser.error('Output must be a subdirectory of this repository .cache/ or .runs/')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = {'benchmark': args.benchmark,
                'lock_sha256': hashlib.sha256(lock_path.read_bytes()).hexdigest()}
    identity_path = safe_child(target, 's5_nano_source_identity.json')
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError('Source lock changed: choose a new output directory')
    if not identity_path.exists():
        with identity_path.open('x') as stream:
            stream.write(json.dumps(identity, indent=2) + '\n')
    copied = 0
    for name, spec in lock['files'].items():
        copied += copy_verified(safe_child(lock_path.parent / 'fork', name),
                                safe_child(target, name), {'sha256': spec['sha256']})
    # Packaging metadata often references README.md; use our reviewed documentation.
    readme = lock_path.parent / 'README.md'
    readme_target = safe_child(target, 'README.md')
    if not readme_target.exists():
        shutil.copyfile(readme, readme_target)
    downloaded = reused = 0
    if args.with_inputs:
        for name, spec in lock['runtime_inputs'].items():
            destination = safe_child(target, name)
            cached = safe_child(args.input_cache, name) if args.input_cache else None
            if destination.exists():
                verify(destination, spec)
                reused += 1
            elif cached and cached.exists():
                copy_verified(cached, destination, spec)
                reused += 1
            else:
                downloaded += fetch(destination, spec)
    print(json.dumps({'benchmark': args.benchmark, 'source_files_copied': copied,
                      'inputs_reused': reused, 'inputs_downloaded': downloaded,
                      'output': str(target.relative_to(ROOT.resolve())),
                      'model_or_judge_calls': 0, 'execution_started': False}))


if __name__ == '__main__':
    main()
