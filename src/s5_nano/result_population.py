"""Validate benchmark-specific populations without changing native scores."""


def validate_metric_population(spec, task, metric):
    if metric.get('status') != 'FINAL' or task not in spec['tasks']:
        raise ValueError('Result is not final or task is outside the benchmark')
    protocol = spec.get('protocol', {})
    if spec['id'] == 'prosa_pt':
        expected = {
            'n': protocol['scored_conversations'],
            'generated_n': protocol['generated_conversations'],
        }
        if metric.get('aggregation_policy') == 'native_first_judgment_valid_verdicts_v1':
            expected['eligible_rubrics'] = protocol['filtered_rubrics']
            scored = metric.get('scored_rubrics')
            if (type(scored) is not int or not 0 < scored <= protocol['filtered_rubrics']
                    or metric.get('missing_verdicts') != protocol['filtered_rubrics'] - scored):
                raise ValueError('Inconsistent native Prosa verdict coverage')
        else:
            expected['scored_rubrics'] = protocol['filtered_rubrics']
    elif spec['id'] == 'capitu':
        expected = {
            'n': protocol['single_n'],
            'single_turn_n': protocol['single_n'],
            'multi_turn_n': protocol['conversations_n'],
            'total_turns': protocol['turns'],
        }
    elif spec['id'] == 'lumen':
        expected = {'n': protocol['harmful_trials'], 'benign_n': protocol['benign_trials']}
    else:
        expected = {'n': spec['expected_counts'][spec['tasks'].index(task)]}
    for field, count in expected.items():
        if metric.get(field) != count:
            raise ValueError(f'Incomplete {spec["id"]} population: {field} must be {count}')
    return expected
