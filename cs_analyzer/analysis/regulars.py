"""Shared library-regulars computation (Phase S: one definition, three users).

teamplay (K5), funlab_data (排型/日期 filters) and lineups_data (车队局)
each re-implemented "players with >= N appearances across the 5E set"
with the same threshold and the same g161- prefix rule — three copies
that could drift. Callers pass {demo_hash: set[steamid]}; the threshold
stays a parameter (tests override it).
"""
from __future__ import annotations

FIVE_E_PREFIX = "g161-"
MIN_REGULAR_DEMOS = 3
#: a match where >= this many regulars queued together is a 车队局
STACK_THRESHOLD = 3


def compute_regulars(demo_player_ids: dict[str, set[str]],
                     min_appearances: int = MIN_REGULAR_DEMOS) -> set[str]:
    """{demo_hash: player sids} -> steamids appearing in >= min 5E demos.

    5E demos are the ones whose FILENAME carries the g161- prefix; since
    this function only sees ids, callers pre-filter to 5E demos (every
    caller already derives filenames alongside).
    """
    appear: dict[str, int] = {}
    for sids in demo_player_ids.values():
        for sid in sids:
            appear[sid] = appear.get(sid, 0) + 1
    return {sid for sid, n in appear.items() if n >= min_appearances}
