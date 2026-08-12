"""HUD for the 2D replay renderer: score, round, clock, event feed, player info.

Uses a fixed pool of matplotlib text artists so per-frame updates never create
or destroy objects. Text is skipped when the string is unchanged.
"""
from __future__ import annotations

from cs_analyzer.config import ReplayConfig
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.replay.sides import side_for_round
from cs_analyzer.replay.timeline import PlayerTimeline

_FEED_MAX = 5
_FEED_WINDOW_SECONDS = 12.0


class ReplayHUD:
    def __init__(self, config: ReplayConfig, timeline: PlayerTimeline, demo: ParsedDemo) -> None:
        self.config = config
        self.tl = timeline
        self.demo = demo
        self.tick_rate = 64
        self._artists: list = []

        # event feed: sorted (tick, text); built once from timeline
        self.feed = self._build_feed()

        # Artists created in attach() (need fig/ax); None until then.
        self._player_name = None
        self._side_badge = None
        self._kd = None
        self._score = None
        self._round = None
        self._mode = None
        self._clock = None
        self._feed_lines = []
        self._artists = []

    # ---- construction ----

    def _build_feed(self) -> list[tuple[int, str]]:
        feed: list[tuple[int, str]] = []
        for k in self.tl.kills:
            feed.append((k.tick, f"击杀 {k.victim_name} ({k.weapon})"))
        for kind, evs in self.tl.utilities.items():
            label = {"smoke": "烟雾", "flash": "闪光", "he": "手雷", "molly": "燃烧弹", "fire": "燃烧弹"}.get(kind, kind)
            for e in evs:
                feed.append((e.tick, f"{self.tl.player.name} 投掷了{label}"))
        feed.sort(key=lambda x: x[0])
        return feed

    # ---- attach artists to the figure ----

    def attach(self, fig, ax) -> None:
        """Create the HUD text artists on fig/ax (fixed positions, figure coords)."""
        import matplotlib
        from matplotlib.transforms import blended_transform_factory

        self._artists = []
        fc = fig.transFigure

        self._player_name = fig.text(0.02, 0.95, "", color="white", fontsize=18, weight="bold",
                                     ha="left", va="top", transform=fc, zorder=20)
        self._side_badge = fig.text(0.02, 0.905, "", color="white", fontsize=13,
                                    ha="left", va="top", transform=fc, zorder=20)
        self._kd = fig.text(0.02, 0.86, "", color="#CCCCCC", fontsize=13,
                            ha="left", va="top", transform=fc, zorder=20)
        self._score = fig.text(0.5, 0.97, "", color="white", fontsize=20, weight="bold",
                               ha="center", va="top", transform=fc, zorder=20)
        self._round = fig.text(0.98, 0.97, "", color="#CCCCCC", fontsize=16,
                               ha="right", va="top", transform=fc, zorder=20)
        self._mode = fig.text(0.98, 0.92, "", color="#888888", fontsize=12,
                              ha="right", va="top", transform=fc, zorder=20)
        self._clock = fig.text(0.98, 0.10, "", color="white", fontsize=22, weight="bold",
                               ha="right", va="bottom", transform=fc, zorder=20)
        self._feed_lines = [
            fig.text(0.02, 0.30 - i * 0.055, "", color="white", fontsize=12,
                     ha="left", va="bottom", transform=fc, zorder=20)
            for i in range(_FEED_MAX)
        ]
        self._artists.extend(
            [self._player_name, self._side_badge, self._kd, self._score,
             self._round, self._mode, self._clock] + self._feed_lines
        )

    # ---- per-frame update ----

    def update(self, tick: float, round_number: int, side: str, mode_label: str) -> None:
        p = self.tl.player
        kills = len(self.tl.kills)
        deaths = len(self.tl.deaths)
        self._player_name.set_text(f"{p.name}")
        self._player_name.set_color(self.config.t_color if side == "T" else self.config.ct_color)
        self._side_badge.set_text(f"阵营: {'T 恐怖分子' if side == 'T' else 'CT 反恐精英'}")
        self._kd.set_text(f"K/D  {kills}/{deaths}")

        self._set_score(tick, round_number)
        self._round.set_text(f"回合 {round_number}")
        self._mode.set_text(mode_label)
        self._set_clock(tick, round_number)
        self._update_feed(tick)

    def _set_score(self, tick: float, round_number: int) -> None:
        rnd = self.demo.data.round_at_tick(int(tick))
        if rnd is None:
            return
        meta = self.demo.metadata
        a_side = side_for_round(round_number, meta.team_a.starting_side, rnd.is_overtime)
        if a_side == "T":
            self._score.set_text(f"{meta.team_a.name} {rnd.t_score} : {rnd.ct_score} {meta.team_b.name}")
        else:
            self._score.set_text(f"{meta.team_b.name} {rnd.t_score} : {rnd.ct_score} {meta.team_a.name}")

    def _set_clock(self, tick: float, round_number: int) -> None:
        rnd = self.demo.data.round_at_tick(int(tick))
        if rnd is None:
            return
        elapsed = (tick - rnd.start_tick) / self.tick_rate
        remain = max(self.config.round_clock_seconds - elapsed, 0)
        mm, ss = divmod(int(remain), 60)
        self._clock.set_text(f"{mm}:{ss:02d}")

    def _update_feed(self, tick: float) -> None:
        window_ticks = _FEED_WINDOW_SECONDS * self.tick_rate
        recent = [t for t in self.feed if tick - window_ticks <= t[0] <= tick]
        recent = recent[-_FEED_MAX:]
        for i, line in enumerate(self._feed_lines):
            if i < len(recent):
                line.set_text(recent[i][1])
            else:
                line.set_text("")
