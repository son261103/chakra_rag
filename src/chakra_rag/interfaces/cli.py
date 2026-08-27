"""CLI: ingest / ask / files — chạy nhanh không cần API hay UI.

Cách dùng:
    python -m chakra_rag ingest            # ingest data/docs vào DB
    python -m chakra_rag ask "câu hỏi"     # hỏi (mặc định mode=agent)
    python -m chakra_rag ask "..." --mode stuff
    python -m chakra_rag files             # xem danh sách file + tiến trình
"""

from __future__ import annotations

import argparse
import json
import sys

from chakra_rag.config import get_config
from chakra_rag.core.embedding import Embedder
from chakra_rag.ingestion.worker import ingest_directory_sync
from chakra_rag.service.rag_service import RagService
from chakra_rag.storage.store import Store


def cmd_ingest(args: argparse.Namespace) -> None:
    cfg = get_config()
    embedder = Embedder(cfg.embed_model)
    store = Store(cfg.db_path, embed_dim=embedder.dim)
    n = ingest_directory_sync(cfg, store, embedder, cfg.docs_dir, source="seed")
    print(f"Đã ingest {n} file từ {cfg.docs_dir} → {store.count_chunks()} chunks")
    store.close()


def cmd_ask(args: argparse.Namespace) -> None:
    service = RagService()
    result = service.ask(args.question, mode=args.mode, top_k=args.top_k)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{result['answer']}\n")
        if result["citations"]:
            print("Nguồn:")
            for c in result["citations"]:
                print(f"  [{c['chunk_id']}] {c['doc']} — {c['section']}")
        if result["search_trace"]:
            print("\nAgent đã tìm kiếm:")
            for t in result["search_trace"]:
                print(
                    f"  🔍 \"{t['query']}\" → {t['n_results']} kết quả "
                    f"(max score {t['max_score']:.2f})"
                )
        if result["low_confidence"]:
            print("\n⚠️  Độ tin cậy thấp — kết quả truy xuất dưới ngưỡng.")
        if result["unsupported_claims"]:
            print(f"\n⚠️  {len(result['unsupported_claims'])} câu chưa được nguồn đỡ:")
            for claim in result["unsupported_claims"]:
                print(f"  - {claim}")
    service.close()


def cmd_files(args: argparse.Namespace) -> None:
    cfg = get_config()
    embedder = Embedder(cfg.embed_model)
    store = Store(cfg.db_path, embed_dim=embedder.dim)
    for f in store.list_files():
        print(f"  {f['status']:>9}  {f['chunks_done']}/{f['chunks_total']}  {f['name']}"
              + (f"  (lỗi: {f['error']})" if f["error"] else ""))
    store.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="chakra_rag", description="Chakra RAG CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="Ingest data/docs vào database")

    p_ask = sub.add_parser("ask", help="Hỏi một câu")
    p_ask.add_argument("question")
    p_ask.add_argument("--mode", choices=["agent", "stuff"], default="agent")
    p_ask.add_argument("--top-k", type=int, default=None)
    p_ask.add_argument("--json", action="store_true", help="In kết quả dạng JSON")

    sub.add_parser("files", help="Xem danh sách file và trạng thái ingest")

    args = parser.parse_args(argv)
    {"ingest": cmd_ingest, "ask": cmd_ask, "files": cmd_files}[args.command](args)


if __name__ == "__main__":
    main(sys.argv[1:])
