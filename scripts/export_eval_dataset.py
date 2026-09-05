"""Xuất production traces thành dataset đánh giá trên LangSmith.

Thay thế read_all() của telemetry cũ: dataset gốc giờ sống trên LangSmith.
Usage: LANGSMITH_API_KEY=... uv run python scripts/export_eval_dataset.py \
    [--project chakra_rag] [--dataset rag-prod-eval] [--limit 200]
"""

from __future__ import annotations

import argparse
from typing import Any

_client: Any = None  # langsmith.Client | None — lazy singleton


def _make_client():
    import langsmith as ls

    return ls.Client()


def export_eval_dataset(
    project_name: str, dataset_name: str, limit: int | None = None
) -> tuple[int, int]:
    """Bulk-create dataset examples từ root runs của project. Trả về (created, skipped)."""
    global _client
    if _client is None:
        _client = _make_client()
    client = _client
    runs = list(client.list_runs(project_name=project_name, is_root=True, error=False, limit=limit))
    usable = [r for r in runs if getattr(r, "inputs", None) and getattr(r, "outputs", None)]
    dataset = client.create_dataset(dataset_name, description="prod runs → eval set")
    examples = [
        {
            "inputs": r.inputs,
            "outputs": r.outputs,
            "metadata": {"source_run_id": r.id},
        }
        for r in usable
    ]
    if examples:
        client.create_examples(dataset_id=dataset.id, examples=examples)
    return len(examples), len(runs) - len(usable)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default="chakra_rag")
    ap.add_argument("--dataset", default="rag-prod-eval")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    created, skipped = export_eval_dataset(args.project, args.dataset, args.limit)
    print(f"created={created} skipped={skipped} project={args.project} dataset={args.dataset}")
