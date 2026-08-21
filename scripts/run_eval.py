"""Script đánh giá chất lượng RAG trên golden set.

Chạy:
    python scripts/run_eval.py                    # cả 2 mode (ablation agent vs stuff)
    python scripts/run_eval.py --mode agent       # chỉ 1 mode
    python scripts/run_eval.py --judge            # thêm LLM-judge chấm correctness/faithfulness
    python scripts/run_eval.py --out eval/results.json

Metrics:
- Retrieval:  Recall@k, MRR (gold_chunks có xuất hiện trong top-k không)
- Answer:     token-F1 so reference (factoid/multi_hop)
- Grounding:  citation precision (% citation trỏ đúng chunk gold)
- Anti-hallucination: refusal accuracy trên câu unanswerable
- Agent:      số lượt gọi tool trung bình mỗi câu
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from chakra_rag.service.rag_service import RagService  # noqa: E402

REFUSAL_MARKERS = [
    "không có thông tin",
    "không tìm thấy",
    "không có trong tài liệu",
    "chưa có thông tin",
    "không đề cập",
    "không được cung cấp",
]


def load_golden(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"]


def resolve_gold_chunk_ids(service: RagService, gold_specs: list[dict]) -> set[str]:
    """Resolve gold spec {doc, contains} → chunk_id thực tế trong DB."""
    ids: set[str] = set()
    rows = service.store.conn.execute("SELECT chunk_id, doc, text FROM chunks").fetchall()
    for spec in gold_specs:
        for row in rows:
            if row["doc"] == spec["doc"] and spec["contains"] in row["text"]:
                ids.add(row["chunk_id"])
    return ids


def token_f1(prediction: str, reference: str) -> float:
    """Token F1 đơn giản (whitespace token) — đủ cho câu factoid tiếng Việt."""
    pred_tokens = set(re.findall(r"[\w.]+", prediction.lower()))
    ref_tokens = set(re.findall(r"[\w.]+", reference.lower()))
    if not pred_tokens or not ref_tokens:
        return 0.0
    common = pred_tokens & ref_tokens
    if not common:
        return 0.0
    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def is_refusal(answer: str) -> bool:
    answer_lower = answer.lower()
    return any(marker in answer_lower for marker in REFUSAL_MARKERS)


def llm_judge(service: RagService, case: dict, payload: dict) -> dict:
    """LLM-judge chấm correctness + faithfulness theo rubric (1-5).

    Chỉ chạy khi --judge; chi phí thêm 1 LLM call mỗi case.
    """
    from langchain_openai import ChatOpenAI

    cfg = service.cfg
    llm = ChatOpenAI(
        model=cfg.llm_model, base_url=cfg.llm_base_url,
        api_key=cfg.llm_api_key or "not-needed", temperature=0,
    )
    context = "\n\n".join(
        f"[{c['chunk_id']}] {c['text']}" for c in payload["citations"]
    ) or "(không có citation)"
    prompt = f"""Bạn là giám khảo đánh giá câu trả lời của hệ thống RAG. Chấm hai tiêu chí, mỗi tiêu chí 1-5 điểm, chỉ trả JSON.

Tiêu chí:
- correctness: câu trả lời đúng so với đáp án tham khảo đến mức nào (5 = đúng hoàn toàn các ý chính).
- faithfulness: mọi khẳng định trong câu trả lời có được đoạn tài liệu dưới đây đỡ không (5 = hoàn toàn grounded, 1 = bịa đặt nhiều).

Câu hỏi: {case['question']}
Đáp án tham khảo: {case['reference_answer']}
Câu trả lời: {payload['answer']}
Tài liệu được cite:
{context}

Trả lời đúng format: {{"correctness": <int>, "faithfulness": <int>, "note": "<ngắn>"}}"""
    response = llm.invoke(prompt)
    text = str(response.content)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"correctness": None, "faithfulness": None, "note": "judge parse failed"}


def evaluate_case(service: RagService, case: dict, mode: str, judge: bool) -> dict:
    payload = service.ask(case["question"], mode=mode)
    gold_ids = resolve_gold_chunk_ids(service, case["gold_chunks"])
    retrieved_ids = [
        cid
        for t in payload["search_trace"]
        for cid in t["chunk_ids"]
    ]

    # Retrieval metrics
    if gold_ids:
        hits = [i for i, cid in enumerate(retrieved_ids) if cid in gold_ids]
        recall = len(set(hits)) / len(gold_ids) if gold_ids else 0.0
        rr = 1.0 / (hits[0] + 1) if hits else 0.0
    else:
        recall, rr = None, None  # unanswerable: không có gold để tính

    cited_ids = [c["chunk_id"] for c in payload["citations"]]
    citation_precision = (
        len(set(cited_ids) & gold_ids) / len(set(cited_ids)) if cited_ids and gold_ids else None
    )

    result = {
        "id": case["id"],
        "type": case["type"],
        "mode": mode,
        "question": case["question"],
        "answer": payload["answer"],
        "recall_at_k": recall,
        "reciprocal_rank": rr,
        "token_f1": token_f1(payload["answer"], case["reference_answer"])
        if case["type"] != "unanswerable"
        else None,
        "citation_precision": citation_precision,
        "refused": is_refusal(payload["answer"]),
        "refusal_correct": is_refusal(payload["answer"]) if case["type"] == "unanswerable" else None,
        "n_tool_calls": payload["search_trace"] and len(payload["search_trace"]) or 0,
        "low_confidence": payload["low_confidence"],
        "invalid_citations": payload["invalid_citations"],
        "unsupported_claims": payload["unsupported_claims"],
    }
    if judge:
        result["judge"] = llm_judge(service, case, payload)
    return result


def summarize(results: list[dict]) -> dict:
    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 3) if values else None

    answerable = [r for r in results if r["type"] != "unanswerable"]
    unanswerable = [r for r in results if r["type"] == "unanswerable"]
    return {
        "n_cases": len(results),
        "recall_at_k": mean([r["recall_at_k"] for r in answerable]),
        "mrr": mean([r["reciprocal_rank"] for r in answerable]),
        "token_f1": mean([r["token_f1"] for r in answerable]),
        "citation_precision": mean([r["citation_precision"] for r in answerable]),
        "refusal_accuracy": mean([1.0 if r["refusal_correct"] else 0.0 for r in unanswerable]),
        "avg_tool_calls": mean([r["n_tool_calls"] for r in results]),
        "n_invalid_citations": sum(len(r["invalid_citations"]) for r in results),
        "n_unsupported_claims": sum(len(r["unsupported_claims"]) for r in results),
    }


def print_report(all_results: dict[str, list[dict]]) -> None:
    for mode, results in all_results.items():
        summary = summarize(results)
        print(f"\n{'=' * 60}\nMODE: {mode}\n{'=' * 60}")
        print(f"{'case':<28} {'type':<13} {'R@k':>5} {'RR':>5} {'F1':>5} {'citeP':>6} {'tools':>5}")
        for r in results:
            fmt = lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else "  - "  # noqa: E731
            print(
                f"{r['id']:<28} {r['type']:<13} "
                f"{fmt(r['recall_at_k']):>5} {fmt(r['reciprocal_rank']):>5} "
                f"{fmt(r['token_f1']):>5} {fmt(r['citation_precision']):>6} "
                f"{r['n_tool_calls']:>5}"
            )
            if r["refusal_correct"] is not None:
                mark = "✓ từ chối đúng" if r["refusal_correct"] else "✗ KHÔNG từ chối (hallucination risk)"
                print(f"{'':<28} {mark}")
        print("\nTổng hợp:")
        for key, value in summary.items():
            print(f"  {key:<24} {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Đánh giá RAG trên golden set")
    parser.add_argument("--golden", default=str(PROJECT_ROOT / "eval" / "golden.json"))
    parser.add_argument("--mode", choices=["agent", "stuff", "both"], default="both")
    parser.add_argument("--judge", action="store_true", help="Chạy thêm LLM-judge (tốn thêm LLM call)")
    parser.add_argument("--out", default=None, help="Lưu kết quả chi tiết ra file JSON")
    args = parser.parse_args()

    service = RagService()
    cases = load_golden(Path(args.golden))
    modes = ["agent", "stuff"] if args.mode == "both" else [args.mode]

    all_results: dict[str, list[dict]] = {}
    for mode in modes:
        print(f"\nĐang chạy eval mode={mode} trên {len(cases)} câu hỏi...")
        results = []
        for case in cases:
            print(f"  • {case['id']}")
            results.append(evaluate_case(service, case, mode, judge=args.judge))
        all_results[mode] = results

    print_report(all_results)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(
            json.dumps(
                {mode: {"summary": summarize(rs), "cases": rs} for mode, rs in all_results.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nĐã lưu kết quả chi tiết → {out_path}")

    service.close()


if __name__ == "__main__":
    main()
