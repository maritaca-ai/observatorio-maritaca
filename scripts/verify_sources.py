"""Verify pinned forks, explicit profiles and the complete execution matrix offline."""
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from s5_nano.runtime_config import read_profile
from s5_nano.remaining_inputs import read_plan


def read(path):
    return json.loads(path.read_text())


def main():
    catalog = read(ROOT/'benchmarks/catalog.json')
    inventory = read(ROOT/'benchmarks/forks.json')
    if set(catalog) != set(inventory):
        raise ValueError('Fork catalog differs from execution catalog')
    count = 0
    for benchmark, entry in inventory.items():
        directory = ROOT/entry['directory']
        if hashlib.sha256((directory/'upstream.lock.json').read_bytes()).hexdigest() != entry['source_lock_sha256']:
            raise ValueError('Source lock changed: ' + benchmark)
        actual = {str(p.relative_to(directory/'fork')) for p in (directory/'fork').rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts}
        if actual != set(entry['files']):
            raise ValueError('Fork inventory changed: ' + benchmark)
        for name, expected in entry['files'].items():
            path = directory/'fork'/name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Fork source changed: ' + str(path))
            if path.suffix == '.py':
                ast.parse(path.read_bytes(), filename=str(path))
            count += 1
        if catalog[benchmark]['family'] == 'remaining':
            plan = read_plan(benchmark)
            spec = plan['benchmarks'][benchmark]
            if spec['upstream_lock_sha256'] != entry['source_lock_sha256']:
                raise ValueError('Selection uses another source lock: ' + benchmark)
            if spec['selection']['selected_rows'] != sum(catalog[benchmark]['expected_counts']):
                raise ValueError('Selection size changed: ' + benchmark)
    plan = read(ROOT/'profiles/plan.json')
    models = read(ROOT/'results/modelos.json')
    outputs = []
    for job in plan:
        if job['model'] not in models or job['mode'] not in models[job['model']]['modos_avaliados']:
            raise ValueError('Unexpected model or mode')
        profile = read_profile(ROOT/job['profile'])
        if profile['mode'] != job['mode'] or profile['enable_thinking'] != (job['mode'] == 'thinking'):
            raise ValueError('Profile mode mismatch')
        if not profile.get('chat_template_sha256') or not profile.get('references'):
            raise ValueError('Profile lacks template identity or references')
        if job['benchmark'] not in catalog:
            raise ValueError('Benchmark outside source catalog')
        outputs.extend(f'{job["model"]}/{b}/{job["mode"]}' for b in job['outputs'])
    expected = set(read(ROOT/'verifier/reported.json')['notas'])
    if len(outputs) != len(set(outputs)) or set(outputs) != expected:
        raise ValueError('Execution matrix does not cover each reported group exactly once')
    for entry in read(ROOT/'profiles/templates/index.json'):
        if hashlib.sha256((ROOT/entry['arquivo']).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Recorded template changed')
        for profile in entry['perfis']:
            if read(ROOT/profile)['chat_template_sha256'] != entry['sha256']:
                raise ValueError('Template/profile mismatch')
    # Include literal subprocess module names; import-only scans miss these.
    modules = {'.'.join(p.relative_to(ROOT/'src').with_suffix('').parts)
               for p in (ROOT/'src/s5_nano').rglob('*.py')}
    modules |= {m.removesuffix('.__init__') for m in modules if m.endswith('.__init__')}
    for path in (ROOT/'src/s5_nano').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_bytes())):
            names = []
            if isinstance(node, ast.ImportFrom):
                name = node.module or ''
                if node.level:
                    parent = list(path.relative_to(ROOT/'src').parent.parts)
                    name = '.'.join(parent[:len(parent)-node.level+1] + ([name] if name else []))
                names = [name]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith('s5_nano.') and ' ' not in node.value:
                names = [node.value]
            for name in names:
                if name.startswith('s5_nano.') and name not in modules:
                    raise ValueError('Missing runtime module: ' + name)
    print(json.dumps({'forks': len(inventory), 'arquivos_fonte': count,
                      'execucoes': len(plan), 'conjuntos': len(outputs), 'chamadas': 0}))


if __name__ == '__main__':
    main()
