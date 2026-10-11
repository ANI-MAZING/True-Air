"""Reproduce the detection numbers quoted in the README and blog.

  1. False alarms and city AQI: 6 seeds x 100 steps, first 20 ignored as warm-up.
  2. Inverse-model error: mean |inferred - true| / true for stacks the model can see.
  3. Time to detection: switch one clean plant to each cheating behaviour (4 seeds)
     and count steps until it is no longer "trusted" or is flagged over limit.
  4. False readings: inject fake values in transit / into the analyser.

Usage: .venv/bin/python scripts/evaluate.py   (takes a few minutes)
Writes benchmarks/detection_eval.json.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.engine import Engine  # noqa: E402
from app.sensors import BEHAVIOURS  # noqa: E402

STEP_MIN = 15
WARMUP = 20


def baseline(seeds=range(6), steps=100):
    checks = false_alarms = school_alerts = 0
    aqi, rel_err = [], []
    for seed in seeds:
        e = Engine(seed=seed)
        for k in range(steps):
            s = e.tick()
            aqi.append(s["city"]["aqi"])
            school_alerts += sum(x["level"] >= 2 for x in s["schools"])
            if k < WARMUP:
                continue
            for st in s["stacks"]:
                if st["inferred_so2"] is not None and st["true_so2"] > 0:
                    rel_err.append(abs(st["inferred_so2"] - st["true_so2"]) / st["true_so2"])
                if st["behaviour"] == "honest":
                    checks += 1
                    false_alarms += st["status"] != "trusted" or st["exceeding_limit"]
    return {"honest_checks": checks, "false_alarms": int(false_alarms),
            "city_aqi_min": min(aqi), "city_aqi_max": max(aqi),
            "school_alert_steps": int(school_alerts),
            "inverse_model_median_rel_error": round(float(np.median(rel_err)), 3),
            "inverse_model_mean_rel_error": round(float(np.mean(rel_err)), 3)}


def detection(seeds=range(4), target="WZP-02", max_steps=40):
    out = {}
    for b in BEHAVIOURS:
        if b == "honest":
            continue
        steps = []
        for seed in seeds:
            e = Engine(seed=seed)
            for _ in range(16):
                e.tick()
            e.set_behaviour(target, b)
            for k in range(max_steps):
                st = next(x for x in e.tick()["stacks"] if x["id"] == target)
                if st["status"] != "trusted" or st["exceeding_limit"]:
                    steps.append(k + 1)
                    break
            else:
                steps.append(None)
        out[b] = {"steps": steps, "minutes": [s * STEP_MIN if s else None for s in steps]}
    return out


def injections(target="SBD-06"):
    out = {}
    for method, value in (("transit", 5), ("analyser", 5), ("analyser", 300)):
        e = Engine(seed=1)
        for _ in range(16):
            e.tick()
        e.inject_reading(target, value, method, 8)
        hit = None
        for k in range(12):
            st = next(x for x in e.tick()["stacks"] if x["id"] == target)
            if st["status"] != "trusted":
                hit = k + 1
                break
        out[f"{method}_{value}"] = {"steps": hit, "minutes": hit * STEP_MIN if hit else None}
    return out


if __name__ == "__main__":
    result = {"baseline": baseline(), "detection": detection(), "false_readings": injections()}
    out = ROOT / "benchmarks" / "detection_eval.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"wrote {out}")
