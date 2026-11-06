"""Execute the explicit model/mode/benchmark matrix and export final results."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .prepare import REPO


def read(path):
    return json.loads(path.read_text())


def select_jobs(models=None, modes=None, benchmarks=None):
    plan = read(REPO/'profiles/plan.json')
    for field, selected in [('model', models), ('mode', modes), ('benchmark', benchmarks)]:
        if selected and not set(selected) <= {j[field] for j in plan}:
            raise ValueError('Unknown selection for ' + field)
    return [j for j in plan if (not models or j['model'] in models)
            and (not modes or j['mode'] in modes) and (not benchmarks or j['benchmark'] in benchmarks)]


def complete(job, output):
    from verifier.verify import check_group
    for benchmark in job['outputs']:
        folder = output/job['model']/benchmark/job['mode']
        if not (folder/'resumo.json').exists():
            return False
        summary = read(folder/'resumo.json')
        if summary['status'] not in ('final', 'sem_capacidade_demonstrada'):
            return False
        if summary.get('perfil_inferencia') != job['profile']:
            raise ValueError('Existing result uses a different profile: ' + str(folder))
        check_group(folder, summary, benchmark)
    return True


def command(job, endpoint, cache, work, workers):
    family = read(REPO/'benchmarks/catalog.json')[job['benchmark']]['family']
    default = cache/('plus-venv' if family == 'plus' else 'remaining-venv')/'bin/python'
    if family not in ('plus', 'remaining'):
        default = REPO/'.venv/bin/python'
    python = endpoint.get('python', str(default))
    profile = read(REPO/job['profile'])
    args = [python, '-m', 's5_nano.cli', 'run', '--benchmark', job['benchmark'],
            '--profile', str(REPO/job['profile']), '--model', profile['model'],
            '--api-base', endpoint['api_base'], '--tokenizer', endpoint['tokenizer'],
            '--chat-template', endpoint['chat_template'], '--cache', str(cache),
            '--output', str(work), '--workers', str(workers)]
    if job['benchmark'] in ('mmlu_pt', 'global_mmlu_pt'):
        args.append('--allow-chat-adapter')
    if job['benchmark'] == 'marca' and endpoint.get('marca_snapshot'):
        args += ['--marca-snapshot', endpoint['marca_snapshot']]
    return args


def initialize(output):
    output.mkdir(parents=True, exist_ok=True)
    source = REPO/'results/modelos.json'
    target = output/'modelos.json'
    if target.exists() and read(target) != read(source):
        raise ValueError('Output model catalog differs')
    if not target.exists():
        target.write_bytes(source.read_bytes())
    for model in read(source):
        for benchmark in read(REPO/'benchmarks/metrics.json'):
            for mode in ('thinking', 'instruct'):
                folder = output/model/benchmark/mode
                folder.mkdir(parents=True, exist_ok=True)
                path = folder/'resumo.json'
                if not path.exists():
                    original = read(REPO/'results'/model/benchmark/mode/'resumo.json')
                    summary = {k: original[k] for k in ('modelo', 'benchmark', 'modo')}
                    summary.update(status='pendente' if original['status'] in ('final', 'sem_capacidade_demonstrada') else original['status'],
                                   score=None, registros=0, arquivos=[])
                    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models', nargs='+')
    p.add_argument('--modes', nargs='+', choices=['thinking', 'instruct'])
    p.add_argument('--benchmarks', nargs='+')
    p.add_argument('--endpoints', type=Path, help='Local JSON, one entry per model:mode; credentials stay in environment')
    p.add_argument('--output', type=Path, default=REPO/'results')
    p.add_argument('--work', type=Path, default=REPO/'.runs/reproduction')
    p.add_argument('--cache', type=Path, default=REPO/'.cache')
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--plan', action='store_true', help='Show the full selection without network, inference or writes')
    a = p.parse_args(argv)
    if a.workers < 1:
        p.error('workers must be positive')
    jobs = select_jobs(a.models, a.modes, a.benchmarks)
    if a.plan:
        print(json.dumps({'execucoes': len(jobs), 'conjuntos': sum(len(j['outputs']) for j in jobs),
                          'chamadas': 0, 'plano': jobs}, ensure_ascii=False, indent=2))
        return 0
    endpoints = read(a.endpoints) if a.endpoints else {}
    output, work, cache = a.output.resolve(), a.work.resolve(), a.cache.resolve()
    initialize(output)
    work.mkdir(parents=True, exist_ok=True)
    # The lock prevents two orchestrators from double-dispatching a campaign.
    with (work/'run_all.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for job in jobs:
            identity = f'{job["model"]}:{job["mode"]}'
            if complete(job, output):
                print(json.dumps(dict(job, status='final_verificado_reutilizado')), flush=True)
                continue
            if identity not in endpoints:
                raise ValueError('Missing endpoint configuration for ' + identity)
            endpoint = endpoints[identity]
            profile = read(REPO/job['profile'])
            template = Path(endpoint['chat_template'])
            if hashlib.sha256(template.read_bytes()).hexdigest() != profile['chat_template_sha256']:
                raise ValueError('Chat template differs from the selected protocol: ' + identity)
            if not Path(endpoint['tokenizer']).is_dir():
                raise ValueError('Tokenizer must be available locally: ' + identity)
            destination = work/job['model']/job['mode']
            cmd = command(job, endpoint, cache, destination, a.workers)
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO/'src'), str(REPO)]),
                       PYTHONDONTWRITEBYTECODE='1')
            print(json.dumps(dict(job, status='iniciando')), flush=True)
            subprocess.run(cmd, cwd=REPO, env=env, check=True)
            from .export_results import export_run
            receipts = export_run(job, destination/job['benchmark'], output)
            print(json.dumps({'status': 'final_verificado', 'resultados': receipts}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
