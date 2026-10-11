"""Stack-side monitoring units (CEMS) and the ways operators cheat them.

Each unit has a secure element holding an Ed25519 key that signs the raw
measurement together with a monotonic counter. The operator controls everything
*after* the secure element (the DAHS PC, the gateway, the uplink), which is
where the tampering behaviours below live.
"""
import json
import random
from collections import deque

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature

BEHAVIOURS = {
    "honest": "Reports what the analyser measures",
    "clip_at_limit": "Caps reported SO2 just under the consent limit",
    "flatline": "Analyser bypassed; DAHS sends a constant clean value",
    "replay": "Re-sends signed packets recorded on a clean day",
    "mitm_edit": "Gateway scales values down after the secure element signs them",
    "dark_on_bad_days": "Uplink goes 'offline' whenever true emissions are high",
}


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class SecureElement:
    def __init__(self):
        self._key = Ed25519PrivateKey.generate()
        self.public_key = self._key.public_key()
        self.counter = 0

    def sign(self, payload):
        self.counter += 1
        body = dict(payload, seq=self.counter)
        return body, self._key.sign(canonical(body)).hex()


def verify(public_key, body, sig_hex):
    try:
        public_key.verify(bytes.fromhex(sig_hex), canonical(body))
        return True
    except (InvalidSignature, ValueError):
        return False


class MonitoringUnit:
    def __init__(self, stack, rng: random.Random):
        self.stack = stack
        self.behaviour = stack.behaviour
        self.rng = rng
        self.se = SecureElement()
        self.recorded = deque(maxlen=96)   # clean-day packets kept for replay
        self.replay_idx = 0

    def measure(self, true_vals, ts):
        """Analyser reading with ~3 % instrument noise."""
        n = lambda v: max(0.0, v * self.rng.gauss(1.0, 0.03))
        return {"stack_id": self.stack.id, "ts": ts,
                "so2": round(n(true_vals["so2"]), 2),
                "nox": round(n(true_vals["nox"]), 2),
                "pm": round(n(true_vals["pm"]), 2),
                "load": round(true_vals["load"], 3)}

    def emit(self, true_vals, ts):
        """Returns the packet that reaches the regulator, or None if nothing arrives."""
        reading = self.measure(true_vals, ts)
        b = self.behaviour

        if b == "flatline":
            # The analyser is bypassed, so the secure element signs a fake input.
            reading.update(so2=round(18 + self.rng.gauss(0, 0.05), 2),
                           nox=round(12 + self.rng.gauss(0, 0.05), 2),
                           pm=round(9 + self.rng.gauss(0, 0.05), 2))
        elif b == "clip_at_limit":
            cap = 0.95 * self.stack.so2_limit
            if reading["so2"] > cap:
                reading["so2"] = round(cap * self.rng.uniform(0.9, 1.0), 2)

        body, sig = self.se.sign(reading)

        if b == "replay":
            if len(self.recorded) < 24:
                # Warm-up: record low-load packets to replay later.
                if true_vals["load"] < 0.7 or not self.recorded:
                    self.recorded.append((body, sig))
            if self.recorded:
                old_body, old_sig = self.recorded[self.replay_idx % len(self.recorded)]
                self.replay_idx += 1
                # Operator can't re-sign, so the signature is valid but the
                # counter and timestamp are stale.
                return dict(body=old_body, sig=old_sig)
        if b == "mitm_edit":
            body = dict(body, so2=round(body["so2"] * 0.45, 2), nox=round(body["nox"] * 0.5, 2))
        if b == "dark_on_bad_days" and true_vals["so2"] > 0.85 * self.stack.base_so2:
            return None
        return dict(body=body, sig=sig)
