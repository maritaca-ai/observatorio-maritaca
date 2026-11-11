"""Image alignment, original scoring and sample scope must survive projection."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from observatory.build import question_identity, project_response
from observatory.repository import Repository
from observatory.vision import image_asset
from verifier.verify import check_group

ROOT = Path(__file__).resolve().parents[2]


class VisionProjection(unittest.TestCase):
    def test_same_prompt_with_different_images_is_not_paired(self):
        row = dict(pergunta='What is written?', julgamento={},
                   imagem=dict(sha256='a'*64, largura=100, altura=80))
        same = dict(row, id='another-model-id')
        other = dict(row, imagem=dict(sha256='b'*64, largura=100, altura=80))
        identity = question_identity('ocrbench', row, Counter())[0]
        self.assertEqual(identity, question_identity('ocrbench', same, Counter())[0])
        self.assertNotEqual(identity, question_identity('ocrbench', other, Counter())[0])

    def test_original_image_checksum_and_path_are_enforced(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as output:
            root = Path(directory)
            name = 'benchmarks/visao/ocrbench/images/000003.png'
            path = root/name
            path.parent.mkdir(parents=True)
            path.write_bytes(b'original image bytes')
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            image = dict(arquivo=name, sha256=sha, largura=100, altura=80)
            result = image_asset(Repository(root), Path(output), 'ocrbench', image, set())
            self.assertEqual((Path(output)/result['file']).read_bytes(), path.read_bytes())
            remote = image_asset(Repository(root), Path(output), 'ocrbench', image, set(), 'a'*40)
            self.assertEqual(remote['file'], 'https://raw.githubusercontent.com/maritaca-ai/observatorio-maritaca/'+'a'*40+'/'+name)
            self.assertEqual(remote['sha256'], sha)
            with self.assertRaises(ValueError):
                image_asset(Repository(root), Path(output), 'ocrbench', image, set(), 'main')
            with self.assertRaises(ValueError):
                image_asset(Repository(root), Path(output), 'ocrbench', dict(image, sha256='0'*64), set())
            with self.assertRaises(ValueError):
                image_asset(Repository(root), Path(output), 'ocrbench', dict(image, arquivo='../private.png'), set())

    def test_all_visual_results_recompute_from_native_answers(self):
        repo = Repository(ROOT, from_git=True, worktree_overlay=True)
        self.addCleanup(repo.close)
        catalog = repo.json('observatory/catalog.json')
        def load(path):
            return repo.json(str(Path(path).relative_to(ROOT)))
        groups = rows_count = 0
        for task in ('realworldqa','ocrbench'):
            image_inputs = {}
            folders = [f'results/{catalog["model_directories"][m["id"]]}/{task}/{mode}'
                       for m in catalog['models'] if m.get('supports_vision') is True for mode in m['modes']]
            for folder in folders:
                summary = repo.json(folder+'/resumo.json')
                score, count = check_group(ROOT/folder, summary, task, load_json=load,
                                           response_files=repo.response_files(folder))
                self.assertEqual((score, count), (summary['score'], 200))
                rows = repo.json(folder+'/respostas-0001.json')
                self.assertEqual(sum(not r['resposta'].strip() for r in rows), summary['auditoria']['respostas_finais_vazias'])
                self.assertEqual(sum(r['resposta_truncada'] for r in rows), summary['auditoria']['respostas_truncadas'])
                for row in rows:
                    value = (row['pergunta'],row['imagem'],row['julgamento']['veredito']['item_original'])
                    self.assertEqual(image_inputs.setdefault(row['id'],value), value)
                    projected = project_response(row,'test',summary['modo'],summary,'test.json')
                    self.assertEqual(projected['final'],row['resposta'])
                    self.assertEqual(projected['judgment']['kind'],'vision')
                    self.assertEqual(projected['metadata']['parametros_inferencia'],row['parametros_inferencia'])
                groups += 1
                rows_count += count
            self.assertEqual(len(image_inputs),200)
        self.assertEqual((groups,rows_count),(18,3600))


if __name__ == '__main__':
    unittest.main()
