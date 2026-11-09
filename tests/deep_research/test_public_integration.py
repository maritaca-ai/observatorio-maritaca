"""Public launchers, explicit upload destinations and pinned source inventory."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRACO = ROOT/'benchmarks/agentico/draco'
RR = ROOT/'benchmarks/agentico/researchrubrics'
sys.path.insert(0, str(RR/'fork'))
spec = importlib.util.spec_from_file_location('rr_public', RR/'fork/run_eval.py')
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)
from draco_benchmark import cli


@pytest.mark.parametrize('directory', [DRACO, RR])
def test_launcher_help_runs_without_credentials_or_network(directory, tmp_path):
    env = dict(os.environ, PYTHON=sys.executable)
    for name in ('MARITACA_API_KEY', 'OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'SERPER_API_KEY'):
        env.pop(name, None)
    result = subprocess.run([str(directory/'run.sh'), '--help'], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--base-url' in result.stdout
    assert '--judge-base-url' not in result.stdout
    assert '--keychain' not in result.stdout
    assert not list(tmp_path.iterdir())


def test_wandb_has_no_embedded_account_or_project():
    for parser in (cli.parser, rr.parser):
        args = parser().parse_args(['--run-id', 'test'])
        assert args.wandb is False
        assert args.wandb_entity is None and args.wandb_project is None


@pytest.mark.parametrize('options', [[], ['--wandb-project', 'user-project'], ['--wandb-entity', 'user-account']])
def test_upload_requires_both_destinations_before_loading_inputs(options, monkeypatch):
    def no_download(*args, **kwargs):
        pytest.fail('Input loading must not occur for incomplete W&B configuration')
    monkeypatch.setattr(cli, 'load_dataset', no_download)
    monkeypatch.setattr(rr, 'load_inputs', no_download)
    args = ['--run-id', 'test', '--wandb', *options]
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    monkeypatch.setattr(sys, 'argv', ['researchrubrics', *args])
    with pytest.raises(SystemExit) as exc:
        rr.main()
    assert exc.value.code == 2


def test_defaults_write_only_to_ignored_run_tree():
    assert cli.parser().parse_args(['--run-id', 'test']).output_root == ROOT/'.runs/draco'
    assert rr.parser().parse_args(['--run-id', 'test']).output == ROOT/'.runs/researchrubrics'
    result = subprocess.run(['git', 'check-ignore', '.runs/draco/test/answers/a.json',
                             '.runs/researchrubrics/test/answers/a.json', 'wandb/run-test/data.json'],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0 and len(result.stdout.splitlines()) == 3


def test_public_inventory_and_unchanged_historical_matrix():
    catalog = json.loads((ROOT/'benchmarks/catalog.json').read_text())
    forks = json.loads((ROOT/'benchmarks/forks.json').read_text())
    plan = json.loads((ROOT/'profiles/plan.json').read_text())
    for name in ('draco', 'researchrubrics'):
        entry = forks[name]; directory = ROOT/entry['directory']
        assert catalog[name]['campaign_enabled'] is False
        assert not any(job['benchmark'] == name for job in plan)
        assert hashlib.sha256((directory/'upstream.lock.json').read_bytes()).hexdigest() == entry['source_lock_sha256']
        actual = {str(p.relative_to(directory/'fork')) for p in (directory/'fork').rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts}
        assert actual == set(entry['files'])
        for path, expected in entry['files'].items():
            assert hashlib.sha256((directory/'fork'/path).read_bytes()).hexdigest() == expected
