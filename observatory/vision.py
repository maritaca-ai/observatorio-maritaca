"""Project original visual evidence into the same static case format."""
import hashlib
import re
from pathlib import Path

TASKS = {'realworldqa', 'ocrbench'}


def image_asset(repo, output, task, image, copied, revision=None):
    path = image['arquivo']
    if not re.fullmatch(r'benchmarks/visao/' + task + r'/images/\d+\.(jpg|jpeg|png|webp)', path):
        raise ValueError('Unexpected visual input path')
    sha = image['sha256']
    if not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ValueError('Invalid image checksum')
    target = 'cases/images/' + sha + Path(path).suffix
    if revision is not None:
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('Images require a fixed repository revision')
        target = 'https://raw.githubusercontent.com/maritaca-ai/observatorio-maritaca/'+revision+'/'+path
    identity = (path, sha)
    if identity not in copied:
        raw = repo.bytes(path)
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError('Original image checksum differs: ' + path)
        if revision is None:
            destination = output/target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        copied.add(identity)
    return dict(file=target, sha256=sha, width=image['largura'], height=image['altura'])


def metadata(summary):
    labels = [('falhas_do_juiz', 'judge_failures', 'Falhas do juiz'),
              ('respostas_finais_vazias', 'empty_finals', 'Respostas finais vazias'),
              ('respostas_truncadas', 'output_truncations', 'Respostas truncadas'),
              ('falhas_de_geracao', 'generation_failures', 'Falhas de geração')]
    fields = [dict(key=key, label=label, value=summary['auditoria'][source], kind='count',
                   status='recorded', source_field='auditoria.'+source)
              for source, key, label in labels]
    return dict(audit_summary=dict(schema_version=1, fields=fields),
                metric=dict(score=summary['score'], n=summary['registros'],
                            correct=summary['acertos'],
                            confidence_interval_95=summary['intervalo_confianca_95']),
                cost=dict(usd=0, brl=None, status='deterministic_no_judge_api'))


def document(repo, output, source):
    target = 'sources/'+source
    destination = output/target
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(repo.bytes(source))
    return target
