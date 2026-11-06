import importlib.util
import unittest
from s5_nano.answers import extract_answer
from s5_nano.prepare import REPO


class AnswerTests(unittest.TestCase):
    def test_article_is_not_option_a(self):
        for text in ['Resposta: a alternativa correta é B.', 'Answer: a better choice is B.',
                     'Resposta: A ou B', 'Resposta: (B', 'Resposta: B)']:
            self.assertIsNone(extract_answer('mmlu_pt_high_school', text))

    def test_unambiguous_final_lines_and_choice_domain(self):
        for text in ['B', '(b).', 'Raciocínio sintético.\nResposta: B.', 'Answer: (B)']:
            self.assertEqual(extract_answer('global_mmlu_pt', text), 'B')
        self.assertIsNone(extract_answer('global_mmlu_pt', 'Answer: E'))
        self.assertIsNone(extract_answer('global_mmlu_pt', 'Resposta: A\nResposta: B'))
        self.assertIsNone(extract_answer('global_mmlu_pt', ''))


    def test_documented_forks_use_runtime_extractor(self):
        for benchmark in ['mmlu_pt', 'global_mmlu_pt']:
            path = REPO / 'benchmarks/provas' / benchmark / 'fork/scoring.py'
            spec = importlib.util.spec_from_file_location('fixture_scoring', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertIs(module.extract_answer, extract_answer)
