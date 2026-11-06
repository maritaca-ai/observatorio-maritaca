"""Export native final results to the common, independently verifiable layout."""
import collections
import json
import math
from pathlib import Path
import tempfile

from .prepare import REPO
from . import export_format as fmt
from . import native_export as native
from .export_metadata import collect
from .export_judgments import exchanges
from .export_turns import process as collect_turns
from verifier.verify import check_group, item_score
from verifier.scores import aggregate


def adapters():
    return {**{t: native.replay for t in native.REPLAY},
            **{t: native.portuguese for t in native.PT},
            **{t: native.remaining for t in native.REMAINING},
            **{t: native.tool_cases for t in ('browsecomp_plus', 'marca_public', 'lumen_pt')},
            **{t: native.exams for t in ('enade_qa', 'enem_vl')},
            'bluex_v2': native.bluex, 'capitu': native.capitu,
            'capitu_conversations': native.capitu, 'prosa_pt': native.prosa}


def write_group(destination, rows, controls, metadata, summary):
    """Validate in a sibling staging folder; never overwrite a selected result."""
    if destination.exists() and (destination/'resumo.json').exists():
        previous = fmt.read(destination/'resumo.json')
        if previous['status'] in ('final', 'sem_capacidade_demonstrada'):
            raise ValueError('Selected results already exist: ' + str(destination))
        if previous.get('arquivos'):
            raise ValueError('Refusing to overwrite partial answer files')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.export-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        files, batch, size = [], [], 0

        def flush():
            if not batch:
                return
            name = f'respostas-{len(files)+1:04d}.json'
            fmt.write_json(stage/name, batch)
            files.append(dict(arquivo=name, registros=len(batch), primeiro_id=batch[0]['id'], ultimo_id=batch[-1]['id']))
            batch.clear()

        for row in rows:
            length = len(json.dumps(row, ensure_ascii=False).encode())
            if batch and (len(batch) >= 50 or size+length > 700_000):
                flush(); size = 0
            if length > 90_000_000:
                raise ValueError('One answer exceeds the repository file limit')
            batch.append(row); size += length
        flush()
        summary.update(registros=len(rows), arquivos=files)
        totals = collections.defaultdict(float)
        for row in rows:
            cost = row['custo_julgamento']
            if cost['valor'] is not None:
                totals[cost['moeda']] += cost['valor']
        summary['custos_julgamentos_selecionados'] = dict(valores_conhecidos=dict(totals),
            registros_sem_custo_recuperado=sum(r['custo_julgamento']['valor'] is None for r in rows),
            inclui_tentativas_descartadas=False, inclui_gpu=False)
        if controls:
            fmt.write_json(stage/'controles-capacidade.json', controls)
            summary['controles_capacidade'] = dict(arquivo='controles-capacidade.json', registros=len(controls),
                                                  sucessos=sum(r['score'] == 100 for r in controls))
        fmt.write_json(stage/'resumo.json', summary)
        check_group(stage, summary, metadata['slug'])
        (stage/'README.md').write_text(f'# {summary["modelo"]} · {metadata["name"]} · {summary["modo"]}\n\n'
            f'Nota: {summary["score"]}. Registros: {len(rows)}.\n\n'
            'Veja `resumo.json` e os arquivos `respostas-*.json`.\n')
        destination.mkdir(exist_ok=True)
        for file in stage.iterdir():
            file.replace(destination/file.name)


def export_run(job, source, output):
    source, output = Path(source), Path(output)
    verified = fmt.read(source/'results_verified.json')
    if verified.get('status') != 'FINAL':
        raise ValueError('Native execution has not completed')
    profile = fmt.read(REPO/job['profile'])
    if verified['profile'] != profile:
        raise ValueError('Native run profile differs from the selected protocol')
    catalog = fmt.read(REPO/'benchmarks/metrics.json')
    model = fmt.read(REPO/'results/modelos.json')[job['model']]
    receipts = []
    with tempfile.TemporaryDirectory(prefix='export-', dir=source) as temporary:
        directory = Path(temporary)
        for name in ('native', 'judges', 'tool-meta'):
            (directory/name).mkdir()
        for slug in job['outputs']:
            metadata = dict(catalog[slug], slug=slug)
            task = metadata['task']
            metric = verified['benchmarks']['capitu' if task == 'capitu_conversations' else task]
            spec = dict(root=str(source), task=task, model_id=job['model'], mode=job['mode'],
                        allowed_models=[job['model']], protocol_id=job['benchmark'],
                        public_source=metadata.get('source'), judge=metric.get('judge'))
            collect(spec, directory/'native')
            exchanges(spec, directory/'judges')
            if task in ('capitu', 'capitu_conversations', 'marca_public', 'browsecomp_plus', 'lumen_pt'):
                collect_turns(spec, directory)
            saved = fmt.Native(directory, job['model'], job['mode'], task)
            record = dict(profile=profile, judge=metric.get('judge'), judge_effort=metric.get('judge_reasoning_effort'))
            if task == 'lumen_pt' and metric.get('benign_success') == 0:
                record['averages_exclusion'] = True
            cases = list(adapters()[task](spec, source, source))
            if task == 'arena_hard_v2':
                cases.sort(key=lambda c: c['case_id'])
            if len({c['case_id'] for c in cases}) != len(cases):
                raise ValueError('Duplicate native case')
            rows, controls = [], []
            for case in cases:
                response = case['responses'][0]
                verdict = fmt.parsed(response['judgment']['text'])
                benign = task == 'lumen_pt' and verdict['kind'] == 'benign'
                row = fmt.format_case(case, response, saved, record,
                                      len(controls if benign else rows)+1, include_control=benign)
                if row is None:
                    continue
                if benign:
                    row['score'] = 100*int(verdict['benign_success'])
                    row['julgamento']['tipo'] = 'controle_deterministico_de_ferramentas'
                    row['julgamento']['modelo'] = None
                    row['parametros_inferencia_julgamento'] = None
                    row['total_tokens_julgamento'] = 0
                    row['custo_julgamento'] = dict(valor=0, moeda='USD', origem='controle_deterministico_sem_api')
                    controls.append(row)
                else:
                    if task == 'arena_hard_v2':
                        row['ordem_agregacao'] = len(rows)+1
                    row['score'] = item_score(slug, row)
                    rows.append(row)
            expected_n = fmt.read(REPO/'results'/job['model']/slug/job['mode']/'resumo.json')['registros']
            if len(rows) != expected_n:
                raise ValueError(f'{slug}: expected {expected_n} selected cases, found {len(rows)}')
            excluded = record.get('averages_exclusion', False)
            score = None if excluded else float(aggregate(slug, rows))
            expected = metric['multi_turn_conversation_accuracy'] if task == 'capitu_conversations' else metric['score']
            if task in ('lumen_pt', 'harmbench'):
                expected = 100-expected
            if not excluded and not math.isclose(score, expected, abs_tol=1e-8, rel_tol=0):
                raise ValueError(f'{slug}: native and exported scores disagree ({expected}, {score})')
            summary = dict(modelo=model['nome'], benchmark=metadata['name'], modo=job['mode'],
                           status='sem_capacidade_demonstrada' if excluded else 'final', score=score,
                           perfil_inferencia=job['profile'], conferencia_numerica='nota_recalculada_dos_registros')
            destination = output/job['model']/slug/job['mode']
            write_group(destination, rows, controls, metadata, summary)
            receipts.append(dict(model=job['model'], benchmark=slug, mode=job['mode'], score=score, records=len(rows)))
    return receipts
