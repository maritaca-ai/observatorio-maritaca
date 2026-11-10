"""Research projections preserve rubric identity, evidence and model failures."""
from collections import Counter
from copy import deepcopy
import unittest

from observatory.build import question_identity, project_response
from observatory.research import effective_profile, metadata, project_failure


def row():
    return dict(id='case-1', system='System', pergunta='Same research question', resposta='Final answer',
                parametros_inferencia={'temperature': 1}, total_tokens=20, custo={'valor': None},
                parametros_inferencia_julgamento={'reasoning_effort': 'none'},
                total_tokens_julgamento=10, custo_julgamento={'valor': None}, score=-20,
                julgamento=dict(modelo='S5', veredito={'criterios': [
                    dict(indice=0, criterio={'criterion': 'Useful fact', 'weight': 5, 'axis': 'Facts'},
                         veredito={'score': 0, 'verdict': 'Not Satisfied', 'reasoning': 'Not present'}),
                    dict(indice=1, criterio={'criterion': 'Invented citation', 'weight': -1, 'axis': 'Errors'},
                         veredito={'score': 1, 'verdict': 'Satisfied', 'reasoning': 'Invented source'})]}),
                turnos_assistente=[dict(role='assistant', content='Final answer', reasoning_content='Reasoning')],
                chamadas_ferramentas=[], motivo_encerramento='stop')


def summary():
    return dict(benchmark='ResearchRubrics', modo='instruct', score_individual='Points',
                denominador_agregado=2, configuracao_geracao={'max_tokens': 1024, 'context_length': 4096},
                juiz={'model': 'S5', 'effort': 'none'}, pesquisa={'max_tool_calls': 30},
                agregacao='Weighted mean', politica_falha_geracao='attempted-generation-failure-zero-v1')


class ResearchProjection(unittest.TestCase):
    def test_shared_rubrics_pair_but_changed_rubrics_do_not(self):
        a, b = row(), row()
        b['id'] = 'another-source-id'
        b['julgamento']['veredito']['criterios'][0]['criterio']['weight'] = 5.0
        self.assertEqual(question_identity('researchrubrics', a, Counter())[0],
                         question_identity('researchrubrics', b, Counter())[0])
        b['julgamento']['veredito']['criterios'][0]['criterio']['criterion'] = 'Different rubric'
        self.assertNotEqual(question_identity('researchrubrics', a, Counter())[0],
                            question_identity('researchrubrics', b, Counter())[0])

    def test_negative_score_and_final_answer_preserved_reasoning_separate(self):
        r = row()
        projected = project_response(r, 'candidate', 'instruct', summary(), 'source.json')
        self.assertEqual(projected['score'], -20)
        self.assertEqual(projected['final'], r['resposta'])
        self.assertEqual(projected['judgment']['kind'], 'research')
        self.assertIn('Reasoning', str(projected['_tool_trace']))
        self.assertNotIn('Reasoning', projected['final'])
        self.assertIsNone(projected['metadata']['custo_julgamento']['valor'])

    def test_effective_output_cap_overrides_general_profile_without_mutating_it(self):
        profile = {'max_tokens': None, 'context_length': 4096, 'sampling': {'temperature': .1}}
        before = deepcopy(profile)
        self.assertEqual(effective_profile(profile, summary())['max_tokens'], 1024)
        self.assertEqual(profile, before)

    def test_failure_is_zero_not_a_fabricated_answer_or_judgment(self):
        failure = dict(id='failure', pergunta='Same research question', motivo='output_length',
                       criterios=2, score=0, content_chars=100, finish_reason='length', julgamento=None)
        result = project_failure(failure, 'tucano', 'instruct', summary(), 'source.json')
        self.assertEqual(result['final_status'], 'not_recorded')
        self.assertEqual(result['score'], 0)
        self.assertIsNone(result['judgment']['judge'])
        fields = {f['key']: f['value'] for f in metadata(summary(), [row()], [failure])['audit_summary']['fields']}
        self.assertEqual(fields['empty_finals'], 0)
        self.assertEqual(fields['generation_failures'], 1)
        self.assertEqual(fields['output_truncations'], 1)
        self.assertEqual(fields['judged_rubrics'], 2)
        self.assertEqual(fields['policy_rubrics'], 2)
        self.assertEqual(fields['thinking_in_instruct'], 1)


if __name__ == '__main__':
    unittest.main()
