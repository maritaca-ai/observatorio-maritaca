import argparse
import hashlib
import json
import os
import re
import string
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean
from typing import Any, Dict, List, Optional

import httpx
import wandb
from openai import OpenAI
from tqdm import tqdm


# ENADE-QA (BRACIS 2026, Silveira et al.): 716 health-sciences ENADE questions,
# 2013-2023, all text-only. Pinned to a commit of the authors' repo.
DATA_COMMIT = "91674bb98f2e04f812b7c157e81362950e0f9eca"
DATA_URL = (
    f"https://raw.githubusercontent.com/H2IA/ENADE-QA/{DATA_COMMIT}/"
    "enade_mcqa_hf/data/enade_mcqa_unique_clean.jsonl"
)
DATA_SHA256 = "6afd6945a3f71d637515020f8d067519f7fa5b8f70b7dcb9895b43ad506caec4"
DATA_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "enade_qa.jsonl")

# Prompt S1 of the paper (zero-shot generation), copied from prompts/default.yaml.
SYSTEM_TEMPLATE = (
    "Você é um especialista em questões do ENADE (Exame Nacional de Desempenho dos Estudantes),\n"
    "abrangendo ciências da saúde como medicina, enfermagem, farmácia, fisioterapia, nutrição,\n"
    "odontologia, fonoaudiologia, psicologia e biomedicina, além de formação geral.\n"
    "Analise cuidadosamente todas as alternativas antes de escolher.\n"
    "Responda APENAS com a letra da alternativa correta ({valid_letters}).\n"
    "Não inclua explicações, ponto final ou qualquer outro texto."
)
INSTRUCTION_TEMPLATE = (
    "Leia a questão do ENADE abaixo e escolha a alternativa correta ({valid_letters}).\n"
    'Responda no formato exato: "Resposta: X" — sem mais texto.'
)

MAX_ATTEMPTS = 3


def load_questions(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    if not os.path.exists(DATA_CACHE):
        os.makedirs(os.path.dirname(DATA_CACHE), exist_ok=True)
        with urllib.request.urlopen(DATA_URL, timeout=60) as resp:
            raw = resp.read()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != DATA_SHA256:
            raise SystemExit(f"ENADE-QA checksum mismatch: {digest} != {DATA_SHA256}")
        with open(DATA_CACHE, "wb") as f:
            f.write(raw)

    questions: List[Dict[str, Any]] = []
    with open(DATA_CACHE, encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            # 4-option questions carry an empty 5th option
            options = [o for o in doc["options"] if o.strip()]
            assert len(options) == doc["n_options"], doc["id"]
            questions.append(
                {
                    "id": doc["id"],
                    "question": doc["question"],
                    "options": options,
                    "answer": doc["correct_answer_letter"],
                    "year": doc["year"],
                    "area": doc["area"],
                    "question_type": doc["question_type"],
                }
            )
    if limit is not None:
        questions = questions[:limit]
    return questions


def build_messages(question: Dict[str, Any]) -> List[Dict[str, str]]:
    letters = string.ascii_uppercase[: len(question["options"])]
    alternatives = "\n".join(f"{l}) {o}" for l, o in zip(letters, question["options"]))
    user = (
        f"{INSTRUCTION_TEMPLATE.format(valid_letters='/'.join(letters))}\n\n"
        f"Questão:\n{question['question'].strip()}\n\n"
        f"Alternativas:\n{alternatives}\n\nResposta:"
    )
    return [
        {"role": "system", "content": SYSTEM_TEMPLATE.format(valid_letters=", ".join(letters))},
        {"role": "user", "content": user},
    ]


def extract_answer(text: str, valid_letters: str) -> Optional[str]:
    """Return the predicted letter, or None if none was found.

    In order: a bare letter; a letter right after "letra"/"alternativa"/"opção";
    a letter after "resposta"/"alternativa" (optionally "correta"/"correcta") and
    "é" or ":", which must end the phrase so the article in "é a mais..." is not
    read as "A"; a line opening with "X)". The paper's last fallback (the last
    lone letter anywhere) is dropped: it matches the Portuguese words "e"/"a".
    """
    text = (text or "").strip()
    if not text:
        return None
    letters = f"[{valid_letters}]"
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
    parser = argparse.ArgumentParser(description="Run the ENADE-QA evaluation")
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
                "data_commit": DATA_COMMIT,
            },
        )

    questions = load_questions(args.limit)
    print(f"Loaded {len(questions)} ENADE-QA questions")

    def evaluate_question(question: Dict[str, Any]) -> Dict[str, Any]:
        valid_letters = string.ascii_uppercase[: len(question["options"])]
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

                pred = extract_answer(response, valid_letters)
                return {
                    "id": question["id"],
                    "year": question["year"],
                    "area": question["area"],
                    "question_type": question["question_type"],
                    "gold": question["answer"],
                    "pred": pred,
                    "acc": 1.0 if pred == question["answer"] else 0.0,
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
        progress = tqdm(total=len(questions), desc="Evaluating ENADE-QA", unit="question")
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
    for key in ("year", "area", "question_type"):
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
