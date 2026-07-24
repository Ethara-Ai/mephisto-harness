"""Bundle SCALE classification.

=============================================================================
WARNING: THIS MEASURES SCALE. IT DOES NOT MEASURE DIFFICULTY.
=============================================================================

`classify_tier` buckets a bundle by lines-of-code gutted and tests covered.
Those are real, useful properties -- they say how BIG a task is. They say
NOTHING about whether a frontier model can solve it, and the label "extreme"
must never be read as "hard".

The evidence INVERTS the naive reading. From EdgeBench's own reported frontier
scores (`requirements/EdgeBench.md` Tables 8 and 10; Opus 4.8 / GPT-5.5, mean
over up to three 12-hour runs):

    THIS FUNCTION WOULD CALL THESE "toy"   (one file, <200 LOC, no test suite):
        warehouse_forklift_routing ......... 11.2 / 12.6   <- MOST RESISTANT
        wireless_electricity_layout ........ 14.5 /  7.2      task in the
        vibrating_path_graph_coloring ...... 25.3 / 11.4      entire suite

    THIS FUNCTION WOULD CALL THESE "extreme"  (>2000 LOC, >500 tests):
        stream_processing_engine .......... 100.0 / 100.0  <- DEFEATED by all
        entt_graph_module ................. 100.0 /  94.3     five models
        nlohmann_json_modularization ...... 100.0 /  98.9
        mimesis_modular_refactor .......... 100.0 /  91.0
        copier_modular_refactor ............ 98.9 /  97.8

`EdgeBench.md:259` describes the large-refactor family as "thousands of lines of
change, with over 100,000 lines in the largest cases" -- and it is the most
saturated family in the benchmark. Scale is ANTI-CORRELATED with resistance.

So this function would label the hardest task in EdgeBench "toy" and the most
thoroughly defeated ones "extreme". Do not read its output as difficulty
evidence, do not let it anchor a hardness tier, and never let a high scale
bucket stand in for a probe.

WHAT ACTUALLY PREDICTS DIFFICULTY
---------------------------------
Where score 100 comes from. A task resists the frontier when its upper anchor is
an artifact the authoring agent did not create and no known solver has beaten (a
contest leaderboard, a best-known-solutions table, a production library, an open
problem). See `requirements/MEPHISTO.md` §2 and `standards/anchor-provenance.md`.

Otherwise, difficulty is only knowable by MEASUREMENT: run a frontier model
against the built bundle and read the score. See `scripts/probe_difficulty.sh`
and `trinity/FORGE.md:116` -- "A clean frontier solve is a defect signal that
sends the task back to Phase 1. It is not pilot evidence."

Behaviour is intentionally unchanged; only the naming and the contract around it
are corrected. `Tier` / `classify_tier` / `enforce_tier` are retained as the
names `cli_entry.py` imports and as a frozen `--tier` CLI contract.
`Scale` / `classify_scale` / `enforce_scale` are the honest names; prefer them.
"""
from __future__ import annotations

from typing import Literal

from sforge.author.errors import TierMismatchError


# A SCALE axis (small / medium / large), not a difficulty axis. Spelled
# toy/standard/extreme only because that is a frozen CLI + manifest contract.
Tier = Literal["toy", "standard", "extreme"]
Scale = Tier  # honest alias; prefer this name in new code.

#: This module measures scale only. Nothing here is difficulty evidence. A
#: bundle's difficulty is UNKNOWN until a frontier probe has run against the
#: built images (scripts/probe_difficulty.sh).
MEASURES_DIFFICULTY = False


def classify_scale(loc_gutted: int, tests_covered: int) -> Scale:
    """Bucket a bundle by SCALE. Not difficulty -- see the module docstring.

    Returns "toy" | "standard" | "extreme" purely as a size label. A large
    bundle is not a hard one; in EdgeBench's data the correlation runs the
    other way.
    """
    if loc_gutted < 200 and tests_covered < 100:
        return "toy"
    if loc_gutted < 2000 and tests_covered < 500:
        return "standard"
    return "extreme"


def classify_tier(loc_gutted: int, tests_covered: int) -> Tier:
    """Deprecated name for `classify_scale`. Kept for `cli_entry.py`.

    "tier" here is a misnomer inherited from the original authoring flow. It is
    NOT one of the Baseline / Hard / Frontier-defeat hardness tiers of
    `trinity/FORGE.md`; those may only be anchored by an ACTIVE lever read from
    FORGE_VIEW (`FORGE.md:168`), never by a size bucket.
    """
    return classify_scale(loc_gutted, tests_covered)


def enforce_scale(expected: str, observed: str) -> None:
    """Fail closed when the declared scale bucket does not match the measured one."""
    if expected != observed:
        raise TierMismatchError(
            f"scale mismatch: expected {expected!r}, observed {observed!r}"
        )


def enforce_tier(expected: str, observed: str) -> None:
    """Deprecated name for `enforce_scale`. Kept for `cli_entry.py`."""
    enforce_scale(expected, observed)
