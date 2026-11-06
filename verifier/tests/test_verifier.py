import copy
import json
from pathlib import Path
import tempfile
import unittest

from verifier.verify import calculate_averages, check_group, item_score, verify
from verifier.scores import aggregate


def row(score=100):
    return dict(id='000001', system='', pergunta='A ou B?', resposta='A',
                parametros_inferencia={}, total_tokens=None,
                custo={'valor': 0, 'moeda': 'USD'},
                julgamento={'veredito': {'correct': True}},
                parametros_inferencia_julgamento=None, total_tokens_julgamento=0,
                custo_julgamento={'valor': 0, 'moeda': 'USD'}, score=score)


class VerifierTests(unittest.TestCase):
    def test_detects_changed_item_even_when_summary_is_changed_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'respostas-0001.json').write_text(json.dumps([row(0)]))
            summary = dict(status='final', score=0, registros=1,
                           arquivos=[{'arquivo': 'respostas-0001.json', 'registros': 1}])
            with self.assertRaisesRegex(ValueError, 'score individual'):
                check_group(folder, summary, 'enade-qa')

    def test_detects_missing_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'inventário'):
                check_group(Path(tmp), {'arquivos': [{'arquivo': 'respostas-0001.json'}]}, 'enade-qa')

    def test_reducing_population_and_summary_cannot_hide_missing_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root/'results/model/enade-qa/instruct'
            folder.mkdir(parents=True)
            (root/'benchmarks').mkdir()
            (root/'verifier').mkdir()
            def write(path, value):
                path.write_text(json.dumps(value))
            write(root/'results/modelos.json', {'model': {'nome': 'Modelo', 'modos_avaliados': ['instruct']}})
            write(root/'benchmarks/metrics.json', {'enade-qa': {'name': 'ENADE-QA', 'category': 'provas', 'origin': 'native_br'}})
            key = 'model/enade-qa/instruct'
            write(root/'verifier/reported.json', {'notas': {key: 100}, 'populacoes': {key: 2}, 'medias': {}})
            rows = [row(), dict(row(), id='000002')]
            summary = dict(modelo='Modelo', benchmark='ENADE-QA', modo='instruct', status='final',
                           score=100, registros=2, arquivos=[{'arquivo': 'respostas-0001.json', 'registros': 2}])
            write(folder/'respostas-0001.json', rows)
            write(folder/'resumo.json', summary)
            self.assertEqual(verify(root)['respostas'], 2)
            write(folder/'respostas-0001.json', rows[:1])
            summary['registros'] = summary['arquivos'][0]['registros'] = 1
            write(folder/'resumo.json', summary)
            with self.assertRaisesRegex(ValueError, 'População'):
                verify(root)

    def test_assin_uses_macro_f1_instead_of_accuracy(self):
        rows = [{'score': 100 * (a == b), 'julgamento': {'veredito': {'f1': [a, b]}}}
                for a, b in [('sim', 'sim'), ('não', 'sim'), ('não', 'não'), ('não', 'não')]]
        self.assertAlmostEqual(aggregate('assin2-rte', rows), 100 * ((2/3)+(4/5))/2)
        self.assertNotEqual(aggregate('assin2-rte', rows), 75)
        self.assertEqual(item_score('assin2-rte', rows[0]), 100)

    def test_prosa_uses_rubrics_and_counts_context_zeros(self):
        rows = [dict(score=100, julgamento={'veredito': {'evaluations': ['YES', 'PARTIAL'], 'selected_indices': [0, 1]}}),
                dict(score=0, julgamento={'veredito': {'evaluations': [], 'selected_indices': [0, 1, 2], 'context_zero': True}})]
        self.assertEqual(aggregate('prosa-pt', rows), 25)

    def test_safety_complement_applied_once(self):
        r = row(); r['julgamento']['veredito'] = {'label': 1}
        self.assertEqual(item_score('harmbench', r), 0)

    def test_averages_weights_modes_categories_missing_scores_and_ties(self):
        models = {'a': {'nome': 'A', 'modos_avaliados': ['thinking', 'instruct'], 'parametros_b': 4},
                  'b': {'nome': 'B', 'modos_avaliados': ['thinking'], 'parametros_b': 70}}
        metrics = {'chat': {'category': 'chat', 'origin': 'native_br'},
                   'exam': {'category': 'provas', 'origin': 'international'},
                   'extra': {'category': 'chat', 'origin': 'native_br', 'primary_metric': False}}
        scores = {'a/chat/thinking': 80, 'a/exam/thinking': 40, 'a/extra/thinking': 0,
                  'a/chat/instruct': 60, 'b/chat/thinking': 90}
        values = calculate_averages(scores, models, metrics)
        self.assertEqual([r['ranking'] for r in values], [1, 2, 2])
        for r in values[1:]:
            self.assertEqual(r['medias']['total']['valor'], 60)
        selected = calculate_averages(scores, models, metrics, 'chat', 'up_to_4b', 'thinking')
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['medias']['total']['valor'], 80)
        self.assertEqual(selected[0]['medias']['total']['n'], 1)


if __name__ == '__main__':
    unittest.main()
