"""Ground-truth world: weather, plant loads, true emissions, and what the
independent instruments (ambient stations, satellite) observe.

Nothing in here is visible to the integrity engine except the observations.
"""
import math
import random
from datetime import datetime, timedelta, timezone

import numpy as np

from . import dispersion
from .geo import STACKS, STATIONS, grid_cells
from .sensors import DIRTY_FACTOR

IST = timezone(timedelta(hours=5, minutes=30))
TICK_MINUTES = 15
CONTINUOUS_PLANTS = {"OKH-01", "MDK-08"}


class World:
    def __init__(self, seed=None, stacks=STACKS):
        self.rng = random.Random(seed)
        self.stacks = stacks
        self.cells = grid_cells()
        self.station_ll = [(s.lat, s.lon) for s in STATIONS]
        self.t = datetime(2026, 10, 11, 6, 0, tzinfo=IST)
        self.tick_n = 0
        self.wind_from = 305.0   # NW, typical post-monsoon Delhi
        self.wind_speed = 2.5
        self.smog = False
        self.dirty = {s.id: s.behaviour != "honest" for s in stacks}

    @property
    def hour(self):
        return self.t.hour + self.t.minute / 60

    def _load(self, stack):
        if stack.id in CONTINUOUS_PLANTS:
            base = 0.95 + 0.12 * math.sin(2 * math.pi * (self.hour - 10) / 24)
        else:
            day = 8 <= self.hour < 20
            base = 1.0 if day else 0.45
        return min(1.15, max(0.0, base * self.rng.gauss(1.0, 0.05)))

    def _weather(self):
        self.wind_from = (self.wind_from + self.rng.gauss(0, 12)) % 360
        # pull back towards the seasonal NW mean
        self.wind_from += 0.08 * (((305 - self.wind_from + 180) % 360) - 180)
        night = self.hour < 7 or self.hour >= 19
        target = 1.2 if night else 3.0
        self.wind_speed = max(0.6, self.wind_speed + 0.3 * (target - self.wind_speed) + self.rng.gauss(0, 0.2))

    def step(self):
        self.tick_n += 1
        self.t += timedelta(minutes=TICK_MINUTES)
        self._weather()

        true = {}
        for s in self.stacks:
            load = self._load(s)
            f = load * self.rng.gauss(1.0, 0.04) * (DIRTY_FACTOR if self.dirty[s.id] else 1.0)
            true[s.id] = {"load": load, "so2": s.base_so2 * f, "nox": s.base_nox * f, "pm": s.base_pm * f}

        night = self.hour < 7 or self.hour >= 19
        mixing = 1.7 if night else 1.0       # shallow boundary layer at night
        W = dispersion.influence_matrix(self.stacks, self.station_ll, self.wind_from, self.wind_speed) * mixing
        e = lambda p: np.array([true[s.id][p] for s in self.stacks])

        bg_pm = (30 if not night else 42) * (4.0 if self.smog else 1.0)
        bg_so2, bg_no2 = 6.0, (22.0 if not night else 30.0)
        n_st = len(self.station_ll)

        def obs(bg, contrib, rel=0.05, abs_=1.0):
            vals = (bg + contrib) * np.array([self.rng.gauss(1, rel) for _ in range(n_st)])
            vals += np.array([self.rng.gauss(0, abs_) for _ in range(n_st)])
            return np.clip(vals, 0, None)

        so2 = obs(bg_so2, W @ e("so2"))
        no2 = obs(bg_no2, 0.5 * (W @ e("nox")))
        pm25 = obs(bg_pm, 0.6 * (W @ e("pm")), rel=0.06, abs_=3)
        pm10 = pm25 * 1.5 + 10

        S = dispersion.influence_matrix(self.stacks, self.cells, self.wind_from, self.wind_speed, kind="sat")
        sat_bg = 40.0
        sat = (sat_bg + S @ e("so2")) * np.array([self.rng.gauss(1, 0.15) for _ in self.cells])

        return {
            "t": self.t.isoformat(),
            "tick": self.tick_n,
            "wind_from": round(self.wind_from, 1),
            "wind_speed": round(self.wind_speed, 2),
            "night": night,
            "smog": self.smog,
            "true": true,
            "W": W,
            "S": S,
            "stations": {"so2": so2, "no2": no2, "pm25": pm25, "pm10": pm10},
            "satellite_so2": sat,
        }
