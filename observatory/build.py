"""Build the static Observatory from final Git results, without model/API calls."""
import argparse
import base64
import collections
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from observatory.repository import Repository
from observatory import research, vision
from verifier.scores import aggregate
from verifier.verify import item_score, same, calculate_averages, check_group

GITHUB = 'https://github.com/maritaca-ai/observatorio-maritaca'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob(output, folder, value, cache=None):
    raw = encoded(value)
    identity = digest(raw)
    name = f'cases/{folder}/{identity}.json.gz'
    path = output/name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        cached = Path(cache)/name if cache else None
        if cached and cached.is_file():
            compressed = cached.read_bytes()
            if gzip.decompress(compressed) != raw:
                raise ValueError('Cached asset differs from its content identity: '+name)
        else:
            compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        path.write_bytes(compressed)
    return dict(file=name, sha256=identity)


def displayed_profile(profile):
    return {k: v for k, v in profile.items() if 'sha256' not in k and k not in ('revision', 'weight_sha256', 'asset_sha256')}


def shared_edges(a, b):
    """Exact byte prefixes/suffixes; binary search keeps long inputs inexpensive."""
    low, high = 0, min(len(a), len(b))
    while low < high:
        middle = (low+high+1)//2
        if a[:middle] == b[:middle]: low = middle
        else: high = middle-1
    prefix, low, high = low, 0, min(len(a), len(b))-low
    while low < high:
        middle = (low+high+1)//2
        if a[-middle:] == b[-middle:]: low = middle
        else: high = middle-1
    return prefix, low


def input_blob(output, value, bases, identity, cache=None):
    raw = encoded(value)
    if identity in bases:
        original, reference = bases[identity]
        prefix, suffix = shared_edges(original, raw)
        if prefix+suffix > max(16384, len(raw)*0.4) and raw != original:
            middle = raw[prefix:len(raw)-suffix if suffix else len(raw)]
            delta = dict(_observatory_delta_v1=True, base=reference, prefix=prefix, suffix=suffix,
                         middle=base64.b64encode(middle).decode())
            reference = blob(output, 'blobs', delta, cache)
            # The browser reconstructs the original bytes before checking this hash.
            return dict(file=reference['file'], sha256=digest(raw))
    reference = blob(output, 'blobs', value, cache)
    if len(raw) > 16384 and identity not in bases:
        bases[identity] = (raw, reference)
    return reference


def table_record(catalog, summary, profile, model, mode, task, slug):
    identity = f'{model}:{mode}:{task}'
    r = copy.deepcopy(catalog['annotations'].get(identity, {}))
    if task in research.TASKS | vision.TASKS:
        r.setdefault('audit_summary', {'fields': []})
    if 'audit_summary' in r:
        r['audit_summary']['fields'] = [copy.deepcopy(catalog['audit_fields'][key])
                                       for key in r['audit_summary']['fields']]
    source = dict(file=f'results/{slug}/{catalog["benchmark_directories"][task]}/{mode}/resumo.json')
    source['url'] = GITHUB+'/blob/main/'+source['file']
    r.update(id=identity, model_id=model, mode=mode, task=task, score=summary['score'],
             n=summary['registros'], score_denominator=summary.get('denominador_agregado'),
             source=source, profile=displayed_profile(profile), as_of=catalog['updated_at'])
    if summary.get('observacao_nota'):
        r['score_note'] = summary['observacao_nota']
    if summary['status'] != 'final':
        r.update(status='unavailable', status_label='Sem capacidade demonstrada',
                 details={'reason': 'Nenhum dos 22 controles benignos foi concluído; não há nota de segurança.'})
        return r
    r.update(status='final', direction='higher')
    r.setdefault('metric', {}).update(score=summary['score'], n=summary['registros'])
    r['audit_summary']['source'] = source
    values = summary.get('custos_julgamentos_selecionados', {}).get('valores_conhecidos', {})
    r['cost'] = dict(usd=values.get('USD'), brl=values.get('BRL'), status='selected_judgments_only')
    return r


def question_identity(task, row, occurrence):
    # Do not pair distinct prompts merely because their sequential IDs match.
    inputs = dict(question=row['pergunta'], context=row.get('contexto') or '',
                  criteria=research.criteria(row) if task in research.TASKS
                  else row['julgamento'].get('criterios'))
    if row.get('imagem'):
        inputs['image'] = {k: row['imagem'][k] for k in ('sha256', 'largura', 'altura')}
    source_id = digest(encoded(inputs))
    ordinal = occurrence[source_id]
    occurrence[source_id] += 1
    return source_id+f':{ordinal}', inputs


def project_response(row, model, mode, summary, source_path):
    judgment = row['julgamento']
    native = judgment['veredito']
    kind = 'conduta' if 'criterios_atingidos' in judgment else 'native'
    response = dict(model_id=model, mode=mode, final=row['resposta'], score=row['score'],
        direction='higher', metric_name=summary['score_individual'],
        judgment=dict(kind=kind, judge=judgment.get('modelo'), text=json.dumps(native, ensure_ascii=False)),
        source_url=GITHUB+'/blob/main/'+source_path,
        metadata=dict(parametros_inferencia=row['parametros_inferencia'], total_tokens=row['total_tokens'],
                      custo=row['custo'], parametros_inferencia_julgamento=row['parametros_inferencia_julgamento'],
                      total_tokens_julgamento=row['total_tokens_julgamento'], custo_julgamento=row['custo_julgamento']))
    if kind == 'conduta':
        response['judgment']['hits'] = judgment['criterios_atingidos']
    if row.get('imagem'):
        response['judgment']['kind'] = 'vision'
        response['metadata'].update({k: row.get(k) for k in
            ('system', 'reasoning', 'tokens', 'finish_reason', 'resposta_final_vazia', 'resposta_truncada')})
    if row.get('turnos'):
        response['turns'] = [dict(turn=t.get('turno', i), question=t.get('pergunta') or next(
                                      (m.get('content', '') for m in reversed(t.get('mensagens_enviadas') or []) if m.get('role') == 'user'), ''),
                                  final=t.get('resposta') or '') for i, t in enumerate(row['turnos'])]
    if row.get('mensagens_enviadas'):
        response['_input_messages'] = row['mensagens_enviadas']
    if row.get('conversa_com_ferramentas'):
        response['_tool_trace'] = row['conversa_com_ferramentas']
    if row.get('contexto_insuficiente'):
        response['metadata']['contexto_insuficiente'] = True
    if summary.get('benchmark') in ('DRACO', 'ResearchRubrics'):
        response['metric_name'] = 'Pontos por rubricas'
        response['judgment']['kind'] = 'research'
        response['metadata']['system'] = row['system']
        if row.get('limites_saida_usados_por_turno'):
            response['metadata']['limites_saida_usados_por_turno'] = row['limites_saida_usados_por_turno']
        response['_tool_trace'] = dict(turnos_assistente=row.get('turnos_assistente', []),
                                       chamadas_ferramentas=row.get('chamadas_ferramentas', []))
    return response


def performance(row):
    j = row['julgamento']['veredito']
    return None if j.get('judge_error') or j.get('excluded') or j.get('valid') is False else row['score']


def build(output, from_git=False, only=None, max_bytes=1_000_000_000, cache=None, worktree_overlay=False, image_source='auto'):
    if image_source == 'auto':
        image_source = 'github' if from_git and not worktree_overlay else 'local'
    if image_source not in ('local', 'github'):
        raise ValueError('Unknown image source')
    if image_source == 'github' and (not from_git or worktree_overlay):
        raise ValueError('GitHub images require committed results: use --from-git without an overlay')
    image_revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() if image_source == 'github' else None
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory to avoid retaining stale assets')
    output.mkdir(parents=True, exist_ok=True)
    repo = Repository(ROOT, from_git, worktree_overlay)
    try:
        catalog = repo.json('observatory/catalog.json')
        metrics = repo.json('benchmarks/metrics.json')
        models = repo.json('results/modelos.json')
        reported = repo.json('verifier/reported.json')
        if set(catalog['model_directories'].values()) != set(models):
            raise ValueError('Observatory model scope differs from results')
        if set(catalog['benchmark_directories'].values()) != set(metrics):
            raise ValueError('Observatory benchmark scope differs from results')
        tasks = catalog['benchmark_directories']
        if only and not set(only) <= set(tasks):
            raise ValueError('Unknown benchmark selection')
        data = {k: copy.deepcopy(catalog[k]) for k in ['schema_version', 'title', 'updated_at',
                'categories', 'references', 'models', 'benchmarks', 'origins']}
        sources = repo.json('benchmarks/catalog.json')
        for benchmark in data['benchmarks']:
            slug = tasks[benchmark['id']]
            native_task = metrics[slug]['task']
            if native_task.startswith('mmlu_pt_'): native_task = 'mmlu_pt'
            if native_task == 'capitu_conversations': native_task = 'capitu'
            source_task = next((k for k, v in sources.items() if native_task in v['tasks']), native_task)
            benchmark['protocol_url'] = GITHUB+'/blob/main/'+sources[source_task]['directory']+'/protocol.json'
            if benchmark['id'] in vision.TASKS:
                benchmark['protocol_url'] = vision.document(repo, output, sources[source_task]['directory']+'/protocol.json')
        records, partials, scores, counts, indexes = [], [], {}, {}, []
        model_lookup = catalog['model_directories']
        total_responses = 0
        zero_generation_cases = 0
        copied_images = set()
        for task, benchmark in tasks.items():
            cases = {}
            input_bases = {}
            native_cases, pending_failures = {}, []
            for model, slug in model_lookup.items():
                for mode in models[slug]['modos_avaliados']:
                    folder = f'results/{slug}/{benchmark}/{mode}'
                    try:
                        summary = repo.json(folder+'/resumo.json')
                    except FileNotFoundError:
                        if metrics[benchmark].get('allow_missing_results'):
                            continue
                        raise
                    if summary['status'] not in ('final', 'sem_capacidade_demonstrada'):
                        old = catalog['annotations'].get(f'{model}:{mode}:{task}')
                        if old:
                            p = copy.deepcopy(old)
                            p.update(score=None, source={'url': GITHUB+'/tree/main/'+folder}, profile={})
                            partials.append(p)
                        continue
                    profile_path = summary.get('perfil_inferencia') or summary['proveniencia']['perfil']
                    profile = repo.json(profile_path)
                    research_parts = {}
                    if task in research.TASKS:
                        def load_part(path):
                            relative = str(Path(path).relative_to(ROOT)) if Path(path).is_absolute() else str(path)
                            if relative not in research_parts:
                                research_parts[relative] = repo.json(relative)
                            return research_parts[relative]
                        check_group(ROOT/folder, summary, benchmark, load_json=load_part,
                                    response_files=repo.response_files(folder))
                        profile = research.effective_profile(profile, summary)
                    record = table_record(catalog, summary, profile, model, mode, task, slug)
                    if task in vision.TASKS:
                        record.update(vision.metadata(summary))
                        record['source']['url'] = vision.document(repo, output, folder+'/resumo.json')
                        record['audit_summary']['source'] = record['source']
                    if task in research.TASKS:
                        rows = [r for part in summary['arquivos'] for r in load_part(folder+'/'+part['arquivo'])]
                        failures = load_part(folder+'/'+summary['casos_zerados']) if summary.get('casos_zerados') else []
                        record.update(research.metadata(summary, rows, failures))
                        record['audit_summary']['source'] = record['source']
                        pending_failures.extend((r, model, mode, summary, folder) for r in failures)
                    (records if summary['status'] == 'final' else partials).append(record)
                    key = f'{slug}/{benchmark}/{mode}'
                    if not same(summary['score'], reported['notas'][key]) or summary['registros'] != reported['populacoes'][key]:
                        raise ValueError('Result differs from verified reference: '+key)
                    scores[key] = summary['score']
                    if only and task not in only:
                        continue
                    occurrence = collections.Counter()
                    selected, ids = [], set()
                    for part in summary['arquivos']:
                        path = folder+'/'+part['arquivo']
                        batch = load_part(path) if task in research.TASKS else repo.json(path)
                        if len(batch) != part['registros']:
                            raise ValueError('Incomplete result part: '+path)
                        for row in batch:
                            if row['id'] in ids or not same(row['score'], item_score(benchmark, row)):
                                raise ValueError('Invalid/duplicate result: '+path)
                            ids.add(row['id'])
                            selected.append({k: row[k] for k in ['score', 'julgamento', 'ordem_agregacao', 'contexto_insuficiente'] if k in row})
                            identity, inputs = question_identity(task, row, occurrence)
                            if identity not in cases:
                                case_id = identity
                                input_sha = identity.split(':')[0]
                                case = dict(benchmark_id=task, protocol_id=task+'-final', case_id=case_id,
                                    input_sha256=input_sha, question=inputs['question'], context=inputs['context'],
                                    criteria=inputs['criteria'] or [], responses=[])
                                if task in vision.TASKS:
                                    case['image'] = vision.image_asset(repo, output, task, row['imagem'], copied_images, image_revision)
                                case_key = digest(':'.join([task, case['protocol_id'], input_sha, case_id]).encode())
                                cases[identity] = (case_key, case, {})
                            case_key, case, perf = cases[identity]
                            if task in research.TASKS:
                                previous = native_cases.get(row['id'])
                                if previous and previous[0] != case_key:
                                    raise ValueError('Research question or rubrics differ for the same ID: '+row['id'])
                                native_cases[row['id']] = (case_key, case, perf)
                            response = project_response(row, model, mode, summary, path)
                            if task in vision.TASKS:
                                response['source_url'] = blob(output, 'records', row, cache)['file']
                                response['source_local'] = True
                            for field, target in [('_input_messages', 'input_messages_ref'), ('_tool_trace', 'tool_trace_ref')]:
                                if field in response:
                                    value = response.pop(field)
                                    response[target] = (input_blob(output, value, input_bases, case_key, cache)
                                        if task == 'longbench_v2' and field == '_input_messages'
                                        else blob(output, 'blobs', value, cache))
                            case['responses'].append(response)
                            perf[f'{model}:{mode}'] = performance(row)
                    if len(ids) != summary['registros']:
                        raise ValueError('Incomplete final group: '+key)
                    if summary['status'] == 'sem_capacidade_demonstrada':
                        controls = repo.json(folder+'/controles-capacidade.json')
                        if len(controls) != 22 or any(r['julgamento']['veredito']['benign_success'] for r in controls):
                            raise ValueError('Lumen eligibility differs from saved controls')
                    elif task not in research.TASKS and not same(float(aggregate(benchmark, selected)), summary['score']):
                        raise ValueError('Aggregate differs from saved judgments: '+key)
                    total_responses += len(ids)
            if only and task not in only:
                continue
            for failure, model, mode, summary, folder in pending_failures:
                _, case, perf = native_cases[failure['id']]
                if failure['pergunta'] != case['question'] or failure['criterios'] != len(case['criteria']):
                    raise ValueError('Failed-generation receipt differs from its question: '+failure['id'])
                variant = f'{model}:{mode}'
                if variant in perf:
                    raise ValueError('Duplicate response/failure: '+variant+'/'+failure['id'])
                case['responses'].append(research.project_failure(
                    failure, model, mode, summary, GITHUB+'/blob/main/'+folder+'/'+summary['casos_zerados']))
                perf[variant] = 0
                zero_generation_cases += 1
            entries, chunk, pending, size = [], [], [], 0
            def flush():
                if chunk:
                    ref = blob(output, 'chunks', dict(schema_version=1, cases=chunk), cache)
                    entries.extend(dict(e, **ref) for e in pending)
                    chunk.clear(); pending.clear()
            for key, case, perf in cases.values():
                weight = len(encoded(case))
                if chunk and (len(chunk) >= 32 or size+weight > 2_000_000):
                    flush(); size = 0
                if len(case['context']) > 12000:
                    case['context_ref'] = blob(output, 'blobs', {'text': case.pop('context')}, cache)
                    case['context'] = ''
                chunk.append(case); size += weight
                pending.append(dict(key=key, benchmark_id=task, case_id=case['case_id'],
                    title=case['question'][:180], variants=list(perf), performance=perf))
            flush()
            index_ref = blob(output, 'indexes', dict(schema_version=2, cases=entries), cache)
            indexes.append(dict(benchmark_id=task, cases=len(entries), **index_ref))
            counts[task] = len(entries)
            print(json.dumps({'benchmark': task, 'cases': len(entries), 'responses_so_far': total_responses}), flush=True)
        if set(scores) != set(reported['notas']):
            raise ValueError('Missing final result in Observatory table')
        data.update(records=records, partials=partials, coverage=dict(total=len(records), excluded_results=0),
                    authentication={'mode': 'static'}, privacy={'audience': 'deployment-controlled', 'aggregate_only': False, 'model_calls': False},
                    notice='')
        for model in data['models']:
            model['result_count'] = sum(r['model_id'] == model['id'] for r in records)
        data['models'] = [model for model in data['models'] if model['result_count'] > 0]
        directory = encoded(dict(schema_version=2, benchmarks=indexes))
        (output/'cases/index.json').write_bytes(directory)
        data['case_catalog'] = dict(benchmarks=counts, total=sum(counts.values()),
                                   model_count=len(models), sha256=digest(directory))
        for b in data['benchmarks']:
            b['case_count'] = counts.get(b['id'], 0)
            b['result_count'] = sum(r['task'] == b['id'] for r in records)
        # Keep the interface's own averages independently testable against verifier.
        averages = {selection: calculate_averages(scores, models, metrics, *selection.split('/'))
                    for selection in reported['medias']}
        for selection, actual in averages.items():
            expected = reported['medias'][selection]
            if len(actual) != len(expected):
                raise ValueError('Average population differs from reference')
            for a, e in zip(actual, expected):
                if any(a[k] != e[k] for k in ['modelo', 'modo', 'ranking']):
                    raise ValueError('Ranking differs from verified reference')
                for origin in a['medias']:
                    x, y = a['medias'][origin], e['medias'][origin]
                    if not same(x['valor'], y['valor']) or any(x[k] != y[k] for k in ['n', 'total', 'benchmarks']):
                        raise ValueError('Average differs from verified reference: '+selection)
        (output/'data.json').write_bytes(encoded(data))
        for name in ['index.html', 'styles.css', 'home.js', 'home.css', 'model-controls.js', 'averages.js', 'experience.css', 'en.js', 'i18n.js']:
            (output/name).write_bytes(repo.bytes('observatory/'+name))
        for dest, names in [('app.js', ['scatter.js', 'method.js', 'app.js']),
                            ('experience.js', ['case-performance.js', 'experience.js'])]:
            (output/dest).write_bytes(b'\n'.join(repo.bytes('observatory/'+name) for name in names))
        for path in (HERE/'assets').iterdir():
            target = output/'assets'/path.name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(repo.bytes('observatory/assets/'+path.name))
        html = (output/'index.html').read_text()
        for asset in output.iterdir():
            if asset.suffix in ('.js', '.css'):
                html = html.replace('"'+asset.name+'"', '"'+asset.name+'?v='+digest(asset.read_bytes())[:12]+'"')
        (output/'index.html').write_text(html)
        (output/'.nojekyll').touch()
        size = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
        receipt = dict(models=len(models), numeric_scores=len(records), benchmarks=len(tasks),
                       cases=sum(counts.values()), responses=total_responses, bytes=size,
                       sampled=False, only=only, model_calls=0, judge_calls=0)
        receipt['generation_failures_projected'] = zero_generation_cases
        receipt['image_source'] = image_source
        receipt['original_images_verified'] = len(copied_images)
        (output/'build.json').write_bytes(encoded(receipt))
        if max_bytes and size > max_bytes:
            raise ValueError(f'Artifact exceeds GitHub Pages size limit: {size} bytes; no cases were dropped')
        return receipt
    finally:
        repo.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--from-git', action='store_true', help='Read committed result blobs with a sparse checkout')
    parser.add_argument('--worktree-overlay', action='store_true', help='Local preview: use working files before the Git fallback')
    parser.add_argument('--benchmarks', nargs='+', help='Local QA only; deployment requires the full catalog')
    parser.add_argument('--max-bytes', type=int, default=1_000_000_000)
    parser.add_argument('--cache', type=Path, help='Reuse verified compressed assets from a previous local build')
    parser.add_argument('--image-source', choices=('auto', 'local', 'github'), default='auto', help='Auto uses pinned GitHub images with --from-git, local images for worktree previews')
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.from_git, args.benchmarks, args.max_bytes, args.cache, args.worktree_overlay, args.image_source), ensure_ascii=False))


if __name__ == '__main__':
    main()
