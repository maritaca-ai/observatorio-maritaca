"""Original English CulturalBench-Hard prompt and Appier conditional extraction."""
import asyncio
from collections import defaultdict
import json

from .remaining_core import definitions, save

SCORER_REVISION = 'appier_native_comparison_v3'


def native_answer_equal(prediction, gold):
    """Appier fc7f658 viz_culture_plot.py, lines 73-75; no boolean coercion."""
    return str(prediction).strip().lower() == str(gold).strip().lower()


def valid_extraction(result):
    if not isinstance(result, dict) or not isinstance(result.get('answer_extracted'), str):
        return False
    return (result.get('src') == 'llm' or
            (result.get('src') == 'rule' and result['answer_extracted'] in ('True', 'False')))


async def extract_final(run, final):
    """Keep native prompt/parsing, but don't turn transport/schema errors into scores."""
    failures = []
    async def complete(prompt):
        try:
            response = run.paid_client().chat.completions.create(model='gpt-4o-mini-2024-07-18',
                messages=[{'role': 'user', 'content': prompt}], temperature=0.0, max_tokens=256)
            content = response.choices[0].message.content
            parsed = json.loads(content)
            if not isinstance(parsed, dict) or not isinstance(parsed.get('answer'), str):
                raise ValueError('Cultural extractor requires a JSON object with a string answer')
            return content
        except Exception as exc:
            failures.append(exc)
            raise
    native = definitions(run.root / 'sources/benchmarks/extract_answer_culture.py',
                         ['prompt_extract', 'extract_answer'], {'json': json, 'chat_completion': complete})
    result = await native.extract_answer(final)
    # The pinned extractor catches Exception and returns "error". Preserve its
    # literal outputs, but rethrow observed failures before promoting a judgment.
    if failures:
        raise failures[0]
    if not valid_extraction(result):
        raise ValueError('Cultural extraction result schema changed')
    return result


def native_gold_answer(value):
    """Match the native pandas boolean CSV interpretation without changing inputs."""
    if type(value) is bool:
        return str(value)
    if isinstance(value, str) and value in ('TRUE', 'True', 'FALSE', 'False'):
        return value.title()
    raise ValueError('Invalid CulturalBench boolean gold answer')


def evaluate(run, preflight=False):
    prompt_module = definitions(run.root / 'sources/benchmarks/run_culture_bench.py', ['INSTRUCTION_PROMPTS'])
    template = prompt_module.INSTRUCTION_PROMPTS['en']
    groups = defaultdict(list)
    for row in run.rows:
        groups[row['question_idx']].append(row)
    if len(run.rows) != 4908 or len(groups) != 1227 or any(len(v) != 4 for v in groups.values()):
        raise ValueError('CulturalBench Hard option groups changed')
    gold_answers = {row['data_idx']: native_gold_answer(row['answer']) for row in run.rows}
    if preflight:
        for answer in ('True', 'False'):
            result = asyncio.run(extract_final(run, answer))
            assert result == {'answer_extracted': answer, 'src': 'rule'}
        save(run.out / 'preflight.json', dict(passed=True, n=4908, base_questions=1227, model_or_judge_calls=0))
        return
    def one(row):
        prompt = template.format(question=row['prompt_question'], option=row['prompt_option'])
        response = run.ask(row['data_idx'], [{'role': 'user', 'content': prompt}],
                           max_tokens=12000, temperature=0.6, top_p=0.95)
        final = response['final']
        if not final.strip():
            return dict(id=row['data_idx'], question=row['question_idx'], country=row['country'],
                        correct=False, empty_final=True, extraction=None)
        result = run.judgment(row['data_idx'], dict(final=final, extraction=run.manifest['protocol']['extraction']),
            lambda: asyncio.run(extract_final(run, final)), valid_extraction,
            required_model=lambda x: 'gpt-4o-mini-2024-07-18' if x.get('src') == 'llm' else None)
        return dict(id=row['data_idx'], question=row['question_idx'], country=row['country'],
                    correct=native_answer_equal(result['answer_extracted'], gold_answers[row['data_idx']]), extraction=result)
    rows = run.parallel(one)
    scored = defaultdict(list)
    for row in rows:
        scored[row['question']].append(row)
    overall = [all(r['correct'] for r in group) for group in scored.values()]
    brazil = [all(r['correct'] for r in group) for group in scored.values() if group[0]['country'] == 'Brazil']
    if len(brazil) != 25:
        raise ValueError('Brazil report population changed')
    run.finish(dict(score=100 * sum(overall) / len(overall), base_questions=1227,
                    brazil_score=100 * sum(brazil) / 25, brazil_base_questions=25,
                    metric_name='hard_all_four_correct',
                    scorer_revision=SCORER_REVISION,
                    extraction_fallbacks=sum((r.get('extraction') or {}).get('src') == 'llm' for r in rows)), rows)
