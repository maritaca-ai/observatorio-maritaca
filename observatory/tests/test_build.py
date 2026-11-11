"""Offline regression checks for the static result projection."""
from collections import Counter
import gzip
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from observatory.build import blob, encoded, input_blob, performance, project_response, question_identity, table_record
from observatory.repository import Repository


class ResultProjection(unittest.TestCase):
    def row(self):
        return dict(id='1', pergunta='Pergunta', contexto='Contexto', resposta='Resposta',
                    julgamento={'veredito': {'correct': True}, 'modelo': None},
                    score=100, parametros_inferencia={'temperature': 1}, total_tokens=12,
                    custo={'valor': None}, parametros_inferencia_julgamento=None,
                    total_tokens_julgamento=None, custo_julgamento={'valor': None})

    def test_score_note_comes_from_summary_without_changing_score(self):
        root=Path(__file__).resolve().parents[2]
        repo=Repository(root,from_git=True)
        self.addCleanup(repo.close)
        for benchmark in ('draco', 'researchrubrics'):
            for mode in ('instruct', 'thinking'):
                summary=repo.json(f'results/tucano2-qwen-3.7b/{benchmark}/{mode}/resumo.json')
                identity=f'tucano:{mode}:{benchmark}'
                catalog=dict(annotations={identity: {'audit_summary': {'fields': []}}},
                             audit_fields={}, benchmark_directories={benchmark: benchmark}, updated_at='test')
                record=table_record(catalog,summary,{},'tucano',mode,benchmark,'tucano2-qwen-3.7b')
                self.assertEqual(record['score_note'],summary['observacao_nota'])
                self.assertEqual(record['score'],summary['score'])
                self.assertEqual(record['score_denominator'],summary['denominador_agregado'])
                summary.pop('observacao_nota')
                plain=table_record(catalog,summary,{},'tucano',mode,benchmark,'tucano2-qwen-3.7b')
                self.assertNotIn('score_note',plain)

    def test_pairing_uses_content_not_sequential_id(self):
        first = self.row()
        second = dict(first, id='99')
        self.assertEqual(question_identity('test', first, Counter())[0],
                         question_identity('test', second, Counter())[0])
        second['pergunta'] = 'Outra pergunta'
        self.assertNotEqual(question_identity('test', first, Counter())[0],
                            question_identity('test', second, Counter())[0])
        second = dict(first, contexto='Outro contexto')
        self.assertNotEqual(question_identity('test', first, Counter())[0],
                            question_identity('test', second, Counter())[0])

    def test_repeated_questions_keep_separate_occurrences(self):
        counts = Counter()
        a = question_identity('test', self.row(), counts)[0]
        b = question_identity('test', self.row(), counts)[0]
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith(':0') and b.endswith(':1'))

    def test_failed_verdict_is_not_a_wrong_answer_filter(self):
        r = self.row()
        self.assertEqual(performance(r), 100)
        r['julgamento']['veredito'] = {'judge_error': 'timeout'}
        self.assertIsNone(performance(r))

    def test_preserves_final_native_verdict_and_unknown_costs(self):
        row = self.row()
        row['reasoning'] = 'Private chain retained in the full Git record'
        row['turnos'] = [{'turno': 0, 'mensagens_enviadas': None, 'resposta': None}]
        projected = project_response(row, 'candidate', 'thinking', {'score_individual': 'Acerto'},
                                     'results/s5-nano/test/thinking/respostas-0001.json')
        self.assertEqual(projected['final'], row['resposta'])
        self.assertEqual(json.loads(projected['judgment']['text']), row['julgamento']['veredito'])
        self.assertIsNone(projected['metadata']['custo']['valor'])
        self.assertNotIn('reasoning', projected)
        self.assertEqual(projected['turns'][0]['question'], '')

    def test_gzip_is_reproducible_and_roundtrips(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            value = {'text': 'São Paulo; contexto longo'}
            x = blob(Path(a), 'blobs', value)
            y = blob(Path(b), 'blobs', value)
            self.assertEqual(x, y)
            raw = (Path(a)/x['file']).read_bytes()
            self.assertEqual(raw, (Path(b)/y['file']).read_bytes())
            self.assertEqual(json.loads(gzip.decompress(raw)), value)
            with TemporaryDirectory() as output:
                self.assertEqual(blob(Path(output), 'blobs', value, cache=a), x)
            (Path(a)/x['file']).write_bytes(gzip.compress(b'{}'))
            with TemporaryDirectory() as output, self.assertRaises(ValueError):
                blob(Path(output), 'blobs', value, cache=a)

    def test_git_reader_needs_no_result_worktree(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['git', 'init', '-q', temp], check=True)
            (root/'result.json').write_text('{"score":100}')
            subprocess.run(['git', 'add', 'result.json'], cwd=root, check=True)
            subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Fixture'], cwd=root, check=True)
            (root/'result.json').unlink()
            reader = Repository(root, from_git=True)
            try:
                self.assertEqual(reader.json('result.json'), {'score': 100})
                for path in ['../private', '/tmp/private', 'result.json\nHEAD:other']:
                    with self.assertRaises(ValueError):
                        reader.bytes(path)
            finally:
                reader.close()
            # Local previews combine edited/new files with unchanged sparse blobs.
            (root/'result.json').write_text('{"score":75}')
            (root/'new.json').write_text('{"score":50}')
            reader = Repository(root, from_git=True, worktree_overlay=True)
            try:
                self.assertEqual(reader.json('result.json'), {'score':75})
                self.assertEqual(reader.json('new.json'), {'score':50})
                (root/'result.json').unlink()
                self.assertEqual(reader.json('result.json'), {'score':100})
            finally:
                reader.close()

    def test_long_context_sharing_preserves_exact_bytes(self):
        import base64
        from hashlib import sha256
        with TemporaryDirectory() as temp:
            output = Path(temp)
            bases = {}
            full = [{'role': 'user', 'content': 'São Paulo 🌎\n'*5000}]
            shorter = [{'role': 'user', 'content': 'São Paulo 🌎\n'*1000+'[...]'+'São Paulo 🌎\n'*900}]
            base = input_blob(output, full, bases, 'same-question')
            ref = input_blob(output, shorter, bases, 'same-question')
            delta = json.loads(gzip.decompress((output/ref['file']).read_bytes()))
            self.assertTrue(delta['_observatory_delta_v1'])
            self.assertEqual(delta['base'], base)
            raw = encoded(full)
            restored = raw[:delta['prefix']]+base64.b64decode(delta['middle'])+(raw[-delta['suffix']:] if delta['suffix'] else b'')
            self.assertEqual(restored, encoded(shorter))
            self.assertEqual(sha256(restored).hexdigest(), ref['sha256'])


if __name__ == '__main__':
    unittest.main()
