import argparse
import hashlib
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean
from typing import Any, Dict, List, Optional

import httpx
import wandb
from openai import OpenAI
from tqdm import tqdm

from judge_prompt import EVALUATION_SCHEMA, JUDGE_INSTRUCTIONS, build_evaluation_prompt


# BLUEX v2 (BRACIS 2026, Santos et al.): open-ended second-phase Unicamp/Fuvest
# questions, 2022-2025, graded by a Sabiá-4 judge against binary rubric criteria.
# data/bluex_v2_text.jsonl is the image-free subset (173 questions, 395
# subquestions) of Tropic-AI/BLUEX-v2 @ 9284b8cc1bf97abe9eb99bc915e6d390b560fe39
# (data/train-00000-of-00001.parquet, sha256
# 9f976ddeabeb1d223043f2529024c866a7e98b62547393230d47010c810320d6): the paper's
# 39 subquestions whose official answer contains an image are dropped, and so is
# every question with an image.
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bluex_v2_text.jsonl")
DATA_SHA256 = "3bdd4f2d5ff8d016ec55d3aa8bc909dc0c00a8a78a0cbc165dc3b2df955b98a9"

JUDGE_API_BASE = "https://chat.maritaca.ai/api"
JUDGE_MODEL = "sabia-4"

MAX_ATTEMPTS = 3
# Above this the judge itself is broken (key, outage) and the score means nothing.
MAX_JUDGE_ERROR_RATE = 0.10


def build_inference_prompt(
    question_text: str,
    previous_subquestions_context: str,
    target_label: str,
    target_text: str,
) -> str:
    """Copied from extras/inference/generate_inferences.py of the paper's code."""
    context_block = ""
    if previous_subquestions_context.strip():
        context_block = (
            "SUBQUESTOES ANTERIORES (conteúdo e respostas para contexto):\n"
            f"{previous_subquestions_context}\n\n"
        )

    return (
        "Você é um candidato de alto desempenho respondendo uma questão discursiva de vestibular.\n"
        "Responda de forma completa, precisa e objetiva, utilizando o vocabulário técnico adequado ao tema.\n\n"
        "ENUNCIADO DA QUESTÃO:\n"
        f"{question_text}\n\n"
        f"{context_block}"
        "SUBQUESTÃO A RESPONDER:\n"
        f"Item {target_label}: {target_text}\n\n"
        "Escreva sua resposta abaixo. Seja direto, completo e preciso.\n"
        "RESPOSTA:"
    )


def load_questions(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return questions with their subquestions in exam order."""
    with open(DATA_FILE, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != DATA_SHA256:
        raise SystemExit(f"BLUEX v2 checksum mismatch: {digest} != {DATA_SHA256}")

    with open(DATA_FILE, encoding="utf-8") as f:
        questions = [json.loads(line) for line in f]
    if limit is not None:
        questions = questions[:limit]
    return questions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BLUEX v2 evaluation")
    parser.add_argument("--model-name", required=True, help="Model name to evaluate")
    parser.add_argument("--api-url", default=None, help="Base URL for the API")
    parser.add_argument("--api-key", default=None, help="API key to authenticate requests")
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="reasoning_effort forwarded to the API (e.g. low, medium, high)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature. Omitted from the request if not set (API default).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="max_tokens per completion. Omitted from the request if not set.",
    )
    parser.add_argument(
        "--judge-api-key",
        default=os.environ.get("MARITACA_API_KEY"),
        help="Maritaca API key for the Sabiá-4 judge (default: $MARITACA_API_KEY)",
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=20,
        help="Number of parallel requests (questions are generated in parallel, "
        "their subquestions sequentially).",
    )
    parser.add_argument(
        "--wandb-project",
        default="evaluations",
        help="Weights & Biases project where results will be logged.",
    )
    parser.add_argument(
        "--wandb-entity",
        default=None,
        help="Weights & Biases entity where results will be logged.",
    )
    parser.add_argument("--wandb-run-id", default=None, help="Weights & Biases run ID.")
    parser.add_argument(
        "--no-wandb",
        action="store_true",
        help="Skip Weights & Biases logging (local testing).",
    )
    parser.add_argument(
        "--save-generations",
        type=str,
        default=None,
        help="Directory to save generations and judgments as JSONL files.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=1800,
        help="Per-request timeout in seconds for the OpenAI client (default: 1800)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate only the first N questions (smoke tests).",
    )
    args = parser.parse_args()
    if not args.no_wandb and not args.wandb_run_id:
        parser.error("--wandb-run-id is required unless --no-wandb is set")
    if not args.judge_api_key:
        parser.error("--judge-api-key or MARITACA_API_KEY is required for the Sabiá-4 judge")
    return args


def main() -> None:
    args = parse_args()

    client_kwargs: Dict[str, Any] = {"timeout": httpx.Timeout(args.request_timeout)}
    if args.api_url:
        client_kwargs["base_url"] = args.api_url
    if args.api_key:
        client_kwargs["api_key"] = args.api_key
    client = OpenAI(**client_kwargs)
    judge_client = OpenAI(
        base_url=JUDGE_API_BASE,
        api_key=args.judge_api_key,
        timeout=httpx.Timeout(args.request_timeout),
    )

    if not args.no_wandb:
        wandb.init(
            project=args.wandb_project,
            entity=args.wandb_entity,
            id=args.wandb_run_id,
            resume="allow",
            config={
                "model_name": args.model_name,
                "api_url": args.api_url,
                "reasoning_effort": args.reasoning_effort,
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
                "judge_model": JUDGE_MODEL,
                "data_sha256": DATA_SHA256,
            },
        )

    questions = load_questions(args.limit)
    n_sub = sum(len(q["subquestions"]) for q in questions)
    print(f"Loaded {len(questions)} BLUEX v2 questions ({n_sub} subquestions)")

    def generate(prompt: str) -> Dict[str, Any]:
        request_kwargs: Dict[str, Any] = {
            "model": args.model_name,
            "messages": [{"role": "user", "content": prompt}],
        }
        if args.temperature is not None:
            request_kwargs["temperature"] = args.temperature
        if args.max_tokens is not None:
            request_kwargs["max_tokens"] = args.max_tokens
        if args.reasoning_effort:
            request_kwargs["reasoning_effort"] = args.reasoning_effort

        last_error: Optional[Exception] = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                completion = client.chat.completions.create(**request_kwargs)
                choice = completion.choices[0]
                response = choice.message.content or ""
                if not response.strip() and attempt < MAX_ATTEMPTS - 1:
                    print(f"Empty content (finish_reason={choice.finish_reason}); retrying")
                    continue
                return {"response": response, "finish_reason": choice.finish_reason, "error": None}
            except Exception as err:  # noqa: BLE001 - recorded and scored 0, as in the paper
                print(err)
                last_error = err
        return {"response": None, "finish_reason": None, "error": str(last_error)}

    def answer_question(question: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Later items see the earlier items and the model's own answers to them.
        results: List[Dict[str, Any]] = []
        context_lines: List[str] = []
        for sub in question["subquestions"]:
            prompt = build_inference_prompt(
                question_text=question["question_text"],
                previous_subquestions_context="\n\n".join(context_lines),
                target_label=sub["label"],
                target_text=sub["text"],
            )
            gen = generate(prompt)
            results.append({"question": question, "sub": sub, "prompt": prompt, **gen})
            context_lines.append(f"Item {sub['label']}: {sub['text']}")
            context_lines.append(
                f"Resposta dada para o item {sub['label']}: {gen['response'] or '(nao disponivel)'}"
            )
        return results

    def judge(item: Dict[str, Any]) -> Dict[str, Any]:
        question, sub = item["question"], item["sub"]
        record = {
            "id": sub["id"],
            "question_id": question["question_id"],
            "university": question["university"],
            "year": question["year"],
            "subject": question["subject"],
            "prompt": item["prompt"],
            "response": item["response"],
            "finish_reason": item["finish_reason"],
            "generation_error": item["error"],
            "judge_error": None,
        }
        if item["error"] or not (item["response"] or "").strip():
            return {**record, "criteria_checks": [], "score": 0.0}

        prompt = build_evaluation_prompt(
            question_text=question["question_text"],
            subquestion_label=sub["label"],
            subquestion_text=sub["text"],
            expected_answer=sub["expected_answer"],
            criteria_list=sub["criteria"],
            model_name=args.model_name,
            student_answer=item["response"],
        )
        last_error: Optional[Exception] = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = judge_client.responses.create(
                    model=JUDGE_MODEL,
                    instructions=JUDGE_INSTRUCTIONS,
                    input=prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "evaluation_result",
                            "schema": EVALUATION_SCHEMA,
                        }
                    },
                )
                parsed = json.loads(response.output_text)
                break
            except Exception as err:  # noqa: BLE001 - retried, then scored 0 as in the paper
                print(f"Judge error for {sub['id']}: {err}")
                last_error = err
                time.sleep(2 ** attempt)
        else:
            # As in the paper's code: every criterion counts as not met.
            checks = [
                {"criterion": c, "is_met": False, "justification": "", "echoed": False}
                for c in sub["criteria"]
            ]
            return {**record, "criteria_checks": checks, "score": 0.0, "judge_error": str(last_error)}

        # As in the paper's code: a criterion the judge does not echo back counts as not met.
        by_criterion = {
            str(c.get("criterion", "")).strip(): c for c in parsed.get("criteria_checks", [])
        }
        checks = [
            {
                "criterion": criterion,
                "is_met": bool(by_criterion.get(criterion, {}).get("is_met", False)),
                "justification": by_criterion.get(criterion, {}).get("justification", ""),
                "echoed": criterion in by_criterion,
            }
            for criterion in sub["criteria"]
        ]
        score = 10.0 * sum(c["is_met"] for c in checks) / len(checks)
        return {**record, "criteria_checks": checks, "score": score}

    generations: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
        futures = [executor.submit(answer_question, q) for q in questions]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Generating BLUEX v2"):
            generations.extend(future.result())

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
        futures = [executor.submit(judge, g) for g in generations]
        try:
            for future in tqdm(as_completed(futures), total=len(futures), desc="Judging BLUEX v2"):
                results.append(future.result())
        except Exception as exc:  # noqa: BLE001 - need to abort execution
            executor.shutdown(cancel_futures=True)
            raise SystemExit(f"Stopping evaluation: {exc}") from exc
    results.sort(key=lambda r: r["id"])

    metrics: Dict[str, Any] = {
        "score": mean(r["score"] for r in results),
        "generation_error_rate": mean(1.0 if r["generation_error"] else 0.0 for r in results),
        "judge_error_rate": mean(1.0 if r["judge_error"] else 0.0 for r in results),
        "criteria_not_echoed_rate": mean(
            0.0 if c["echoed"] else 1.0 for r in results for c in r["criteria_checks"]
        ),
        "num_questions": len(questions),
        "num_subquestions": len(results),
    }
    for key in ("university", "year"):
        groups: Dict[Any, List[float]] = defaultdict(list)
        for r in results:
            groups[r[key]].append(r["score"])
        for value, scores in sorted(groups.items()):
            metrics[f"score_{key}_{value}"] = mean(scores)

    print(json.dumps(metrics, indent=2))

    if args.save_generations:
        os.makedirs(args.save_generations, exist_ok=True)
        with open(os.path.join(args.save_generations, "generations.jsonl"), "w") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(os.path.join(args.save_generations, "metrics.json"), "w") as f:
            json.dump(metrics, f, indent=2)

    if metrics["judge_error_rate"] > MAX_JUDGE_ERROR_RATE:
        raise SystemExit(
            f"Judge failed on {metrics['judge_error_rate']:.1%} of subquestions "
            f"(> {MAX_JUDGE_ERROR_RATE:.0%}); not logging the score."
        )

    if not args.no_wandb:
        wandb.log(metrics)
        wandb.finish()


if __name__ == "__main__":
    main()
