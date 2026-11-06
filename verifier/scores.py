"""Validate the result inventory and recompute deterministic aggregate scores."""
import collections
import json
import math


def read(path):
    return json.loads(path.read_text())


def aggregate(benchmark, rows):
    verdicts = [r['julgamento']['veredito'] for r in rows]
    scores = [r['score'] for r in rows]
    if benchmark == 'arena-hard-v2':
        import numpy as np
        labels = {'A>B': [1], 'A>>B': [1]*3, 'A=B': [.5],
                  'A<B': [0], 'A<<B': [0]*3, 'B>A': [0],
                  'B>>A': [0]*3, 'B=A': [.5], 'B<A': [1], 'B<<A': [1]*3}
        values = []
        for row in sorted(rows, key=lambda r: r['ordem_agregacao']):
            j = row['julgamento']['veredito']
            games = j.get('games', [])
            if row.get('contexto_insuficiente') or j.get('model_context_exhausted') or j.get('context_zero'):
                values.extend([0, 0])
            elif len(games) == 2 and all(g and g.get('score') in labels for g in games):
                values.extend(labels[games[1]['score']])
                values.extend(1-v for v in labels[games[0]['score']])
            else:
                raise ValueError('Confronto sem veredito nem tratamento de contexto registrado')
        rng = np.random.RandomState(42)
        values = np.asarray(values, dtype=float)
        return 100 * sum(values[rng.choice(len(values), len(values), replace=True)].mean()
                         for _ in range(100)) / 100
    if benchmark == 'assin2-rte':
        pairs = [j['f1'] for j in verdicts]
        values = []
        for label in {gold for _, gold in pairs}:
            tp = sum(a == b == label for a, b in pairs)
            fp = sum(a != label and b == label for a, b in pairs)
            fn = sum(a == label and b != label for a, b in pairs)
            values.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
        return 100*sum(values)/len(values)
    if benchmark == 'culturalbench-hard':
        groups = collections.defaultdict(list)
        for j in verdicts:
            groups[j['question']].append(j['correct'])
        if len(groups) != 1227 or any(len(v) != 4 for v in groups.values()):
            raise ValueError('CulturalBench: população diferente de 1.227 perguntas × quatro opções')
        return 100*sum(all(v) for v in groups.values())/len(groups)
    if benchmark == 'structured-output-benchmark':
        return 100*sum(j['schema_compliance']*j['difficulty_weight'] for j in verdicts)/sum(j['difficulty_weight'] for j in verdicts)
    if benchmark == 'prosa-pt':
        valid = [j['evaluations'][i] for j in verdicts for i in j['selected_indices']
                 if i < len(j['evaluations']) and j['evaluations'][i] in ('YES', 'NO')]
        zeros = sum(len(j['selected_indices']) for j in verdicts if j.get('context_zero'))
        return 100*valid.count('YES')/(len(valid)+zeros)
    if benchmark in ('oab-bench', 'magis-bench'):
        sections = collections.defaultdict(float)
        for j in verdicts:
            sections['_'.join(j['question_id'].split('_')[:-2])] += j['score']
        if len(sections) != (42 if benchmark == 'oab-bench' else 24):
            raise ValueError('Benchmark jurídico: conjunto de exames/seções incompleto')
        return 10*sum(sections.values())/len(sections)
    return sum(scores)/len(scores)*(10 if benchmark == 'bluex-v2' else 1)

