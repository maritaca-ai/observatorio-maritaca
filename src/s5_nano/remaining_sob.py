"""SOB's native vLLM prompt, free decoder, extraction, serialization and scoring."""
import importlib.util
import json
import logging
import re
import sys
from types import SimpleNamespace
from typing import Any

from .remaining_core import definitions, digest, save
from .runtime_config import PROFILE


def evaluate(run, preflight=False):
    source = run.root / 'sources'
    utils = definitions(source / 'utils/utils.py', ['parse_string', 'extract_json'], dict(json=json, re=re))
    prompt = definitions(source / 'sob/common/prompts.py', ['SYSTEM_PROMPT'])
    serialization = definitions(source / 'sob/common/serialization.py', ['KNOWN_FIELDS', 'build_eval_record'],
                                dict(Any=Any, parse_string=utils.parse_string))
    module_spec = importlib.util.spec_from_file_location('sob_native_' + digest(str(source))[:12], source / 'evaluate.py')
    scorer = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = scorer
    module_spec.loader.exec_module(scorer)
    counts = {modality: sum(row['_modality'] == modality for row in run.rows) for modality in ('text', 'image', 'audio')}
    if counts != dict(text=5000, image=209, audio=115):
        raise ValueError('SOB population changed')
    config = SimpleNamespace(model_id=run.identity['model'], tensor_parallel_size=1,
        max_model_len=PROFILE['context_length'], max_tokens=2048, temperature=0,
        use_structured_decoding=False, disable_thinking=not PROFILE['enable_thinking'])
    logger = logging.getLogger('sob_native_transport')
    logger.setLevel(logging.CRITICAL)
    def one(row):
        class Endpoint:
            def __init__(self, **kwargs):
                pass
            def get_tokenizer(self):
                # The common proxy applies the verified native model template.
                return SimpleNamespace(apply_chat_template=lambda messages, **kwargs: messages)
            def generate(self, prompts, sampling_params):
                assert len(prompts) == len(sampling_params) == 1
                if preflight:
                    final = json.dumps(utils.parse_string(row['ground_truth']))
                    usage = {}
                else:
                    response = run.ask(row['_selection_id'], prompts[0], **vars(sampling_params[0]))
                    final = response['final']
                    usage = (response.get('raw') or {}).get('usage') or {}
                # Native provider only consumes the sequence lengths for usage.
                return [SimpleNamespace(prompt_token_ids=range(usage.get('prompt_tokens', 0)),
                    outputs=[SimpleNamespace(text=final, token_ids=range(usage.get('completion_tokens', 0)))])]
        native = definitions(source / 'sob/providers/vllm.py', ['run'], dict(
            LLM=Endpoint, SamplingParams=lambda **kw: SimpleNamespace(**kw), InferenceConfig=SimpleNamespace,
            SYSTEM_PROMPT=prompt.SYSTEM_PROMPT, parse_if_string=utils.parse_string, extract_json=utils.extract_json,
            tqdm=lambda rows, **kwargs: rows, logger=logger, json=json, time=__import__('time')))
        original, candidate, input_tokens, output_tokens, elapsed = native.run([row], config)[0]
        return serialization.build_eval_record(original, candidate, run.identity['model'], row['_modality'],
                                                input_tokens, output_tokens, elapsed)
    if preflight:
        for modality in counts:
            row = next(row for row in run.rows if row['_modality'] == modality)
            scored = scorer.evaluate_record(one(row), modality)
            assert scored.row['strict_json_em'] == 1 and scored.row['json_parse_success'] == 1
        save(run.out / 'preflight.json', dict(passed=True, n=5324, modalities=counts, model_or_judge_calls=0))
        return
    responses = run.parallel(one)
    summaries, scored = {}, []
    for modality in counts:
        path = run.out / (modality + '_native_responses.jsonl')
        with path.open('w') as stream:
            for row in responses:
                if row['metadata']['_modality'] == modality:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        records, quality = scorer.evaluate_file(path, modality)
        assert len(records) == counts[modality] and quality['malformed_jsonl_line_count'] == 0
        summary = scorer.build_summary(path, records, quality, bootstrap_samples=1000, seed=42,
                                       top_k_errors=20, modality=modality)
        save(run.out / (modality + '_native_summary.json'), summary)
        summaries[modality] = summary['summary']
        scored.extend(dict(modality=modality, **r.row) for r in records)
    # Native SOB reports each modality separately; the table's primary column
    # is text / weighted JSON Pass Rate, with all native metrics retained.
    primary = summaries['text']['overall_weighted']['metrics']['schema_compliance']['mean']
    run.finish(dict(score=100 * primary, metric_name='text_weighted_json_pass_rate',
                    native_summaries=summaries, modality_counts=counts, external_api_cost_usd=0), scored)
