"""Project saved research evaluations without generating answers or verdicts."""
from collections import Counter
from copy import deepcopy
import json

TASKS = {'draco', 'researchrubrics'}


def criteria(row):
    return [dict(text=v['criterio'].get('requirement', v['criterio'].get('criterion')),
                 weight=float(v['criterio']['weight']),
                 type=v['criterio'].get('section', v['criterio'].get('axis', '')))
            for v in row['julgamento']['veredito']['criterios']]


def effective_profile(profile, summary):
    profile = deepcopy(profile)
    config = summary['configuracao_geracao']
    if 'max_tokens' in config and config['max_tokens'] != profile.get('max_tokens'):
        profile['output_budget_source'] = 'configuracao_geracao.max_tokens do resumo deste benchmark'
    for key in ('max_tokens', 'context_length', 'context_reserve', 'input_byte_budget'):
        if key in config:
            profile[key] = config[key]
    return profile


def policy(row):
    return row['julgamento']['veredito'].get('politica_resposta_vazia')


def metadata(summary, rows, failures):
    """Use the same leading audit fields as every other result card."""
    rubric_count = sum(len(criteria(r)) for r in rows) + sum(r['criterios'] for r in failures)
    policy_rubrics = (sum(len(criteria(r)) for r in rows if policy(r))
                      + sum(r['criterios'] for r in failures))
    empty = sum(not r['resposta'].strip() for r in rows)
    empty += sum(r.get('content_chars') == 0 for r in failures)
    truncated = sum(r.get('motivo_encerramento') == 'length' for r in rows)
    truncated += sum(r.get('finish_reason') == 'length' for r in failures)
    audit = summary.get('auditoria', {})
    # Explicit source counts take precedence; unavailable failure text is not
    # inferred to have been empty merely because the case received zero.
    values = [
        ('missing_verdicts', 'Rubricas sem veredicto', audit.get('rubricas_sem_veredicto', 0)),
        ('eligible_rubrics', 'Rubricas elegíveis', rubric_count),
        ('judge_failures', 'Falhas do juiz', audit.get('falhas_do_juiz', 0)),
        ('empty_finals', 'Respostas finais vazias', audit.get('respostas_finais_vazias', empty)),
        ('output_truncations', 'Respostas truncadas', audit.get('respostas_truncadas', truncated)),
        ('generation_failures', 'Falhas de geração', audit.get('falhas_de_geracao', len(failures))),
        ('scored_rubrics', 'Rubricas pontuadas', rubric_count),
        ('judged_rubrics', 'Rubricas julgadas', rubric_count - policy_rubrics),
        ('policy_rubrics', 'Rubricas pontuadas por política de zero', policy_rubrics),
        ('zero_cases', 'Casos zerados por política', len(failures) + sum(bool(policy(r)) for r in rows)),
        ('saved_answers', 'Respostas registradas', len(rows)),
    ]
    context_failures = sum((policy(r) or {}).get('politica') ==
                          'native-context-exhausted-no-final-zero-v1' for r in rows)
    context_failures += sum(r['motivo'] == 'context_overflow' or
                            bool(r.get('tentativas_rejeitadas')) for r in failures)
    values += [('context_failures', 'Estouros de contexto na geração', context_failures),
               ('input_budget_failures', 'Falhas por orçamento de entrada',
                sum(r['motivo'] == 'input_byte_budget' for r in failures))]
    tools = Counter(t['chamada']['name'] for r in rows for t in r.get('chamadas_ferramentas', []))
    tools.update(t['nome'] for r in failures for t in r.get('ferramentas_executadas', []))
    values += [('native_tool_calls', 'Chamadas nativas de ferramentas', sum(tools.values())),
               ('web_searches', 'Buscas web', tools['web_search']),
               ('webpage_reads', 'Leituras de páginas', tools['webpage_scraping'])]
    fields = [dict(key=k, label=label, value=value, kind='count', status='recorded')
              for k, label, value in values]
    fields[0]['note'] = ('Critérios aguardando um veredicto válido. Critérios zerados por política '
                         'são contabilizados separadamente e não simulam julgamentos.')
    observed = sum(bool(t.get('reasoning_content') or t.get('reasoning') or t.get('reasoning_details'))
                   for r in rows for t in r.get('turnos_assistente', []))
    fields.append(dict(key='thinking_in_instruct', label='Respostas/turnos com thinking no Instruct',
                       value=observed if summary['modo'] == 'instruct' else None, kind='count',
                       status='recorded' if summary['modo'] == 'instruct' else 'not_applicable'))
    judge = summary['juiz']
    requests = {}
    for row in rows:
        parameters = row.get('parametros_inferencia_julgamento') or []
        for request in ([parameters] if isinstance(parameters, dict) else parameters):
            requests[json.dumps(request, sort_keys=True)] = request
    task = 'draco' if summary['benchmark'] == 'DRACO' else 'researchrubrics'
    protocol = task + '-serper-s5-none-v1'
    notes = list(summary.get('observacoes', []))
    if summary.get('orcamento_saida'):
        notes.append(summary['orcamento_saida'])
    return dict(n=summary['denominador_agregado'], denominator_unit='perguntas',
                judge=judge['model'], judge_effort=judge['effort'], judge_route=None,
                judge_parameters=dict(configuracao={k: v for k, v in judge.items() if 'sha256' not in k},
                                      parametros_efetivos=list(requests.values())),
                research_parameters={k: v for k, v in summary['pesquisa'].items() if 'sha256' not in k},
                generation_parameters=summary['configuracao_geracao'],
                protocol_id=protocol, comparison_key=protocol, flags=[], notes=notes,
                scorer_variant='weighted-rubrics',
                scorer_overrides=dict(aggregation=summary['agregacao'],
                                      generation_failure_policy=summary.get('politica_falha_geracao'),
                                      empty_final_policy=summary.get('politica_resposta_vazia'),
                                      context_policy=summary.get('politica_limite_contexto')),
                audit_summary=dict(schema_version=1, fields=fields,
                                   scope='Somente os registros selecionados para a nota atual.'))


def project_failure(row, model, mode, summary, source_url):
    """A saved failed-generation receipt is not a model answer or a judge vote."""
    return dict(model_id=model, mode=mode, final='', final_status='not_recorded',
                score=0, direction='higher', metric_name='Pontos por rubricas',
                judgment=dict(kind='generation_failure', judge=None,
                              policy=summary['politica_falha_geracao'], reason=row['motivo']),
                source_url=source_url,
                metadata=dict(parametros_inferencia=summary['configuracao_geracao'],
                              total_tokens=None, custo={'valor': None, 'moeda': None},
                              parametros_inferencia_julgamento=None, total_tokens_julgamento=0,
                              custo_julgamento={'valor': 0, 'moeda': 'USD'},
                              falha_geracao=row))
