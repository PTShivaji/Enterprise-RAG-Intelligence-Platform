"""Black-box RAG evaluation against a running API.

Steps: register/login an evaluation user -> upload the sample corpus -> wait for
indexing -> run a retrieval ablation and a full generation evaluation through
``POST /api/v1/evaluation/run`` -> write JSON + CSV reports to evaluation/results/.

Only the Python standard library + httpx are used (httpx ships with the backend).

Usage (repository root, API running on :8001):
    backend\\.venv\\Scripts\\python.exe evaluation\\scripts\\run_evaluation.py
    backend\\.venv\\Scripts\\python.exe evaluation\\scripts\\run_evaluation.py --model gpt-4o-mini   # paid API!
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "datasets" / "sample_corpus"
DATASET = ROOT / "datasets" / "sample_qa.json"
RESULTS = ROOT / "results"
MIME = {".pdf": "application/pdf", ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}

# Retrieval ablation: each step adds one technique so its contribution is measurable.
ABLATION = [
    {"search_mode": "keyword", "rerank": False, "query_expansion": "none"},
    {"search_mode": "vector", "rerank": False, "query_expansion": "none"},
    {"search_mode": "hybrid", "rerank": False, "query_expansion": "none"},
    {"search_mode": "hybrid", "rerank": False, "query_expansion": "prf"},
    {"search_mode": "vector", "rerank": True, "query_expansion": "none"},
    {"search_mode": "hybrid", "rerank": True, "query_expansion": "none"},
    {"search_mode": "hybrid", "rerank": True, "query_expansion": "prf"},
]


def login(client: httpx.Client, email: str | None, password: str | None) -> None:
    if email is None:
        email = f"eval-{secrets.token_hex(4)}@example.com"
        password = f"Eval-{secrets.token_urlsafe(12)}1"
        r = client.post("/auth/register", json={"email": email, "password": password, "full_name": "Evaluation"})
        r.raise_for_status()
    r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    print(f"Authenticated as {email}")


def ingest_corpus(client: httpx.Client, timeout_s: float = 600) -> dict[str, dict]:
    docs = {}
    for path in sorted(CORPUS.iterdir()):
        r = client.post("/documents/upload", files={"file": (path.name, path.read_bytes(), MIME[path.suffix])})
        r.raise_for_status()
        docs[path.name] = r.json()["document"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        statuses = {n: client.get(f"/documents/{d['id']}/status").json() for n, d in docs.items()}
        pending = [n for n, s in statuses.items() if s["status"] in ("uploaded", "processing")]
        failed = {n: s["error_message"] for n, s in statuses.items() if s["status"] == "failed"}
        if failed:
            sys.exit(f"Ingestion failed: {failed}")
        if not pending:
            for n, d in docs.items():
                docs[n] = client.get(f"/documents/{d['id']}").json()
            print("Indexed:", ", ".join(f"{n} ({d['chunk_count']} chunks, {d['ingestion_ms']} ms)" for n, d in docs.items()))
            return docs
        time.sleep(2)
    sys.exit("Timed out waiting for ingestion")


def run(client: httpx.Client, name: str, configurations: list[dict], k: int, generate: bool, timeout_s: float,
        dataset: Path = DATASET) -> dict:
    items = json.loads(dataset.read_text(encoding="utf-8"))["items"]
    r = client.post("/evaluation/run", json={"name": name, "dataset": items, "configurations": configurations,
                                             "k": k, "generate_answers": generate})
    r.raise_for_status()
    run_id = r.json()["id"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        result = client.get(f"/evaluation/results/{run_id}").json()
        if result["status"] in ("completed", "failed"):
            if result["status"] == "failed":
                sys.exit(f"Evaluation failed: {result['error_message']}")
            return result
        time.sleep(3)
    sys.exit("Timed out waiting for evaluation")


def write_reports(stamp: str, ablation: dict, full: dict, meta: dict) -> list[Path]:
    RESULTS.mkdir(exist_ok=True)
    report = {"meta": meta, "retrieval_ablation": ablation["metrics"], "end_to_end": full["metrics"],
              "items": {"ablation": ablation["results"], "end_to_end": full["results"]}}
    json_path = RESULTS / f"{stamp}_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary_path = RESULTS / f"{stamp}_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run", "configuration", "precision@k", "recall@k", "hit@k", "mrr", "ndcg@k",
                    "retrieval_p50_ms", "retrieval_p95_ms", "faithfulness", "answer_relevance", "context_relevance",
                    "citation_precision", "citation_validity", "answer_term_recall", "abstention_accuracy",
                    "e2e_p50_ms", "e2e_p95_ms", "prompt_tokens", "completion_tokens", "cost_usd"])
        for run_name, run_data in (("ablation", ablation), ("end_to_end", full)):
            for cfg in run_data["metrics"]["configurations"]:
                mt = cfg["metrics"]
                ret, gen, lat, tok = mt["retrieval"], mt.get("generation", {}), mt["latency_ms"], mt.get("tokens", {})
                e2e = lat.get("end_to_end", {})
                w.writerow([run_name, cfg["name"], ret["precision_at_k"], ret["recall_at_k"], ret["hit_at_k"], ret["mrr"],
                            ret["ndcg_at_k"], lat["retrieval"]["p50"], lat["retrieval"]["p95"], gen.get("faithfulness"),
                            gen.get("answer_relevance"), gen.get("context_relevance"), gen.get("citation_precision"),
                            gen.get("citation_validity"), gen.get("answer_term_recall"),
                            gen.get("abstention_accuracy_on_unanswerable"), e2e.get("p50"), e2e.get("p95"),
                            tok.get("prompt_total"), tok.get("completion_total"), tok.get("cost_usd_total")])

    items_path = RESULTS / f"{stamp}_items.csv"
    with items_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["configuration", "id", "category", "question", "hit_at_k", "mrr", "recall_at_k", "retrieval_ms",
                    "insufficient_evidence", "faithfulness", "citation_precision", "answer"])
        for cfg in full["results"]:
            for row in cfg["results"]:
                w.writerow([cfg["name"], row["id"], row.get("category"), row["question"], row.get("hit_at_k"),
                            row.get("mrr"), row.get("recall_at_k"), row.get("retrieval_ms"),
                            row.get("insufficient_evidence"), row.get("faithfulness"), row.get("citation_precision"),
                            (row.get("answer") or "").replace("\n", " ")[:500]])
    return [json_path, summary_path, items_path]


def abstention_sweep(rows: list[dict]) -> list[dict]:
    """Trade-off curve for the local answerer's abstention threshold.

    For each candidate threshold t: answer_rate = share of answerable questions whose
    answerability score >= t; abstention_accuracy = share of unanswerable questions
    whose score < t (or that retrieval already rejected, score None).
    """
    scored = [(r["answerable"], r.get("answerability")) for r in rows if "answer" in r]
    answerable = [s for a, s in scored if a]
    unanswerable = [s for a, s in scored if not a]
    curve = []
    for i in range(-16, 13):
        t = i / 2
        ans = sum(1 for s in answerable if s is not None and s >= t) / len(answerable) if answerable else None
        abst = sum(1 for s in unanswerable if s is None or s < t) / len(unanswerable) if unanswerable else None
        curve.append({"threshold": t, "answer_rate": round(ans, 4) if ans is not None else None,
                      "abstention_accuracy": round(abst, 4) if abst is not None else None,
                      "balanced": round((ans + abst) / 2, 4) if ans is not None and abst is not None else None})
    return curve


def print_table(title: str, configs: list[dict], generation: bool) -> None:
    print(f"\n{title}")
    head = f"{'configuration':<22}{'P@k':>7}{'R@k':>7}{'Hit@k':>7}{'MRR':>7}{'nDCG':>7}{'p50 ms':>9}"
    if generation:
        head += f"{'Faith':>7}{'AnsRel':>8}{'CitPrec':>9}{'Abst':>6}{'e2e p50':>9}"
    print(head)
    for c in configs:
        r, lat = c["metrics"]["retrieval"], c["metrics"]["latency_ms"]
        line = (f"{c['name']:<22}{r['precision_at_k']:>7.3f}{r['recall_at_k']:>7.3f}{r['hit_at_k']:>7.3f}"
                f"{r['mrr']:>7.3f}{r['ndcg_at_k']:>7.3f}{lat['retrieval']['p50']:>9.1f}")
        if generation:
            g = c["metrics"]["generation"]
            fmt = lambda v, w=7: f"{v:>{w}.3f}" if isinstance(v, (int, float)) else f"{'n/a':>{w}}"  # noqa: E731
            line += (fmt(g["faithfulness"]) + fmt(g["answer_relevance"], 8) + fmt(g["citation_precision"], 9)
                     + fmt(g["abstention_accuracy_on_unanswerable"], 6) + f"{lat['end_to_end']['p50']:>9.1f}")
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8001/api/v1")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--model", default="local", help="LLM for the end-to-end run (default: local, free)")
    parser.add_argument("--skip-ablation", action="store_true")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--dataset", type=Path, default=DATASET, help="QA dataset JSON (default: sample_qa.json)")
    args = parser.parse_args()
    dataset = args.dataset.resolve()

    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        health = client.get("/health/ready").json()
        if health["status"] == "not_ready":
            sys.exit(f"API not ready: {health}")
        login(client, args.email, args.password)
        docs = ingest_corpus(client)
        models = client.get("/models").json()
        models.pop("llm_configured_providers", None)  # local environment detail; not part of the report
        client.put("/settings", json={"llm_model": args.model}).raise_for_status()

        started = time.time()
        ablation = {"metrics": {"configurations": []}, "results": []}
        if not args.skip_ablation:
            ablation = run(client, "retrieval-ablation", ABLATION, args.k, generate=False, timeout_s=args.timeout,
                           dataset=dataset)
            print_table(f"Retrieval ablation (k={args.k})", ablation["metrics"]["configurations"], generation=False)
        full = run(client, f"end-to-end-{args.model}", [{"search_mode": "hybrid", "rerank": True,
                                                         "query_expansion": "none", "llm_model": args.model}],
                   args.k, generate=True, timeout_s=args.timeout, dataset=dataset)
        print_table(f"End-to-end (model={args.model})", full["metrics"]["configurations"], generation=True)

        curve = abstention_sweep(full["results"][0]["results"]) if args.model == "local" else []
        if curve:
            print("\nAbstention calibration (local answerer, cross-encoder sentence logit)")
            print(f"{'threshold':>10}{'answer_rate':>13}{'abstain_acc':>13}{'balanced':>10}")
            for p in curve[::2]:
                print(f"{p['threshold']:>10.1f}{p['answer_rate']:>13.3f}{p['abstention_accuracy']:>13.3f}{p['balanced']:>10.3f}")
        full["metrics"]["abstention_calibration"] = curve

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ("" if dataset == DATASET else f"_{dataset.stem}")
        meta = {
            "timestamp": stamp,
            "dataset": json.loads(dataset.read_text(encoding="utf-8"))["name"],
            "corpus": {n: {"chunks": d["chunk_count"], "pages": d["page_count"], "ingestion_ms": d["ingestion_ms"]}
                       for n, d in docs.items()},
            "models": models,
            "llm_model": args.model,
            "k": args.k,
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "processor": platform.processor(), "client": "run_evaluation.py"},
            "wall_clock_s": round(time.time() - started, 1),
            "scope": "Local deterministic metrics (see backend/app/evaluation/metrics.py). Faithfulness and "
                     "relevance are lexical/embedding proxies, not LLM-judged scores.",
        }
        for path in write_reports(stamp, ablation, full, meta):
            print("Wrote", path.relative_to(ROOT.parent))


if __name__ == "__main__":
    main()
