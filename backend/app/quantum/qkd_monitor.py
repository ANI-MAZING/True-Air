"""Watches QKD links on the regulator backbone and classifies attacks.

Each tick a BB84 session runs on every link; the 9 session metrics go through
a classifier trained on the 8-scenario dataset. The classical model here is the
production path. The hybrid QLSTM is benchmarked offline (scripts/qlstm_benchmark.py).
"""
import time

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from . import bb84

QBER_ABORT = 0.11  # BB84 security threshold

LINKS = [
    {"id": "L1", "a": "CPCB HQ", "b": "DPCC Delhi", "a_ll": (28.630, 77.220), "b_ll": (28.640, 77.240)},
    {"id": "L2", "a": "CPCB HQ", "b": "HSPCB Faridabad", "a_ll": (28.630, 77.220), "b_ll": (28.410, 77.320)},
    {"id": "L3", "a": "CPCB HQ", "b": "UPPCB Ghaziabad", "a_ll": (28.630, 77.220), "b_ll": (28.670, 77.420)},
]

LABELS = {
    "normal": "Normal",
    "mitm_attack": "Intercept-resend",
    "pns_attack": "Photon-number splitting",
    "trojan_horse_attack": "Trojan horse",
    "wavelength_dependent_trojan_attack": "Wavelength Trojan",
    "rng_attack": "RNG bias",
    "detector_blinding_attack": "Detector blinding",
    "combined_attack": "Combined",
}


def build_dataset(per_class=300, seed=7):
    bb84.seed(seed)
    X, y = [], []
    for label in bb84.SCENARIOS:
        for _ in range(per_class):
            r = bb84.run(label)
            X.append([r[c] for c in bb84.FEATURE_COLS])
            y.append(label)
    return np.array(X, dtype=np.float32), np.array(y)


class QKDMonitor:
    def __init__(self, per_class=300):
        t0 = time.time()
        X, y = build_dataset(per_class)
        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=0, stratify=y)
        self.clf = RandomForestClassifier(n_estimators=200, random_state=0, n_jobs=-1)
        self.clf.fit(Xtr, ytr)
        t1 = time.time()
        self.test_accuracy = float((self.clf.predict(Xte) == yte).mean())
        self.infer_ms = (time.time() - t1) / len(Xte) * 1000
        self.train_seconds = t1 - t0
        self.n_train = len(Xtr)
        self.scenario = {l["id"]: "normal" for l in LINKS}
        self.state = {}
        bb84.seed(None)

    def set_attack(self, link_id, scenario):
        if link_id not in self.scenario or scenario not in bb84.SCENARIOS:
            raise KeyError(link_id if link_id not in self.scenario else scenario)
        self.scenario[link_id] = scenario

    def tick(self):
        for link in LINKS:
            m = bb84.run(self.scenario[link["id"]])
            x = np.array([[m[c] for c in bb84.FEATURE_COLS]], dtype=np.float32)
            probs = self.clf.predict_proba(x)[0]
            k = int(np.argmax(probs))
            pred = self.clf.classes_[k]
            secure = pred == "normal" and m["qber"] < QBER_ABORT
            prev = self.state.get(link["id"], {})
            keys = prev.get("keys_distilled", 0) + (1 if secure else 0)
            self.state[link["id"]] = {
                **link,
                "injected": self.scenario[link["id"]],  # demo ground truth
                "qber": round(m["qber"], 4),
                "key_length": m["key_length"],
                "detected": pred,
                "detected_label": LABELS[pred],
                "confidence": round(float(probs[k]), 3),
                "secure": bool(secure),
                "keys_distilled": keys,
                "fallback": None if secure else "Session keys discarded; link fell back to hybrid PQ-TLS (X25519 + ML-KEM-768)",
                "metrics": {c: round(float(m[c]), 5) for c in bb84.FEATURE_COLS},
            }
        return list(self.state.values())

    def summary(self):
        return {"model": "RandomForest (200 trees)", "test_accuracy": round(self.test_accuracy, 4),
                "train_seconds": round(self.train_seconds, 2), "infer_ms": round(self.infer_ms, 4),
                "n_train": self.n_train, "scenarios": LABELS}
