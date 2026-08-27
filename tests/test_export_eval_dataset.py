from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_export_skips_runs_missing_io():
    from scripts.export_eval_dataset import export_eval_dataset  # type: ignore[attr-defined]

    run_ok = MagicMock(inputs={"question": "q"}, outputs={"answer": "a"})
    run_bad = MagicMock(inputs=None, outputs={"answer": "a"})
    with patch("scripts.export_eval_dataset._client") as client:
        client.list_runs.return_value = [run_ok, run_bad]
        created, skipped = export_eval_dataset("proj", "ds")
    assert created == 1
    assert skipped == 1
