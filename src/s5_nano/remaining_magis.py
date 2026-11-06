"""Native MAGIS aggregation and entrypoint for the shared legal phases."""
from collections import defaultdict

from .remaining_legal import evaluate

JUDGE = 'anthropic/claude-opus-4.6'


def aggregate(rows):
    """show_result.py sums points over the 24 complete examination sections."""
    if len(rows) != 74 or len({row['question_id'] for row in rows}) != 74:
        raise ValueError('Magis requires all 74 unique judgments')
    sections = defaultdict(float)
    for row in rows:
        sections['_'.join(row['question_id'].split('_')[:-2])] += row['score']
    if len(sections) != 24:
        raise ValueError('Magis requires 24 examination sections')
    native_score = sum(sections.values()) / len(sections)
    return dict(score=native_score * 10, native_score_out_of_10=native_score,
                exam_scores=dict(sections), complete_exams=24,
                approved_exams=sum(value >= 6 for value in sections.values()),
                metric_name='native_mean_exam_section_score')
