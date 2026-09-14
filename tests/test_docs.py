"""Public docs may only quote measured figures, and they must match benchmarks/results/*.json."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("benchmark_report", ROOT / "benchmarks" / "report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def test_benchmarks_doc_is_rendered_from_current_results():
    expected = report.render(report.load())
    actual = (ROOT / "docs" / "benchmarks.md").read_text()
    assert actual == expected, "docs/benchmarks.md is stale: run `uv run python benchmarks/report.py`"


@pytest.mark.parametrize("doc", ["README.md", "docs/PRD.md"])
def test_docs_quote_the_current_headline_figures(doc):
    text = (ROOT / doc).read_text()
    missing = [figure for figure in report.headline_figures(report.load()) if figure not in text]
    assert not missing, f"{doc} does not quote the current measured figures: {missing}"
