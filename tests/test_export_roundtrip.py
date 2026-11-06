"""End-to-end export of synthetic native artifacts; no inference or network."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from s5_nano.prepare import REPO, save
from s5_nano.run_all import select_jobs, complete
from s5_nano.export_results import export_run
from verifier.verify import check_group


class ExportRoundtripTests(unittest.TestCase):
    def test_native_responses_become_readable_verifiable_results(self):
        job = select_jobs(['s5-nano'], ['thinking'], ['enade_qa'])[0]
        profile = json.loads((REPO/job['profile']).read_text())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'native'
            folder = source/'results/enade_qa'
            inputs = source/'runtime/sources/maritaca-utils/benchmarks/enade_qa_bench/data'
            inputs.mkdir(parents=True)
            questions, scores = [], []
            # The full native population is preserved, with synthetic content.
            for i in range(716):
                qid = str(i)
                answer = 'A' if i % 2 == 0 else 'B'
                messages = [{'role': 'system', 'content': 'Sistema sintético'},
                            {'role': 'user', 'content': f'Pergunta sintética {i}'}]
                requested = dict(model='s5-nano', messages=messages, temperature=0)
                effective = dict(requested, **profile['sampling'], chat_template_kwargs={'enable_thinking': True})
                usage = dict(prompt_tokens=i+5, completion_tokens=1, total_tokens=i+6)
                message = dict(role='assistant', content=answer, reasoning_content='Raciocínio sintético')
                raw = dict(model='s5-nano', choices=[dict(message=message, finish_reason='stop')], usage=usage)
                save(folder/'responses'/f'{qid}.json', dict(id=qid, content=answer, raw=raw,
                     identity=dict(case=qid, request=requested)))
                wire = source/'runtime/raw_api'/f'{qid}.json.gz'
                wire.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(wire, 'wt') as stream:
                    json.dump(dict(status=200, benchmark='enade_qa', answer=message, usage=usage,
                                   effective_request=effective, request=requested, finish_reason='stop'), stream)
                questions.append(dict(id=qid, question=f'Pergunta sintética {i}', options=['A', 'B']))
                scores.append(dict(id=qid, prediction=answer, gold='A', correct=answer == 'A'))
            (inputs/'enade_qa.jsonl').write_text(''.join(json.dumps(q)+'\n' for q in questions))
            save(folder/'scored_rows.json', scores)
            save(source/'results_verified.json', dict(status='FINAL', profile=profile,
                 benchmarks={'enade_qa': {'score': 50, 'n': 716}}))
            receipts = export_run(job, source, root/'results')
            self.assertEqual(receipts[0]['score'], 50)
            destination = root/'results/s5-nano/enade-qa/thinking'
            summary = json.loads((destination/'resumo.json').read_text())
            score, count = check_group(destination, summary, 'enade-qa')
            self.assertEqual((score, count), (50, 716))
            first = json.loads((destination/summary['arquivos'][0]['arquivo']).read_text())[0]
            self.assertEqual(first['system'], 'Sistema sintético')
            self.assertEqual(first['parametros_inferencia']['temperature'], profile['sampling']['temperature'])
            self.assertEqual(first['parametros_inferencia']['origem'], 'requisicao_efetiva')
            self.assertEqual(first['total_tokens'], 6)
            self.assertEqual(first['reasoning'], 'Raciocínio sintético')
            self.assertNotIn(str(root), json.dumps(first))
            self.assertTrue(complete(job, root/'results'))
            with self.assertRaisesRegex(ValueError, 'already exist'):
                export_run(job, source, root/'results')

    def test_matrix_covers_only_supported_final_groups_once(self):
        jobs = select_jobs()
        outputs = [f'{j["model"]}/{b}/{j["mode"]}' for j in jobs for b in j['outputs']]
        reference = json.loads((REPO/'verifier/reported.json').read_text())['notas']
        self.assertEqual(set(outputs), set(reference))
        self.assertEqual(len(outputs), len(set(outputs)))
        self.assertEqual(len(jobs), 390)
        self.assertEqual(select_jobs(['lfm2.5-24b-a2b'], ['instruct']), [])
        with self.assertRaises(ValueError):
            select_jobs(['unknown-model'])


if __name__ == '__main__':
    unittest.main()
