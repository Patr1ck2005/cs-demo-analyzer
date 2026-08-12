"""Shared T/CT side logic for the 2D replay renderer.

CS2 uses MR12 regulation (side swap after round 12) and MR6 overtime
(side swap every 6 overtime rounds).
"""
from __future__ import annotations

REGULATION_ROUNDS = 12
OVERTIME_ROUNDS = 6


def side_for_round(
    round_number: int, team_starting_side: str, is_overtime: bool = False
) -> str:
    """Side a team plays in a given round (handles halftime + overtime swaps)."""
    if round_number <= REGULATION_ROUNDS:
        swap = 0
    elif is_overtime:
        ot_num = round_number - REGULATION_ROUNDS
        swap = (ot_num - 1) // OVERTIME_ROUNDS
    else:
        swap = 1
    if swap % 2 == 0:
        return team_starting_side
    return "CT" if team_starting_side == "T" else "T"
