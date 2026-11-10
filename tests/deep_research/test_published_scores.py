"""Research result verification preserves signed weights and native clipping."""
from pathlib import Path
import sys
import unittest
import json
import shutil
import tempfile
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'benchmarks/agentico/draco/fork'))
from draco_benchmark.core import score as native_draco
sys.path.insert(0, str(ROOT/'benchmarks/agentico/researchrubrics/fork'))
from run_eval import question_score as native_researchrubrics
from verifier.verify import item_score, verify_supplemental, check_group


def row(benchmark, weights, values):
    votes = []
    for i, (weight, value) in enumerate(zip(weights, values)):
        verdict = ({'criterion_status': 'MET' if value else 'UNMET'} if benchmark == 'draco'
                   else {'score': value, 'verdict': 'Satisfied' if value else 'Not Satisfied'})
        votes.append({'indice': i, 'criterio': {'weight': weight}, 'veredito': verdict})
    return {'julgamento': {'veredito': {'criterios': votes}}}


class ResearchPublicationTests(unittest.TestCase):
    def empty_row(self, benchmark):
        value = row(benchmark, [2, -3], [0, 0])
        value.update(resposta='', total_tokens_julgamento=0, custo_julgamento={'valor': 0})
        value['julgamento'].update(tipo='politica_resposta_vazia', modelo=None, chamadas=[])
        for criterion in value['julgamento']['veredito']['criterios']:
            criterion['veredito'] = None
        value['julgamento']['veredito']['politica_resposta_vazia'] = {
            'politica': 'empty-final-after-three-attempts-zero-v1',
            'mesmo_pedido': True, 'pedido_sha256': 'a' * 64,
            'tentativas': [dict(tentativa=i, resposta='', motivo_encerramento='stop',
                               chamadas_ferramentas=[], pedido_sha256='a' * 64)
                          for i in (1, 2, 3)]}
        return value

    def test_three_empty_final_answers_have_zero_without_fake_judgments(self):
        for benchmark in ('draco', 'researchrubrics'):
            self.assertEqual(item_score(benchmark, self.empty_row(benchmark)), 0.0)

    def test_empty_policy_rejects_failed_nonempty_or_different_attempts(self):
        changes = [{'resposta': 'Resposta válida'}, {'motivo_encerramento': 'length'},
                   {'motivo_encerramento': 'error'}, {'pedido_sha256': 'b' * 64},
                   {'chamadas_ferramentas': [{'name': 'web_search'}]}, {'tentativa': 2}]
        for benchmark in ('draco', 'researchrubrics'):
            for change in changes:
                value = self.empty_row(benchmark)
                value['julgamento']['veredito']['politica_resposta_vazia']['tentativas'][0].update(change)
                with self.subTest(benchmark=benchmark, change=change), self.assertRaises(ValueError):
                    item_score(benchmark, value)
            for count in (0, 1, 2, 4):
                value = self.empty_row(benchmark)
                attempts = value['julgamento']['veredito']['politica_resposta_vazia']['tentativas']
                value['julgamento']['veredito']['politica_resposta_vazia']['tentativas'] = (attempts * 2)[:count]
                with self.subTest(benchmark=benchmark, attempts=count), self.assertRaises(ValueError):
                    item_score(benchmark, value)

    def test_empty_policy_cannot_hide_an_answer_or_invent_judgment(self):
        original = self.empty_row('draco')
        changed = deepcopy(original); changed['resposta'] = 'Resposta válida'
        fake_judge = deepcopy(original); fake_judge['julgamento']['modelo'] = 'S5'
        fake_verdict = deepcopy(original)
        fake_verdict['julgamento']['veredito']['criterios'][0]['veredito'] = {'criterion_status': 'UNMET'}
        for value in (changed, fake_judge, fake_verdict):
            with self.assertRaises(ValueError):
                item_score('draco', value)

    def test_native_context_zero_requires_exact_usage_and_preserves_valid_finals(self):
        value = self.empty_row('draco')
        value['parametros_inferencia'] = dict(context_length=4096, max_tokens=None)
        policy=value['julgamento']['veredito']['politica_resposta_vazia']
        policy.update(politica='native-context-exhausted-no-final-zero-v1',context_length=4096,
                      prompt_tokens=1000,completion_tokens=3096,total_tokens=4096,effective_max_tokens=None)
        policy['tentativas']=policy['tentativas'][:1]
        policy['tentativas'][0].update(motivo_encerramento='length',
                                     tokens=dict(prompt_tokens=1000,completion_tokens=3096,total_tokens=4096))
        self.assertEqual(item_score('draco',value),0.0)
        for change in [dict(completion_tokens=1024,total_tokens=2024),dict(total_tokens=4000)]:
            altered=deepcopy(value)
            altered['julgamento']['veredito']['politica_resposta_vazia']['tentativas'][0]['tokens'].update(change)
            with self.assertRaises(ValueError):item_score('draco',altered)
        value['resposta']='Valid final answer'
        with self.assertRaises(ValueError):item_score('draco',value)

    def test_draco_clips_negative_score(self):
        weights, values = [2, -3], [0, 1]
        expected = native_draco([{'weight': w} for w in weights], ['UNMET', 'MET'])['score']
        self.assertEqual(item_score('draco', row('draco', weights, values)), expected)
        self.assertEqual(expected, 0)

    def test_researchrubrics_preserves_negative_score(self):
        expected = native_researchrubrics([{'weight': 2}, {'weight': -3}], [0, 1])
        self.assertEqual(item_score('researchrubrics', row('researchrubrics', [2, -3], [0, 1])), expected)
        self.assertEqual(expected, -150)

    def test_invalid_votes_are_rejected(self):
        for benchmark in ('draco', 'researchrubrics'):
            value = row(benchmark, [1, 1], [1, 0])
            value['julgamento']['veredito']['criterios'][1]['indice'] = 0
            with self.assertRaises(ValueError):
                item_score(benchmark, value)
        value = row('researchrubrics', [1], [1])
        value['julgamento']['veredito']['criterios'][0]['veredito']['verdict'] = 'Not Satisfied'
        with self.assertRaises(ValueError):
            item_score('researchrubrics', value)

    def test_partial_draco_cannot_be_promoted_or_drop_failures(self):
        source = ROOT/'results/tucano2-qwen-3.7b/draco/instruct'
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'instruct'
            shutil.copytree(source, folder)
            summary = json.loads((folder/'resumo.json').read_text())
            self.assertEqual(check_group(folder, summary, 'draco'), (None, 48))
            for changes in ({'status': 'final', 'score': summary['score_parcial']},
                            {'score': 0}, {'denominador_agregado': 100},
                            {'score_parcial': 0}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    check_group(folder, dict(summary, **changes), 'draco')
            missing_path = folder/'casos-sem-nota.json'
            missing = json.loads(missing_path.read_text())
            missing_path.write_text(json.dumps(missing[:-1]))
            with self.assertRaises(ValueError):
                check_group(folder, summary, 'draco')
            missing_path.write_text(json.dumps(missing))
            summary['uso_ferramentas']['buscas_web'] += 1
            with self.assertRaises(ValueError):
                check_group(folder, summary, 'draco')

    def test_published_population_and_scores(self):
        report = verify_supplemental(ROOT/'results')
        self.assertGreaterEqual(report['conjuntos'], 8)
        for mode in ('instruct', 'thinking'):
            self.assertIsNone(report['notas'][f'tucano2-qwen-3.7b/draco/{mode}'])
        expected = {'gaia-4b/draco/instruct': 16.590807759896006,
                    'gaia-4b/researchrubrics/instruct': 23.62975414021194,
                    'lumi-4b/draco/instruct': 13.860375308877487,
                    'lumi-4b/draco/thinking': 10.987681538695401,
                    'lumi-4b/researchrubrics/instruct': 27.2689294377907,
                    'lumi-4b/researchrubrics/thinking': 22.894405887993205}
        for key, value in expected.items():
            self.assertAlmostEqual(report['notas'][key], value, places=10)


if __name__ == '__main__':
    unittest.main()
