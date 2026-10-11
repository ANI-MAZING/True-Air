import random

import pytest

from app import aqi
from app.engine import Engine
from app.geo import STACKS
from app.quantum import bb84
from app.sensors import MonitoringUnit, verify


def test_aqi_bands():
    assert aqi.sub_index("pm25", 30) == 50
    assert aqi.sub_index("pm25", 60) == 100
    assert aqi.sub_index("pm25", 250) == 400
    assert aqi.sub_index("pm25", 900) == 500
    assert aqi.compute({"pm25": 95, "pm10": 120, "no2": 40, "so2": 10})[1] == "Poor"


def test_signature_catches_edits():
    unit = MonitoringUnit(STACKS[1], random.Random(0))
    pkt = unit.emit({"so2": 50, "nox": 30, "pm": 20, "load": 1.0}, "t0")
    assert verify(unit.se.public_key, pkt["body"], pkt["sig"])
    edited = dict(pkt["body"], so2=pkt["body"]["so2"] / 2)
    assert not verify(unit.se.public_key, edited, pkt["sig"])


def test_bb84_intercept_resend_raises_qber():
    bb84.seed(1)
    normal = sum(bb84.run("normal")["qber"] for _ in range(20)) / 20
    mitm = sum(bb84.run("mitm_attack")["qber"] for _ in range(20)) / 20
    assert normal < 0.11 < mitm


@pytest.fixture(scope="module")
def engine():
    e = Engine(seed=9)
    for _ in range(40):
        e.tick()
    return e


def test_every_cheater_is_flagged_and_honest_plants_are_not(engine):
    for s in engine.snapshot["stacks"]:
        if s["behaviour"] == "honest":
            assert s["status"] == "trusted", s
        else:
            assert s["status"] in ("suspect", "compromised"), s


def test_honest_violator_is_trusted_but_over_limit(engine):
    mdk = next(s for s in engine.snapshot["stacks"] if s["id"] == "MDK-08")
    assert mdk["status"] == "trusted" and mdk["exceeding_limit"]


def test_inverse_model_recovers_true_emissions(engine):
    for s in engine.snapshot["stacks"]:
        if s["inferred_so2"] is not None:
            assert abs(s["inferred_so2"] - s["true_so2"]) / s["true_so2"] < 0.35, s


def test_qkd_attack_detected(engine):
    engine.set_qkd_attack("L1", "mitm_attack")
    engine.tick()
    link = next(l for l in engine.snapshot["qkd"] if l["id"] == "L1")
    assert not link["secure"] and link["detected"] == "mitm_attack"
    engine.set_qkd_attack("L1", "normal")
