"""Ties the world, monitoring units, integrity engine, QKD monitor and alerts
into one tick loop, and produces the dashboard snapshot."""
import dataclasses
import logging
import random
import threading
import time
from collections import deque

from . import aqi as aqi_mod
from . import alerts
from .aws import AwsSinks
from .geo import SCHOOLS, STACKS, STATIONS, grid_cells
from .integrity import MIN_WINDOW, IntegrityEngine, window_features
from .quantum.qkd_monitor import QKDMonitor
from .sensors import BEHAVIOURS, MonitoringUnit
from .world import World

log = logging.getLogger("trueair")


def _pipeline(stacks, seed):
    world = World(seed=seed, stacks=stacks)
    rng = random.Random(seed)
    units = {s.id: MonitoringUnit(s, rng) for s in stacks}
    integ = IntegrityEngine(stacks, {sid: u.se.public_key for sid, u in units.items()})
    return world, units, integ


def _run_tick(world, units, integ):
    snap = world.step()
    for sid, u in units.items():
        integ.ingest(sid, u.emit(snap["true"][sid], snap["t"]), snap["t"])
    integ.invert(snap)
    return snap


def honest_baseline_features(ticks=160, seed=11):
    """Window features from a city where every plant is honest. The
    IsolationForest learns 'normal' from this; tampering is never shown to it."""
    stacks = [dataclasses.replace(s, behaviour="honest") for s in STACKS]
    world, units, integ = _pipeline(stacks, seed)
    rows = []
    for k in range(ticks):
        _run_tick(world, units, integ)
        if k >= MIN_WINDOW * 2:
            rows += [window_features(L) for L in integ.ledgers.values()]
    return rows


class Engine:
    def __init__(self, seed=None, tick_seconds=2.0):
        t0 = time.time()
        self.lock = threading.RLock()
        self.tick_seconds = tick_seconds
        self.stacks = [dataclasses.replace(s) for s in STACKS]
        self.world, self.units, self.integ = _pipeline(self.stacks, seed)
        self.integ.fit_baseline(honest_baseline_features())
        self.qkd = QKDMonitor()
        self.aws = AwsSinks()
        self.events = deque(maxlen=60)
        self.prev_status = {}
        self.prev_school_level = {}
        self.prev_link_secure = {}
        self.snapshot = None
        self.paused = False
        self.startup_seconds = round(time.time() - t0, 2)
        for _ in range(MIN_WINDOW + 2):
            self.tick()

    # ---------------- controls ----------------
    def set_behaviour(self, stack_id, behaviour):
        if behaviour not in BEHAVIOURS:
            raise KeyError(behaviour)
        with self.lock:
            self.units[stack_id].behaviour = behaviour

    def set_smog(self, on):
        with self.lock:
            self.world.smog = bool(on)

    def set_qkd_attack(self, link_id, scenario):
        with self.lock:
            self.qkd.set_attack(link_id, scenario)

    # ---------------- loop ----------------
    def run_forever(self, stop: threading.Event):
        while not stop.wait(self.tick_seconds):
            self.aws.flush()  # sends any queued digest once its interval has passed
            if not self.paused:
                try:
                    self.tick()
                except Exception:
                    log.exception("tick failed")

    def _event(self, kind, subject, severity, message, t, notify=False):
        ev = {"kind": kind, "subject": subject, "severity": severity, "message": message, "t": t}
        self.events.appendleft(ev)
        self.aws.put_event(ev)
        if notify:
            self.aws.notify(f"TrueAir: {subject}", message, kind)

    def tick(self):
        with self.lock:
            snap = _run_tick(self.world, self.units, self.integ)
            ledgers = self.integ.score(snap["t"])
            links = self.qkd.tick()
            t = snap["t"]

            stations = []
            station_aqi = {}
            for i, st in enumerate(STATIONS):
                concs = {p: float(snap["stations"][p][i]) for p in ("pm25", "pm10", "no2", "so2")}
                a, cat, dom = aqi_mod.compute(concs)
                station_aqi[st.id] = a
                stations.append({"id": st.id, "name": st.name, "lat": st.lat, "lon": st.lon,
                                 "aqi": a, "category": cat, "dominant": dom,
                                 "concs": {k: round(v, 1) for k, v in concs.items()}})

            stacks = []
            for s in self.stacks:
                L = ledgers[s.id]
                if L.history:
                    L.history[-1]["true"] = round(snap["true"][s.id]["so2"], 1)  # demo ground truth
                last = L.events[-1] if L.events else {}
                best = last.get("so2") if L.status == "trusted" else L.inferred
                stacks.append({
                    "id": s.id, "name": s.name, "lat": s.lat, "lon": s.lon,
                    "so2_limit": s.so2_limit, "behaviour": self.units[s.id].behaviour,
                    "reported_so2": last.get("so2"), "packet_status": last.get("status"),
                    "inferred_so2": round(L.inferred, 1) if L.inferred is not None else None,
                    "true_so2": round(snap["true"][s.id]["so2"], 1),  # demo ground truth
                    "best_estimate_so2": round(best, 1) if best is not None else None,
                    "exceeding_limit": bool(best is not None and best > s.so2_limit),
                    "score": L.score, "status": L.status, "reasons": L.reasons,
                    "anomaly": round(L.anomaly, 3),
                })
                prev = self.prev_status.get(s.id)
                if prev and prev != L.status and L.status in ("suspect", "compromised"):
                    self._event("stack", s.id, "high" if L.status == "compromised" else "medium",
                                f"{s.name} marked {L.status.upper()}: " + "; ".join(L.reasons[:2]), t,
                                notify=L.status == "compromised")
                elif prev in ("suspect", "compromised") and L.status == "trusted":
                    self._event("stack", s.id, "info", f"{s.name} data trusted again", t)
                self.prev_status[s.id] = L.status

            schools = []
            for sc in SCHOOLS:
                a, km = alerts.school_aqi(sc, STATIONS, station_aqi)
                contrib = alerts.top_contributor(sc, self.stacks, ledgers, snap["wind_from"], snap["wind_speed"])
                adv = alerts.advisory(sc, a, km, contrib)
                schools.append({"id": sc.id, "name": sc.name, "lat": sc.lat, "lon": sc.lon,
                                "students": sc.students, "aqi": a, "category": aqi_mod.category(a),
                                "nearest_station_km": km, "contributor": contrib, **adv})
                prev = self.prev_school_level.get(sc.id)
                if prev is not None and adv["level"] > prev and adv["level"] >= 2:
                    self._event("school", sc.id, "high" if adv["level"] >= 3 else "medium",
                                adv["message"], t, notify=adv["level"] >= 3)
                self.prev_school_level[sc.id] = adv["level"]

            for ln in links:
                prev = self.prev_link_secure.get(ln["id"])
                if prev is True and not ln["secure"]:
                    self._event("qkd", ln["id"], "high",
                                f"QKD {ln['a']} ↔ {ln['b']}: {ln['detected_label']} detected "
                                f"(QBER {ln['qber']:.1%}, conf {ln['confidence']:.0%}). {ln['fallback']}.", t,
                                notify=True)
                elif prev is False and ln["secure"]:
                    self._event("qkd", ln["id"], "info", f"QKD {ln['a']} ↔ {ln['b']} secure again", t)
                self.prev_link_secure[ln["id"]] = ln["secure"]

            city_aqi = round(sum(station_aqi.values()) / len(station_aqi))
            self.snapshot = {
                "t": t, "tick": snap["tick"],
                "wind": {"from": snap["wind_from"], "speed": snap["wind_speed"]},
                "night": snap["night"], "smog": snap["smog"],
                "city": {"aqi": city_aqi, "category": aqi_mod.category(city_aqi)},
                "stations": stations, "stacks": stacks, "schools": schools, "qkd": links,
                "satellite": [{"lat": la, "lon": lo, "so2": round(float(v), 1)}
                              for (la, lo), v in zip(grid_cells(), snap["satellite_so2"])],
                "events": list(self.events),
            }
            return self.snapshot

    def stack_history(self, stack_id):
        with self.lock:
            return list(self.integ.ledgers[stack_id].history)

    def meta(self):
        return {"behaviours": BEHAVIOURS, "qkd": self.qkd.summary(), "aws": self.aws.status,
                "tick_seconds": self.tick_seconds, "startup_seconds": self.startup_seconds}
