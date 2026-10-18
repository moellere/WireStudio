"""The component gate rejects what it must. Each file in
`tests/fixtures/bad_components/` is the good draft with one defect and a
first line naming the error the report has to carry:

    # expect: <substring of an error>

A gate that lets a file through, or fails it for another reason, fails
here. The good draft the corpus is cut from is the one the esphome-config
workflow compiles through `esphome config`."""
from __future__ import annotations

from pathlib import Path

import pytest

from wirestudio.library import Library
from wirestudio.library.check import check_component_yaml

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BUNDLED = Path(__file__).resolve().parent.parent / "wirestudio" / "library"
CORPUS = sorted((FIXTURES / "bad_components").glob("*.yaml"))


@pytest.fixture
def lib(tmp_path):
    return Library(BUNDLED, tmp_path / "user")


def test_the_corpus_is_not_empty():
    assert len(CORPUS) >= 10


def test_the_draft_the_corpus_is_cut_from_passes(lib):
    report = check_component_yaml((FIXTURES / "components" / "led_driver_npn.yaml").read_text(), lib)
    assert report.ok, report.errors


@pytest.mark.parametrize("path", CORPUS, ids=[p.stem for p in CORPUS])
def test_each_bad_component_is_rejected_for_the_named_reason(lib, path):
    header, _, body = path.read_text().partition("\n")
    assert header.startswith("# expect: "), path
    expect = header[len("# expect: "):]
    report = check_component_yaml(body, lib)
    assert not report.ok, path
    assert any(expect in e for e in report.errors), (path.stem, expect, report.errors)
