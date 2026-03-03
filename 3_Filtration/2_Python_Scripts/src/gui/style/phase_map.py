# src/gui/style/phase_map.py
from __future__ import annotations

from typing import Dict, List, Set, Optional


PHASE_ORDER: List[str] = [
    "BACKWASH_INITIAL",
    "BACKWASH_HOLD",
    "FILLING",
    "FILTRATION",
    "VENTING",
    "BACKWASH_FINAL",
]

# Map arbitrary step strings -> canonical phase keys
_STEP_MAP: Dict[str, str] = {
    "BACKWASH_1": "BACKWASH_INITIAL",
    "BACKWASH_INITIAL": "BACKWASH_INITIAL",
    "BW1": "BACKWASH_INITIAL",

    "BACKWASH_HOLD": "BACKWASH_HOLD",
    "HOLD": "BACKWASH_HOLD",

    "FILL": "FILLING",
    "FILLING": "FILLING",

    "FILTER": "FILTRATION",
    "FILTRATION": "FILTRATION",

    "VENT": "VENTING",
    "VENTING": "VENTING",

    "BACKWASH_2": "BACKWASH_FINAL",
    "BACKWASH_FINAL": "BACKWASH_FINAL",
    "BW2": "BACKWASH_FINAL",
}


def normalize_step(step: str) -> str:
    """
    Normalize a worker/step string into canonical phase key.

    Patched:
    - safe handling for None
    - accepts already-canonical values
    """
    if not step:
        return ""
    key = str(step).strip().upper()
    return _STEP_MAP.get(key, key)


def compute_phase_states(
    active_phase: str,
    finished_phases: Optional[Set[str]] = None,
    blocked: Optional[Set[str]] = None,
) -> Dict[str, str]:
    """
    Compute per-phase UI state labels:
      idle | next | active | done | blocked

    Patched:
    - finished_phases/blocked are normalized to canonical keys
    - NEXT selection skips blocked and done
    - If active is unknown/unmapped, still produces a stable state map
    """
    finished_phases = {normalize_step(p) for p in (finished_phases or set())}
    blocked = {normalize_step(p) for p in (blocked or set())}

    active = normalize_step(active_phase)

    states: Dict[str, str] = {}
    for p in PHASE_ORDER:
        if p in blocked:
            states[p] = "blocked"
        elif p in finished_phases:
            states[p] = "done"
        elif p == active and active:
            states[p] = "active"
        else:
            states[p] = "idle"

    # Mark NEXT:
    # - Prefer: next idle after active (if active is known and in order)
    # - Else: first idle (skipping blocked/done)
    def _mark_first_next(candidates: List[str]) -> None:
        for pj in candidates:
            if states.get(pj) == "idle":
                states[pj] = "next"
                return

    if active and active in PHASE_ORDER:
        i = PHASE_ORDER.index(active)
        _mark_first_next(PHASE_ORDER[i + 1 :])
    else:
        _mark_first_next(PHASE_ORDER)

    return states