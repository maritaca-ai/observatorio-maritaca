import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean
from typing import Any, Dict, List, Optional

import httpx
import wandb
from openai import OpenAI
from tqdm import tqdm


# Enem-VL (BRACIS 2026, Soares et al.), text-only subset: exams 2020-2025, no
# extracted images, annulled questions dropped (1988 questions). Built from
# dataset.json of Kaggle andersonlbsoares/enem-v-questions v4 (sha256
# 1e96064414b00ce3953502dd9aa8abd3927d66f85f47878cb736d20fd6a35eb8); the full
DATA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "enem_vl_2020_2025_text.jsonl"
)
DATA_SHA256 = "8a8b1b4db2ed4231e9eeb95108f1d25a5c4c644cf81d95efdbdac38ae3c63981"

# Prompt of the paper's baseline (graphs4ai/enem-vl-code @ b24cbac, baseline.ipynb).
ANSWER_INSTRUCTION = (
    'Retorne estritamente um JSON válido no formato {"answer":"A"}. O valor de answer '
    "deve ser somente A, B, C, D ou E. Não inclua markdown, texto extra ou justificativa."
)

AREA_SLUGS = {
    "Linguagens, Códigos e suas Tecnologias": "linguagens",
    "Ciências Humanas e suas Tecnologias": "humanas",
    "Ciências da Natureza e suas Tecnologias": "natureza",
    "Matemática e suas Tecnologias": "matematica",
}

MAX_ATTEMPTS = 3


def load_questions(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    with open(DATA_FILE, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != DATA_SHA256:
        raise SystemExit(f"Enem-VL checksum mismatch: {digest} != {DATA_SHA256}")

    with open(DATA_FILE, encoding="utf-8") as f:
        questions = [json.loads(line) for line in f]
    if limit is not None:
        questions = questions[:limit]
    return questions


def has_text(value: Optional[str]) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() != "nan"


def build_messages(question: Dict[str, Any]) -> List[Dict[str, str]]:
    parts = []
    if has_text(question["texto_apoio_externo"]):
        parts.append(f"Texto externo:\n{question['texto_apoio_externo']}")
    if has_text(question["texto_apoio_questao"]):
        parts.append(f"Texto de apoio:\n{question['texto_apoio_questao']}")
    alternatives = "\n".join(f"{letter}) {text}" for letter, text in question["alternativas"].items())
    parts.extend(
        [
            f"Pergunta:\n{question['enunciado']}",
            f"Alternativas:\n{alternatives}",
            ANSWER_INSTRUCTION,
        ]
    )
    return [{"role": "user", "content": "\n\n".join(parts)}]


def answer_from_json(text: str) -> Optional[str]:
    """The paper's JSON parser: the whole response or its first {...} block."""
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        answer = str(data.get("answer", "")).strip().upper()
        if re.fullmatch(r"[A-E]", answer):
            return answer
    return None


def extract_answer(text: str) -> Optional[str]:
    """Return the predicted letter, or None if none was found.

    JSON first, as in the paper. The paper's free-text fallback reads the article
    in "a resposta é a letra D" as "A", so free text uses the ENADE-QA bench
    patterns instead (keep the two in sync).
    """
    text = (text or "").strip()
    if not text:
        return None
    answer = answer_from_json(text)
    if answer:
        return answer
    letters = "[ABCDE]"
    end = r"(?=\**\s*(?:$|[\)\]\.\,;:/!\n]))"
    patterns = [
        rf"^\W*({letters})\W*$",
        rf"\b(?:letra|alternativa|op[çc][ãa]o)\s*:?\s*\**\(?({letters})\b",
        rf"\b(?:resposta|alternativa)(?:\s+corre(?:c)?ta)?\s*(?:é\s*:?|:)\s*\**\s*(?:a\s+)?\**\(?({letters}){end}",
        rf"^\s*\**\(?({letters})\)",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if matches:
            return matches[-1].upper()
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Enem-VL (text-only) evaluation")
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
        default=0.0,
        help="Sampling temperature (paper: 0.0).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="max_tokens per completion. Omitted from the request if not set.",
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=20,
        help="Number of parallel requests to make against the model API.",
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
        help="Directory to save generations as a JSONL file for inspection.",
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
    return args


def main() -> None:
    args = parse_args()

    client_kwargs: Dict[str, Any] = {"timeout": httpx.Timeout(args.request_timeout)}
    if args.api_url:
        client_kwargs["base_url"] = args.api_url
    if args.api_key:
        client_kwargs["api_key"] = args.api_key
    client = OpenAI(**client_kwargs)

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
                "data_sha256": DATA_SHA256,
            },
        )

    questions = load_questions(args.limit)
    print(f"Loaded {len(questions)} Enem-VL text-only questions")

    def evaluate_question(question: Dict[str, Any]) -> Dict[str, Any]:
        request_kwargs: Dict[str, Any] = {
            "model": args.model_name,
            "messages": build_messages(question),
            "temperature": args.temperature,
        }
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
                reasoning = getattr(choice.message, "reasoning", None) or ""
                if not response.strip():
                    if attempt < MAX_ATTEMPTS - 1:
                        print(
                            f"Empty content for {question['id']} "
                            f"(finish_reason={choice.finish_reason}); retrying"
                        )
                        continue
                    if reasoning.strip():
                        response = reasoning

                pred = extract_answer(response)
                return {
                    "id": question["id"],
                    "year": question["ano"],
                    "area": AREA_SLUGS[question["area"]],
                    "language": question["idioma"] or "portugues",
                    "gold": question["resposta"],
                    "pred": pred,
                    "acc": 1.0 if pred == question["resposta"] else 0.0,
                    "unknown": pred is None,
                    "finish_reason": choice.finish_reason,
                    "response": response,
                }
            except Exception as err:  # noqa: BLE001 - surface exact error to caller
                print(err)
                last_error = err
        raise RuntimeError(
            f"Failed to evaluate {question['id']} after {MAX_ATTEMPTS} retries"
        ) from last_error

    results: List[Dict[str, Any]] = []
    gen_file = None
    if args.save_generations:
        os.makedirs(args.save_generations, exist_ok=True)
        gen_file = open(os.path.join(args.save_generations, "generations.jsonl"), "w")

    with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
        futures = [executor.submit(evaluate_question, q) for q in questions]
        progress = tqdm(total=len(questions), desc="Evaluating Enem-VL", unit="question")
        try:
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - need to abort execution
                    progress.close()
                    executor.shutdown(cancel_futures=True)
                    raise SystemExit(
                        f"Stopping evaluation because a question failed after retries: {exc}"
                    ) from exc
                results.append(result)
                if gen_file:
                    gen_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                    gen_file.flush()
                progress.update(1)
        finally:
            progress.close()
            if gen_file:
                gen_file.close()

    metrics: Dict[str, Any] = {
        "acc": mean(r["acc"] for r in results),
        "unknown_rate": mean(1.0 if r["unknown"] else 0.0 for r in results),
        "num_questions": len(results),
    }
    for key in ("year", "area", "language"):
        groups: Dict[Any, List[float]] = defaultdict(list)
        for r in results:
            groups[r[key]].append(r["acc"])
        for value, accs in sorted(groups.items()):
            metrics[f"acc_{key}_{value}"] = mean(accs)

    print(json.dumps(metrics, indent=2))

    if args.save_generations:
        with open(os.path.join(args.save_generations, "metrics.json"), "w") as f:
            json.dump(metrics, f, indent=2)

    if not args.no_wandb:
        wandb.log(metrics)
        wandb.finish()


if __name__ == "__main__":
    main()
