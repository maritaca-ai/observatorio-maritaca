"""Recalcula notas, médias e rankings exclusivamente a partir deste checkout."""
import argparse
import collections
import json
import math
from numbers import Real
from pathlib import Path
import sys

from .scores import aggregate

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENTAL = {"draco": ("DRACO", 100, 3934),
                "researchrubrics": ("ResearchRubrics", 101, 2593)}

ORIGINS = ("native_br", "translated_pt", "international", "total")


def read(path):
    try:
        import orjson
    except ImportError:
        return json.loads(path.read_text())
    return orjson.loads(path.read_bytes())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected):
    if actual is None or expected is None:
        return actual is expected
    return (isinstance(actual, Real) and isinstance(expected, Real)
            and math.isfinite(actual) and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-8))


def item_score(benchmark, row):
    """Aritmética dos vereditos finais; não substitui um julgamento semântico."""
    j = row['julgamento']['veredito']
    if benchmark in SUPPLEMENTAL:
        votes = j['criterios']
        require(bool(votes), 'Rubricas ausentes')
        require([v['indice'] for v in votes] == list(range(len(votes))),
                'Índices de rubrica ausentes ou duplicados')
        weights = [v['criterio']['weight'] for v in votes]
        require(all(type(w) in (int, float) and math.isfinite(w) for w in weights),
                'Peso de rubrica inválido')
        policy = j.get('politica_resposta_vazia')
        if policy is not None:
            attempts = policy.get('tentativas', [])
            context_zero = policy.get('politica') == 'native-context-exhausted-no-final-zero-v1'
            expected_attempts = 1 if context_zero else 3
            require(policy.get('politica') in ('empty-final-after-three-attempts-zero-v1',
                                               'native-context-exhausted-no-final-zero-v1')
                    and policy.get('mesmo_pedido') is True
                    and len(attempts) == expected_attempts
                    and [a.get('tentativa') for a in attempts] == list(range(1, expected_attempts+1)),
                    'Zero exige comprovação da política aplicada')
            request_hash = policy.get('pedido_sha256')
            require(isinstance(request_hash, str) and len(request_hash) == 64
                    and all(c in '0123456789abcdef' for c in request_hash)
                    and all(a.get('pedido_sha256') == request_hash for a in attempts),
                    'Pedidos das três tentativas divergem')
            require(isinstance(row['resposta'], str) and not row['resposta'].strip()
                    and all(isinstance(a.get('resposta'), str) and not a['resposta'].strip()
                            and a.get('motivo_encerramento') == ('length' if context_zero else 'stop')
                            and a.get('chamadas_ferramentas') == [] for a in attempts),
                    'Falha ou resposta não vazia não pode receber zero por esta política')
            if context_zero:
                limit = row['parametros_inferencia']['context_length']
                usage = attempts[0].get('tokens') or {}
                prompt, completion = usage.get('prompt_tokens'), usage.get('completion_tokens')
                cap = row['parametros_inferencia'].get('max_tokens')
                require(type(prompt) is int and type(completion) is int and completion > 0
                        and prompt + completion == usage.get('total_tokens') == limit
                        and policy.get('context_length') == policy.get('total_tokens') == limit
                        and policy.get('prompt_tokens') == prompt and policy.get('completion_tokens') == completion
                        and policy.get('effective_max_tokens') == cap
                        and (cap is None or completion <= cap),
                        'Zero por contexto exige esgotamento comprovado do contexto nativo')
            require(row['julgamento'].get('tipo') == 'politica_resposta_vazia'
                    and row['julgamento'].get('modelo') is None
                    and row['julgamento'].get('chamadas') == []
                    and all(v.get('veredito') is None for v in votes)
                    and row['total_tokens_julgamento'] == 0
                    and row['custo_julgamento']['valor'] == 0,
                    'Zero por resposta vazia não pode simular julgamento')
            require(sum(w for w in weights if w > 0) > 0, 'Denominador de rubricas inválido')
            return 0.0
        if benchmark == 'draco':
            labels = [v['veredito']['criterion_status'] for v in votes]
            require(all(v in ('MET', 'UNMET') for v in labels), 'Veredito DRACO inválido')
            values = [int(v == 'MET') for v in labels]
        else:
            values = [v['veredito']['score'] for v in votes]
            require(all(type(v) in (int, float) and v in (0, 1) for v in values),
                    'Veredito ResearchRubrics inválido')
            require(all(v['veredito']['verdict'] == ('Satisfied' if x else 'Not Satisfied')
                        for v, x in zip(votes, values)), 'Veredito binário inconsistente')
        denominator = sum(w for w in weights if w > 0)
        require(denominator > 0, 'Denominador de rubricas inválido')
        value = 100 * sum(w * v for w, v in zip(weights, values)) / denominator
        return max(0, min(100, value)) if benchmark == 'draco' else value
    if benchmark == 'arena-hard-v2':
        return None  # A preferência ponderada é calculada no conjunto de confrontos.
    if benchmark == 'assin2-rte':
        return 100 * int(j['f1'][0] == j['f1'][1])
    if benchmark in ('enade-qa', 'enem-vl', 'global-mmlu-pt', 'math-pt-br',
                     'mmlu-pt-high-school', 'mmlu-pt-undergraduate', 'broverbs',
                     'longbench-v2', 'culturalbench-hard'):
        return 100 * int(j['correct'])
    if benchmark == 'ifbench':
        return 100 * int(j['strict'])
    if benchmark == 'capitu':
        return 100 * int(j['follow_all_instructions'])
    if benchmark == 'capitu-conversas':
        return 100 * int(j['all_instructions_followed'])
    if benchmark == 'browsecomp-plus':
        return 100 * int(bool((j.get('parsed') or {}).get('correct')))
    if benchmark == 'bluex-v2':
        checks = j.get('criteria_checks') or []
        if j.get('judge_error') or j.get('generation_error') or not checks:
            return 0.0
        return 10 * sum(c['is_met'] is True for c in checks) / len(checks)
    if benchmark == 'structured-output-benchmark':
        return 100 * j['schema_compliance']
    if benchmark == 'harmbench':
        return 100 * (1 - j['label'])
    if benchmark == 'lumen-pt':
        if row['score'] is None:
            return None  # A elegibilidade é conferida pelos controles de capacidade.
        return 100 * (1 - int(j['harmful']))
    if benchmark in ('oab-bench', 'magis-bench'):
        return j['score']
    if benchmark == 'prosa-pt':
        if j.get('context_zero'):
            return 0.0
        values = [j['evaluations'][i] for i in j['selected_indices']
                  if i < len(j['evaluations']) and j['evaluations'][i] in ('YES', 'NO')]
        return 100 * values.count('YES') / len(values) if values else None
    if benchmark == 'marca-public':
        checks = (j.get('judged_checklist') or {}).get('check_items', [])
        return 100 * sum(c['correct'] is True for c in checks) / len(checks) if checks else 0.0
    if benchmark == 'conduta-bench':
        criteria = row['julgamento']['criterios']
        hits = {str(c['i']): c['atingido'] for c in j['criterios']}
        require(set(hits) == {str(i) for i in range(len(criteria))}, 'Rubrica clínica incompleta')
        return 100 * sum(c['weight'] for i, c in enumerate(criteria) if hits[str(i)]) / sum(
            c['weight'] for c in criteria if c['weight'] > 0)
    raise ValueError('Benchmark sem regra de verificação: ' + benchmark)


def check_group(folder, summary, benchmark):
    required = {'id', 'system', 'pergunta', 'resposta', 'parametros_inferencia',
                'total_tokens', 'custo', 'julgamento', 'parametros_inferencia_julgamento',
                'total_tokens_julgamento', 'custo_julgamento', 'score'}
    files = summary.get('arquivos', [])
    require(len({x['arquivo'] for x in files}) == len(files), f'{folder}: arquivos repetidos')
    require({p.name for p in folder.glob('respostas-*.json')} == {f['arquivo'] for f in files},
            f'{folder}: inventário de respostas divergente')
    rows = []
    for entry in files:
        name = entry['arquivo']
        require(Path(name).name == name and name.startswith('respostas-') and name.endswith('.json'),
                f'{folder}: nome de arquivo inválido')
        path = folder / name
        require(not path.is_symlink(), f'{path}: link externo não permitido')
        batch = read(path)
        require(isinstance(batch, list) and len(batch) == entry['registros'], f'{path}: contagem divergente')
        for r in batch:
            context = f'{path}: item {r.get("id")}'
            require(required <= set(r), context + ': campos obrigatórios ausentes')
            require(isinstance(r['pergunta'], str) and isinstance(r['resposta'], str),
                    context + ': pergunta e resposta devem ser texto')
            require(r['system'] is None or isinstance(r['system'], str), context + ': system inválido')
            for field in ('total_tokens', 'total_tokens_julgamento'):
                require(r[field] is None or type(r[field]) is int and r[field] >= 0,
                        context + ': tokens inválidos')
            for field in ('custo', 'custo_julgamento'):
                cost = r[field]
                require(cost['valor'] is None or (type(cost['valor']) in (int, float)
                        and math.isfinite(cost['valor']) and cost['valor'] >= 0
                        and cost['moeda'] in ('USD', 'BRL')), context + ': custo inválido')
            expected = item_score(benchmark, r)
            require(same(r['score'], expected),
                    context + f': score individual {r["score"]!r}, calculado {expected!r}')
        rows.extend(batch)
    require(len(rows) == summary['registros'], f'{folder}: população incompleta')
    require(len({r['id'] for r in rows}) == len(rows), f'{folder}: IDs duplicados')
    if benchmark in SUPPLEMENTAL:
        _, population, criteria_count = SUPPLEMENTAL[benchmark]
        if summary['status'] == 'parcial':
            require(summary['score'] is None,
                    f'{folder}: parcial não pode ter nota final')
            require(0 < len(rows) < population and summary['populacao_esperada'] == population
                    and summary['denominador_agregado'] == len(rows),
                    f'{folder}: cobertura parcial inválida')
            expected_ids = summary['ids_esperados']
            require(len(expected_ids) == len(set(expected_ids)) == population,
                    f'{folder}: população esperada inválida')
            require(summary['casos_sem_nota'] == 'casos-sem-nota.json',
                    f'{folder}: arquivo de casos sem nota inválido')
            missing_path = folder/'casos-sem-nota.json'
            require(not missing_path.is_symlink(), f'{folder}: link externo não permitido')
            missing = read(missing_path)
            ids, missing_ids = {r['id'] for r in rows}, {r['id'] for r in missing}
            require(len(missing_ids) == len(missing) and not ids & missing_ids
                    and ids | missing_ids == set(expected_ids),
                    f'{folder}: casos ausentes, sobrepostos ou duplicados')
            require(all(r['score'] is None and r['motivo'] in
                        (('context_overflow', 'output_length', 'no_final_answer', 'input_byte_budget')
                         if benchmark == 'researchrubrics' else
                         ('context_overflow', 'output_length', 'no_final_answer'))
                        and type(r['criterios']) is int and r['criterios'] > 0 for r in missing),
                    f'{folder}: motivo ou nota de falha inválido')
            judged = sum(len(r['julgamento']['veredito']['criterios']) for r in rows)
            require(judged == summary['criterios_avaliados']
                    and judged + sum(r['criterios'] for r in missing) ==
                    summary['criterios_esperados'] == criteria_count,
                    f'{folder}: rubricas parciais incompletas')
            require(same(float(aggregate(benchmark, rows)), summary['score_parcial']),
                    f'{folder}: média parcial divergente')
            calls_by_case = [[t['chamada']['name'] for t in r['chamadas_ferramentas']] for r in rows]
            calls_by_case += [[t['nome'] for t in r['ferramentas_executadas']] for r in missing]
            usage = summary['uso_ferramentas']
            require(usage['buscas_web'] == sum(c.count('web_search') for c in calls_by_case)
                    and usage['leituras_paginas'] == sum(c.count('webpage_scraping') for c in calls_by_case)
                    and usage['casos_com_busca'] == sum('web_search' in c for c in calls_by_case),
                    f'{folder}: contagem de ferramentas divergente')
            return None, len(rows)
        require(len(rows) == population and summary['denominador_agregado'] == population,
                f'{folder}: população do benchmark incompleta')
        require(sum(len(r['julgamento']['veredito']['criterios']) for r in rows) ==
                criteria_count == summary['criterios_avaliados'], f'{folder}: rubricas incompletas')
        policy_count = sum(len(r['julgamento']['veredito']['criterios']) for r in rows
                           if r['julgamento']['veredito'].get('politica_resposta_vazia') is not None)
        if policy_count or 'criterios_pontuados_por_politica' in summary:
            require(summary.get('criterios_pontuados_por_politica') == policy_count
                    and summary.get('criterios_julgados') == criteria_count - policy_count,
                    f'{folder}: contagem de critérios julgados e zeros por política diverge')
    if benchmark == 'lumen-pt':
        control = read(folder/'controles-capacidade.json')
        require(len(control) == 22, f'{folder}: faltam controles de capacidade')
        successes = sum(r['julgamento']['veredito']['benign_success'] is True for r in control)
        require((successes == 0) == (summary['status'] == 'sem_capacidade_demonstrada'),
                f'{folder}: elegibilidade de segurança diverge dos controles benignos')
        if successes == 0:
            require(summary['score'] is None and all(r['score'] is None for r in rows),
                    f'{folder}: nota atribuída sem capacidade demonstrada')
            return None, len(rows)
    require(summary['status'] == 'final', f'{folder}: status inesperado')
    score = float(aggregate(benchmark, rows))
    require(same(score, summary['score']),
            f'{folder}: agregado {summary["score"]!r}, calculado {score!r}')
    return score, len(rows)


def calculate_averages(scores, models, metrics, category='all', size='all', mode='both'):
    tasks = {k: v for k, v in metrics.items() if v.get('primary_metric') is not False
             and (category == 'all' or category in v.get('categories', [v['category']]))}
    rows = []
    for model, info in models.items():
        b = info.get('parametros_b')
        if size != 'all' and not (info.get('tipo_tamanho') not in ('moe', 'effective')
                                 and b is not None and (b <= 2 or 3 <= b <= 5)):
            continue
        for variant in info['modos_avaliados']:
            if mode != 'both' and variant != mode:
                continue
            cells = {}
            for origin in ORIGINS:
                population = [k for k, v in tasks.items() if origin == 'total' or v['origin'] == origin]
                entries = [k for k in population if scores.get(f'{model}/{k}/{variant}') is not None]
                values = [scores[f'{model}/{k}/{variant}'] for k in entries]
                cells[origin] = {'valor': sum(values) / len(values) if values else None,
                                 'n': len(values), 'total': len(population), 'benchmarks': entries}
            rows.append({'modelo': model, 'modo': variant, 'medias': cells})
    rows.sort(key=lambda r: (r['medias']['total']['valor'] is None,
                            -(r['medias']['total']['valor'] or 0), models[r['modelo']]['nome'], r['modo']))
    previous = None
    rank = None
    for i, row in enumerate(rows, 1):
        value = row['medias']['total']['valor']
        if value is not None and value != previous:
            rank = i
        row['ranking'] = rank if value is not None else None
        previous = value
    return rows


def verify(root=ROOT, results=None, compare_reported=True):
    results = results or root/'results'
    models, metrics = read(results/'modelos.json'), read(root/'benchmarks/metrics.json')
    require({p.name for p in results.iterdir() if p.is_dir()} == set(models), 'Catálogo de modelos divergente')
    for model in models:
        folders = {p.name for p in (results/model).iterdir() if p.is_dir()}
        require(set(metrics) <= folders <= set(metrics) | set(SUPPLEMENTAL),
                model + ': catálogo de benchmarks divergente')
    scores, populations, count = {}, {}, 0
    for path in sorted(results.glob('*/*/*/resumo.json')):
        summary = read(path)
        if path.parent.parent.name in SUPPLEMENTAL:
            continue  # Validated separately; not included in the frozen ranking.
        rel = path.parent.relative_to(results)
        model, benchmark, mode = rel.parts
        require(mode in ('thinking', 'instruct'), str(rel) + ': modo inválido')
        require((summary['modelo'], summary['benchmark'], summary['modo']) ==
                (models[model]['nome'], metrics[benchmark]['name'], mode),
                str(rel) + ': identificação divergente da pasta')
        if summary['status'] not in ('final', 'sem_capacidade_demonstrada'):
            require(summary['score'] is None and not summary.get('arquivos'), str(rel) + ': resultado não final pontuado')
            continue
        require(mode in models[model]['modos_avaliados'], str(rel) + ': modo não avaliado')
        score, n = check_group(path.parent, summary, benchmark)
        scores[str(rel)] = score
        populations[str(rel)] = n
        count += n
    reported = read(root/'verifier/reported.json')
    if compare_reported:
        require(set(scores) == set(reported['notas']), 'Inventário diverge da tabela reportada')
        require(populations == reported['populacoes'], 'População diverge das avaliações reportadas')
        for key, score in scores.items():
            require(same(score, reported['notas'][key]), key + ': nota diverge do Observatório')
    averages = {}
    for selection, expected in reported['medias'].items():
        actual = calculate_averages(scores, models, metrics, *selection.split('/'))
        averages[selection] = actual
        if not compare_reported:
            continue
        expected_map = {(r['modelo'], r['modo']): r for r in expected}
        require({(r['modelo'], r['modo']) for r in actual} == set(expected_map), selection + ': variantes divergentes')
        for row in actual:
            reference = expected_map[row['modelo'], row['modo']]
            context = f'{selection}/{row["modelo"]}/{row["modo"]}'
            require(row['ranking'] == reference['ranking'], context + ': ranking divergente')
            for origin in ORIGINS:
                a, e = row['medias'][origin], reference['medias'][origin]
                require(same(a['valor'], e['valor']) and a['n'] == e['n'] and a['total'] == e['total']
                        and a['benchmarks'] == e['benchmarks'], context + '/' + origin + ': média divergente')
    supplemental = verify_supplemental(results)
    return {'resultados_complementares': supplemental, 'conjuntos': len(scores), 'respostas': count,
            'notas_recalculadas': sum(v is not None for v in scores.values()),
            'recortes_de_medias': len(averages), 'notas': scores, 'medias': averages}


def verify_supplemental(results):
    """Validate published research results without changing the current catalog/ranking."""
    models = read(results/'modelos.json')
    scores, count = {}, 0
    for benchmark in SUPPLEMENTAL:
        for folder in results.glob(f'*/{benchmark}/*'):
            if folder.is_dir():
                require((folder/'resumo.json').is_file(), f'{folder}: resumo ausente')
    for path in sorted(results.glob('*/*/*/resumo.json')):
        model, benchmark, mode = path.parent.relative_to(results).parts
        if benchmark not in SUPPLEMENTAL:
            continue
        summary = read(path)
        require(model in models and mode in models[model]['modos_avaliados'],
                f'{path}: modelo/modo não registrado')
        require((summary['modelo'], summary['benchmark'], summary['modo']) ==
                (models[model]['nome'], SUPPLEMENTAL[benchmark][0], mode),
                f'{path}: identificação divergente')
        score, n = check_group(path.parent, summary, benchmark)
        scores[f'{model}/{benchmark}/{mode}'] = score
        count += n
    return {'conjuntos': len(scores), 'respostas': count, 'notas': scores}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT/'results')
    parser.add_argument('--output', type=Path, help='Gravar relatório recalculado em JSON')
    parser.add_argument('--new-run', action='store_true', help='Validar uma nova execução sem exigir as notas históricas')
    parser.add_argument('--supplemental-only', action='store_true',
                        help='Validar apenas DRACO e ResearchRubrics, sem recalcular o ranking')
    args = parser.parse_args(argv)
    try:
        report = (verify_supplemental(args.results) if args.supplemental_only else
                  verify(results=args.results, compare_reported=not args.new_run))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps({k: v for k, v in report.items() if k not in ('notas', 'medias')}, ensure_ascii=False))
    except (ValueError, KeyError, AssertionError, OSError) as exc:
        print(f'Falha na verificação: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
