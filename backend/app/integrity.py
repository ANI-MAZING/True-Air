"""Integrity engine: decides how far to trust each stack's self-reported data.

Evidence, cheapest first:
  1. Cryptographic   - Ed25519 signature from the stack's secure element
  2. Freshness       - monotonic counter and timestamp (catches replay)
  3. Availability    - data gaps, and whether gaps coincide with high emissions
  4. Physics         - flatlines, readings piling up just under the consent limit
  5. Independent     - inverse dispersion model over ambient stations + satellite
                       estimates what each stack *actually* emitted
  6. Learned         - IsolationForest over the window features, trained on honest plants
"""
from collections import deque

import numpy as np
from scipy.optimize import nnls
from sklearn.ensemble import IsolationForest

from . import sensors

WINDOW = 16          # ticks (4 h of simulated time)
MIN_WINDOW = 6
RECOVERY_PER_TICK = 2  # ~8 points per simulated hour


class StackLedger:
    def __init__(self, stack, public_key):
        self.stack = stack
        self.public_key = public_key
        self.last_seq = 0
        self.events = deque(maxlen=WINDOW)    # per tick: dict(status, so2, load)
        self.history = deque(maxlen=200)      # for charts
        self.inferred = None
        self.reasons = []
        self.score = 100
        self.status = "warming_up"
        self.anomaly = 0.0


def window_features(ledger):
    ev = list(ledger.events)
    ok = [e for e in ev if e["status"] == "ok"]
    so2 = np.array([e["so2"] for e in ok]) if ok else np.array([0.0])
    load = np.array([max(e["load"], 1e-3) for e in ok]) if ok else np.array([1.0])
    lim = ledger.stack.so2_limit
    cv = float(so2.std() / (so2.mean() + 1e-6))
    clip = float(np.mean((so2 > 0.85 * lim) & (so2 <= 0.96 * lim))) if ok else 0.0
    gap = sum(e["status"] == "missing" for e in ev) / max(len(ev), 1)
    per_load = so2 / load
    per_load_cv = float(per_load.std() / (per_load.mean() + 1e-6))
    ratio = 1.0
    if ledger.inferred is not None and ok:
        ratio = float(so2.mean() / max(ledger.inferred, 1e-3))
    return np.array([cv, clip, gap, min(ratio, 3.0), per_load_cv])


class IntegrityEngine:
    def __init__(self, stacks, public_keys):
        self.stacks = stacks
        self.ledgers = {s.id: StackLedger(s, public_keys[s.id]) for s in stacks}
        self.obs = deque(maxlen=WINDOW)
        self.iforest = None

    # ---------- evidence 1-3 ----------
    def ingest(self, stack_id, packet, now_iso):
        L = self.ledgers[stack_id]
        if packet is None:
            L.events.append({"status": "missing", "so2": None, "load": None})
            L.history.append({"t": now_iso, "reported": None, "status": "missing"})
            return
        body, sig = packet["body"], packet["sig"]
        if not sensors.verify(L.public_key, body, sig):
            status = "bad_signature"
        elif body["seq"] <= L.last_seq or body["ts"] != now_iso:
            status = "replay"
        else:
            status = "ok"
            L.last_seq = body["seq"]
        L.events.append({"status": status, "so2": body["so2"], "load": body["load"]})
        L.history.append({"t": now_iso, "reported": body["so2"], "status": status})

    # ---------- evidence 5 ----------
    def invert(self, snap):
        """Non-negative least squares over the window: per-tick backgrounds +
        one mean SO2 emission rate per stack."""
        self.obs.append(snap)
        T, N = len(self.obs), len(self.stacks)
        if T < MIN_WINDOW:
            return None
        rows, rhs = [], []
        n_bg = 2 * T
        for k, o in enumerate(self.obs):
            for block, y, sigma, bg_col in (
                (o["W"], o["stations"]["so2"], 1.0, k),
                (o["S"], o["satellite_so2"], 4.0, T + k),
            ):
                for i in range(block.shape[0]):
                    r = np.zeros(N + n_bg)
                    r[:N] = block[i]
                    r[N + bg_col] = 1.0
                    rows.append(r / sigma)
                    rhs.append(y[i] / sigma)
        A, b = np.array(rows), np.array(rhs)
        # light ridge towards zero keeps unobservable (always upwind) stacks sane
        A = np.vstack([A, np.hstack([np.eye(N) * 0.002, np.zeros((N, n_bg))])])
        b = np.concatenate([b, np.zeros(N)])
        x, _ = nnls(A, b, maxiter=2000)
        est = x[:N]
        # observability: how strongly the window's receptors "see" each stack
        sens = np.array([sum(o["W"][:, j].sum() + o["S"][:, j].sum() / 400 for o in self.obs)
                         for j in range(N)])
        for j, s in enumerate(self.stacks):
            self.ledgers[s.id].inferred = float(est[j]) if sens[j] > 0.05 else None
        return est

    # ---------- evidence 4 + 6, and scoring ----------
    def fit_baseline(self, feature_rows):
        self.iforest = IsolationForest(n_estimators=150, contamination=0.02, random_state=0)
        self.iforest.fit(np.array(feature_rows))

    def score(self, now_iso):
        out = {}
        for sid, L in self.ledgers.items():
            ev = list(L.events)
            if len(ev) < MIN_WINDOW:
                L.status = "warming_up"
                out[sid] = L
                continue
            f = window_features(L)
            cv, clip, gap, ratio, _ = f
            n_ok = sum(e["status"] == "ok" for e in ev)
            pen, reasons = 0, []
            n_bad = sum(e["status"] == "bad_signature" for e in ev)
            n_rep = sum(e["status"] == "replay" for e in ev)
            lim = L.stack.so2_limit
            if n_bad:
                pen += 40 + min(30, 100 * n_bad // len(ev))
                reasons.append(f"{n_bad}/{len(ev)} packets failed signature check (altered after signing)")
            if n_rep:
                pen += 40 + min(30, 100 * n_rep // len(ev))
                reasons.append(f"{n_rep}/{len(ev)} packets replayed (stale counter/timestamp)")
            if gap > 0.2:
                pen += min(70, round(80 * gap)); reasons.append(f"{gap:.0%} of readings missing")
            if n_ok >= MIN_WINDOW and cv < 0.01:
                pen += 35; reasons.append(f"Flatline: variation {cv:.2%} is below any real analyser's noise")
            if n_ok >= MIN_WINDOW and clip > 0.4:
                pen += 30; reasons.append(f"{clip:.0%} of SO₂ readings sit just under the consent limit")
            if L.inferred is not None and n_ok and ratio < 0.7:
                pen += 35; reasons.append(
                    f"Reports {ratio:.0%} of what stations + satellite imply ({L.inferred:.0f} kg/h)")
            elif L.inferred is not None and n_ok and L.inferred > 1.1 * lim and ratio * L.inferred < lim:
                pen += 30; reasons.append(
                    f"Independent estimate {L.inferred:.0f} kg/h is over the {lim:.0f} kg/h limit; reports stay under it")
            if L.inferred is not None and pen and not any("estimate" in r or "imply" in r for r in reasons):
                reasons.append(f"Independent estimate: {L.inferred:.0f} kg/h SO₂")
            if self.iforest is not None:
                L.anomaly = float(-self.iforest.score_samples([f])[0])
                if self.iforest.predict([f])[0] == -1:
                    pen += 15; reasons.append("Behaviour pattern unlike any honest plant (IsolationForest)")
            # Trust is lost fast and regained slowly: a plant that cheats only on
            # bad days must not look clean again by the next quiet night.
            fresh = max(0, 100 - pen)
            L.score = fresh if L.status == "warming_up" else min(fresh, L.score + RECOVERY_PER_TICK)
            if fresh > L.score and not reasons:
                reasons.append(f"Recovering trust after earlier violations ({L.score}/100)")
            L.status = "trusted" if L.score >= 75 else "suspect" if L.score >= 40 else "compromised"
            L.reasons = reasons
            if L.history:
                L.history[-1]["inferred"] = L.inferred
            out[sid] = L
        return out
