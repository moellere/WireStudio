"""Promoting a community library entry into the bundled library."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coverage_matrix  # noqa: E402
import promote_library  # noqa: E402

from wirestudio.library import Library  # noqa: E402
from wirestudio.library.board_check import check_board_yaml  # noqa: E402
from wirestudio.library.check import check_component_yaml  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
LED = (FIXTURES / "components" / "led_driver_npn.yaml").read_text()
S2 = (FIXTURES / "boards" / "lolin-s2-mini.yaml").read_text()
META = "author: octocat\ntags: [esp32s2]\nsource: https://www.wemos.cc/en/latest/s2/s2_mini.html\n"


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    shutil.copytree(ROOT / "wirestudio" / "library", r / "wirestudio" / "library",
                    ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    shutil.copytree(ROOT / "wirestudio" / "examples", r / "wirestudio" / "examples")
    (r / "scripts").mkdir()
    for name in ("coverage_baseline.yaml", "framework_baseline.yaml"):
        shutil.copy(ROOT / "scripts" / name, r / "scripts" / name)
    shutil.copy(ROOT / "CHANGELOG.md", r / "CHANGELOG.md")
    return r


@pytest.fixture
def catalogue(tmp_path):
    c = tmp_path / "catalogue"
    for kind, lid, text in (("boards", "lolin-s2-mini", S2), ("components", "led_driver_npn", LED)):
        d = c / "library" / kind / lid
        d.mkdir(parents=True)
        (d / promote_library.KINDS[kind]).write_text(text)
        (d / "meta.yaml").write_text(META)
    shipped = c / "designs" / "porch-led" / "components"
    shipped.mkdir(parents=True)
    (shipped / "led_driver_npn.yaml").write_text(LED)
    return c


def run(catalogue, repo, entry, *flags):
    return promote_library.main([str(catalogue), entry, "--repo", str(repo), *flags])


def strict(repo) -> int:
    library = Library(repo / "wirestudio" / "library")
    examples = {p.stem: json.loads(p.read_text()) for p in (repo / "wirestudio" / "examples").glob("*.json")}
    return coverage_matrix._strict_check(library, examples, repo / "scripts" / "coverage_baseline.yaml",
                                         repo / "scripts" / "framework_baseline.yaml")


def test_a_dry_run_writes_nothing(catalogue, repo, capsys):
    before = (repo / "CHANGELOG.md").read_text()
    assert run(catalogue, repo, "boards/lolin-s2-mini") == 0
    out = capsys.readouterr().out
    assert "# Contributed by @octocat" in out and "Dry run" in out
    assert not (repo / "wirestudio" / "library" / "boards" / "lolin-s2-mini.yaml").exists()
    assert (repo / "CHANGELOG.md").read_text() == before


def test_a_board_is_promoted_with_its_credit_and_the_gate_stays_green(catalogue, repo, capsys):
    assert strict(repo) == 0
    assert run(catalogue, repo, "boards/lolin-s2-mini", "--write") == 0
    out = capsys.readouterr().out
    text = (repo / "wirestudio" / "library" / "boards" / "lolin-s2-mini.yaml").read_text()
    assert text.startswith("# Contributed by @octocat through the WireStudio community library\n"
                           "# (moellere/wirestudio-designs, library/boards/lolin-s2-mini), MIT.\n"
                           "# Written from: https://www.wemos.cc/en/latest/s2/s2_mini.html\n")
    assert text.endswith(S2)
    library = Library(repo / "wirestudio" / "library")
    report = check_board_yaml(text, library)
    assert report.ok and report.exists == "bundled"
    changelog = (repo / "CHANGELOG.md").read_text()
    unreleased = changelog[changelog.index("## [Unreleased]"):changelog.index("\n## [", changelog.index("## [Unreleased]") + 1)]
    assert "**LOLIN S2 Mini** (`lolin-s2-mini`), a community board by @octocat" in unreleased
    assert "coverage_baseline.yaml: boards: lolin-s2-mini" in out
    assert "library/boards/lolin-s2-mini/" in out
    assert strict(repo) == 0


def test_a_component_gets_its_framework_gaps_and_the_catalogue_copies_to_remove(catalogue, repo, capsys):
    assert run(catalogue, repo, "components/led_driver_npn", "--write") == 0
    out = capsys.readouterr().out
    library = Library(repo / "wirestudio" / "library")
    assert check_component_yaml(
        (repo / "wirestudio" / "library" / "components" / "led_driver_npn.yaml").read_text(), library).ok
    assert "framework_baseline.yaml: circuitpython: led_driver_npn" in out
    assert "designs/porch-led/components/led_driver_npn.yaml" in out
    assert strict(repo) == 0


def test_promotion_refuses_what_it_cannot_credit_or_bundle(catalogue, repo, capsys):
    meta = catalogue / "library" / "boards" / "lolin-s2-mini" / "meta.yaml"
    meta.write_text("author: octocat\nsource: http://example.com\n")
    assert run(catalogue, repo, "boards/lolin-s2-mini", "--write") == 1
    assert "no https `source`" in capsys.readouterr().err
    meta.write_text(META)

    board = catalogue / "library" / "boards" / "lolin-s2-mini" / "board.yaml"
    board.write_text(S2.replace("pin: GPIO15", "pin: GPIO14"))
    assert run(catalogue, repo, "boards/lolin-s2-mini", "--write") == 1
    assert "GPIO14 is not in gpio_capabilities" in capsys.readouterr().err
    assert not (repo / "wirestudio" / "library" / "boards" / "lolin-s2-mini.yaml").exists()

    board.write_text(S2)
    assert run(catalogue, repo, "boards/lolin-s2-mini", "--write") == 0
    assert run(catalogue, repo, "boards/lolin-s2-mini", "--write") == 1
    assert "already exists" in capsys.readouterr().err
    assert run(catalogue, repo, "modules/x") == 2
