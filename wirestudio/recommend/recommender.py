"""Deterministic component recommender.

Given a free-text capability query (and optional electrical constraints),
rank the library's components by how well they fit. v1 is a small ranking
function over name / category / use_cases / aliases plus a boost for
"battle-tested" parts (those used in the bundled examples).

Pure: no LLM call, no network. Cheap enough to run synchronously inside
an agent tool. The agent reads the ranked list and narrates it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from wirestudio.library import Library, LibraryComponent


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


@dataclass
class Recommendation:
    library_id: str
    name: str
    category: str
    use_cases: list[str]
    aliases: list[str]
    required_components: list[str]
    current_ma_typical: Optional[float]
    current_ma_peak: Optional[float]
    vcc_min: Optional[float]
    vcc_max: Optional[float]
    score: float
    in_examples: int
    rationale: str
    notes: Optional[str] = None


@dataclass
class Constraints:
    """Optional filters applied before ranking. Components that fail any
    constraint are dropped, not penalised."""
    voltage: Optional[float] = None
    """Rail the component will run on. Filters by [vcc_min, vcc_max]."""
    max_current_ma_peak: Optional[float] = None
    """Drop components whose peak current exceeds this."""
    required_bus: Optional[str] = None
    """Drop components that don't list this bus in required_components
    (e.g., 'i2c'). Use to filter when the design already commits to a bus."""
    excluded_categories: list[str] = field(default_factory=list)
    """Drop components in any of these categories (e.g., ['io_expander'])."""


# ---------------------------------------------------------------------------
# Examples-corpus boost
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _example_usage_counts() -> dict[str, int]:
    """Map library_id -> number of bundled examples that use it."""
    counts: dict[str, int] = {}
    if not EXAMPLES_DIR.is_dir():
        return counts
    for p in sorted(EXAMPLES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for c in data.get("components", []):
            lib_id = c.get("library_id")
            if lib_id:
                counts[lib_id] = counts.get(lib_id, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Token matching
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _component_haystacks(c: LibraryComponent) -> dict[str, set[str]]:
    """Return tokens grouped by where they came from. The grouping lets us
    weight matches: a hit in the name beats a hit in an alias."""
    return {
        "name": _tokens(c.name),
        "category": _tokens(c.category),
        "use_cases": _tokens(" ".join(c.use_cases)),
        "aliases": _tokens(" ".join(c.aliases)),
    }


# Field weights for match scoring. A query token landing in `use_cases` is the
# strongest signal -- that's the field designers write to describe intent.
_FIELD_WEIGHTS = {
    "use_cases": 4.0,
    "name":      2.5,
    "category":  2.0,
    "aliases":   1.5,
}


def _match_score(query_tokens: set[str], haystacks: dict[str, set[str]]) -> tuple[float, list[str]]:
    """Return (score, rationale-tokens) for a single component."""
    if not query_tokens:
        return 0.0, []
    score = 0.0
    matched: list[str] = []
    for fname, weight in _FIELD_WEIGHTS.items():
        hits = query_tokens & haystacks.get(fname, set())
        if hits:
            score += weight * len(hits)
            matched.extend(sorted(hits))
    return score, sorted(set(matched))


# ---------------------------------------------------------------------------
# Constraint filtering
# ---------------------------------------------------------------------------

def _passes_constraints(c: LibraryComponent, constraints: Constraints) -> bool:
    if constraints.voltage is not None:
        if c.electrical.vcc_min is not None and c.electrical.vcc_min > constraints.voltage:
            return False
        if c.electrical.vcc_max is not None and c.electrical.vcc_max < constraints.voltage:
            return False
    if constraints.max_current_ma_peak is not None:
        if (c.electrical.current_ma_peak or 0) > constraints.max_current_ma_peak:
            return False
    if constraints.required_bus is not None:
        if constraints.required_bus not in c.esphome.required_components:
            return False
    if constraints.excluded_categories:
        if c.category in constraints.excluded_categories:
            return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_components(
    library: Library,
    query: str,
    constraints: Optional[Constraints] = None,
    limit: int = 10,
) -> list[Recommendation]:
    """Rank library components against the query.

    Score = match_score (field-weighted) + 3 * in_examples - 0.05 * peak_mA.
    Components with zero match are dropped; the rest are returned descending,
    capped at `limit`.

    Notes on the score components:
    - **match_score** gives use_cases > name > category > aliases. A query
      like "motion" lands in use_cases for the PIR (4.0 * 1) and in name
      for the PIR (2.5 * 1) for a total of 6.5.
    - **in_examples** boosts parts that are battle-tested in the bundled
      examples. A WS2812B used in 3 examples gets +9.
    - **peak current penalty** prefers low-power parts when the match
      scores tie. 1000mA peak nudges a candidate down by ~50 points,
      which is meaningful but never decisive against a strong text match.
    """
    constraints = constraints or Constraints()
    query_tokens = _tokens(query)
    if not query_tokens:
        return []

    usage = _example_usage_counts()
    out: list[Recommendation] = []

    for c in library.list_components():
        if not _passes_constraints(c, constraints):
            continue
        haystacks = _component_haystacks(c)
        match, matched_tokens = _match_score(query_tokens, haystacks)
        if match == 0:
            continue
        in_examples = usage.get(c.id, 0)
        peak_ma = c.electrical.current_ma_peak or 0
        score = match + 3.0 * in_examples - 0.05 * peak_ma

        rationale_bits = []
        if matched_tokens:
            rationale_bits.append(f"matched {', '.join(matched_tokens)}")
        if in_examples:
            rationale_bits.append(f"used in {in_examples} example{'s' if in_examples != 1 else ''}")
        if c.electrical.current_ma_peak:
            rationale_bits.append(f"~{int(c.electrical.current_ma_peak)}mA peak")

        out.append(Recommendation(
            library_id=c.id,
            name=c.name,
            category=c.category,
            use_cases=list(c.use_cases),
            aliases=list(c.aliases),
            required_components=list(c.esphome.required_components),
            current_ma_typical=c.electrical.current_ma_typical,
            current_ma_peak=c.electrical.current_ma_peak,
            vcc_min=c.electrical.vcc_min,
            vcc_max=c.electrical.vcc_max,
            score=round(score, 2),
            in_examples=in_examples,
            rationale="; ".join(rationale_bits),
            notes=c.notes,
        ))

    out.sort(key=lambda r: -r.score)
    return out[:limit]
