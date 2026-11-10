"""Research result verification preserves signed weights and native clipping."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'benchmarks/agentico/draco/fork'))
from draco_benchmark.core import score as native_draco
sys.path.insert(0, str(ROOT/'benchmarks/agentico/researchrubrics/fork'))
from run_eval import question_score as native_researchrubrics
from verifier.verify import item_score, verify_supplemental


def row(benchmark, weights, values):
    votes = []
    for i, (weight, value) in enumerate(zip(weights, values)):
        verdict = ({'criterion_status': 'MET' if value else 'UNMET'} if benchmark == 'draco'
                   else {'score': value, 'verdict': 'Satisfied' if value else 'Not Satisfied'})
        votes.append({'indice': i, 'criterio': {'weight': weight}, 'veredito': verdict})
    return {'julgamento': {'veredito': {'criterios': votes}}}


class ResearchPublicationTests(unittest.TestCase):
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

    def test_published_population_and_scores(self):
        report = verify_supplemental(ROOT/'results')
        self.assertGreaterEqual(report['conjuntos'], 6)
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
