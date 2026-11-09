"""Paired agreement; tasks, not criteria, are the bootstrap unit."""
from itertools import combinations
import math

import numpy as np
from scipy import stats


def finite(value):
    value = float(value)
    return value if math.isfinite(value) else None


def binary(a, b):
    a, b = np.asarray(a, dtype=int), np.asarray(b, dtype=int)
    cm = np.bincount(a*2+b, minlength=4).reshape(2, 2)
    agreement = float((a == b).mean())
    expected = a.mean()*b.mean()+(1-a.mean())*(1-b.mean())
    denominator = np.sqrt(float(cm.sum(axis=0).prod())*float(cm.sum(axis=1).prod()))
    return {'n': len(a), 'agreement': agreement, 'disagreements': int((a != b).sum()),
            'kappa': finite((agreement-expected)/(1-expected)) if expected != 1 else None,
            'phi': finite((float(cm[0, 0])*cm[1, 1]-float(cm[0, 1])*cm[1, 0])/denominator) if denominator else None,
            'a_met_rate': float(a.mean()), 'b_met_rate': float(b.mean()),
            'confusion_rows_a_columns_b_UNMET_MET': cm.tolist()}


def scores(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    variable = len(a) >= 2 and np.ptp(a) > 0 and np.ptp(b) > 0
    return {'n': len(a), 'pearson_r': finite(stats.pearsonr(a, b).statistic) if variable else None,
            'spearman_rho': finite(stats.spearmanr(a, b).statistic) if variable else None,
            'a_mean': float(a.mean()), 'b_mean': float(b.mean()),
            'b_minus_a_pp': float((b-a).mean()), 'mae_pp': float(np.abs(b-a).mean()),
            'rmse_pp': float(np.sqrt(np.mean((b-a)**2)))}


def correlation_rows(a, b):
    a, b = a-a.mean(axis=1, keepdims=True), b-b.mean(axis=1, keepdims=True)
    with np.errstate(invalid='ignore', divide='ignore'):
        return (a*b).sum(axis=1)/np.sqrt((a*a).sum(axis=1)*(b*b).sum(axis=1))


def interval(values):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    return [float(v) for v in np.percentile(values, [2.5, 97.5])] if len(values) else None


def compare_pair(a, b, *, bootstrap=10000, seed=20261106, exclude_flags=False):
    if not a['complete'] or not b['complete']:
        raise ValueError('Both judge summaries must be complete')
    ar = {r['report_id']: r for r in a['reports']}
    br = {r['report_id']: r for r in b['reports']}
    if not ar or ar.keys() != br.keys():
        raise ValueError('Judges evaluated different reports')
    for rid in ar:
        if any(ar[rid][key] != br[rid][key] for key in ('text_sha256', 'case_id', 'generator')):
            raise ValueError('Judges evaluated different report text or identity')
    ap = {(p['report_id'], p['criterion_index']): p for p in a['pairs']}
    bp = {(p['report_id'], p['criterion_index']): p for p in b['pairs']}
    if ap.keys() != bp.keys():
        raise ValueError('Judges evaluated different criteria')
    for key in ap:
        if ap[key]['criterion'] != bp[key]['criterion']:
            raise ValueError('Rubric differs across judges')
    ids = sorted(rid for rid in ar if not exclude_flags or not (ar[rid].get('flags') or br[rid].get('flags')))
    if not ids:
        raise ValueError('No reports remain after exclusions')
    selected = set(ids)
    keys = sorted(k for k in ap if k[0] in selected)
    av = [int(ap[k]['criterion_status'] == 'MET') for k in keys]
    bv = [int(bp[k]['criterion_status'] == 'MET') for k in keys]
    ax = [ar[rid]['score'] for rid in ids]
    bx = [br[rid]['score'] for rid in ids]
    result = {'judge_a': a['judge'], 'judge_b': b['judge'], 'binary': binary(av, bv), 'scores': scores(ax, bx)}
    result['by_generator'] = {g: {
        'scores': scores([ar[r]['score'] for r in ids if ar[r]['generator'] == g],
                         [br[r]['score'] for r in ids if ar[r]['generator'] == g]),
        'binary': binary([v for k, v in zip(keys, av) if ar[k[0]]['generator'] == g],
                         [v for k, v in zip(keys, bv) if ar[k[0]]['generator'] == g])}
        for g in sorted({ar[r]['generator'] for r in ids})}
    result['by_criterion_sign'] = {}
    for positive in (True, False):
        positions = [i for i, k in enumerate(keys) if (ap[k]['criterion']['weight'] > 0) == positive]
        if positions:
            result['by_criterion_sign']['positive' if positive else 'negative'] = binary(
                [av[i] for i in positions], [bv[i] for i in positions])
    tasks = sorted({ar[rid]['case_id'] for rid in ids})
    winner_agreement = []
    for task in tasks:
        sub = [r for r in ids if ar[r]['case_id'] == task]
        if len(sub) < 2:
            continue
        aw = {ar[r]['generator'] for r in sub if ar[r]['score'] == max(ar[x]['score'] for x in sub)}
        bw = {br[r]['generator'] for r in sub if br[r]['score'] == max(br[x]['score'] for x in sub)}
        winner_agreement.append({'case_id': task, 'a_winners': sorted(aw), 'b_winners': sorted(bw), 'agree': aw == bw})
    result['winner_agreement'] = winner_agreement
    result['excluded_report_ids'] = sorted(set(ar)-set(ids))
    result['disagreements'] = [dict(ap[k], a_status=ap[k]['criterion_status'], b_status=bp[k]['criterion_status'],
                                    a_explanation=ap[k]['explanation'], b_explanation=bp[k]['explanation'])
                               for k in keys if ap[k]['criterion_status'] != bp[k]['criterion_status']]
    if bootstrap:
        rng = np.random.default_rng(seed)
        draws = rng.integers(0, len(tasks), size=(bootstrap, len(tasks)))
        task_cms = np.asarray([np.bincount([av[i]*2+bv[i] for i, k in enumerate(keys)
            if ar[k[0]]['case_id'] == task], minlength=4) for task in tasks])
        cm = task_cms[draws].sum(axis=1).astype(float)
        total = cm.sum(axis=1)
        agreement = (cm[:, 0]+cm[:, 3])/total
        ma, mb = (cm[:, 2]+cm[:, 3])/total, (cm[:, 1]+cm[:, 3])/total
        expected = ma*mb+(1-ma)*(1-mb)
        with np.errstate(invalid='ignore', divide='ignore'):
            kappa = (agreement-expected)/(1-expected)
        # Variable cluster sizes (sensitivity subsets) require per-draw indexing.
        by_task = [[i for i, rid in enumerate(ids) if ar[rid]['case_id'] == task] for task in tasks]
        pearson, spearman, bias, mae = [], [], [], []
        for draw in draws:
            indices = [i for t in draw for i in by_task[t]]
            x, y = np.asarray(ax)[indices], np.asarray(bx)[indices]
            pearson.append(correlation_rows(x[None, :], y[None, :])[0])
            spearman.append(correlation_rows(stats.rankdata(x)[None, :], stats.rankdata(y)[None, :])[0])
            bias.append((y-x).mean())
            mae.append(np.abs(y-x).mean())
        result['task_cluster_bootstrap_95ci'] = dict(replicates=bootstrap, seed=seed, tasks=len(tasks),
            agreement=interval(agreement), kappa=interval(kappa), pearson_r=interval(pearson),
            spearman_rho=interval(spearman), b_minus_a_pp=interval(bias), mae_pp=interval(mae))
    return result


def compare(summaries, **kwargs):
    if len(summaries) < 2:
        raise ValueError('At least two judges are required')
    return [compare_pair(a, b, **kwargs) for a, b in combinations(summaries, 2)]
