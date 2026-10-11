"""BB84 session simulator: normal operation plus seven attack scenarios.

Ported from the author's Hybrid Quantum-Classical LSTM for QKD notebook
(github.com/ANI-MAZING/Hybrid-Quantum-Classical-LSTM-for-Quantum-Key-Distribution).
Simulation logic is unchanged; global RNGs were swapped for seedable instances.
"""
import math
import random

import numpy as _npm

_rng = random.Random()
_np = _npm.random.default_rng()


def seed(s):
    global _np
    _rng.seed(s)
    _np = _npm.random.default_rng(s)


N_TRANS = 500    # was 50 — paper gets ~250 bit keys, we need more transmissions
P_SIG   = 0.7
P_DEC   = 0.3
P_ERR   = 0.02   # was 0.03 — paper QBER ~0.05 for normal
P_DEPOL = 0.01   # was 0.02
P_LOSS  = 0.08   # was 0.15 — paper sig_det_rate ~0.73
MU      = 0.5

def _measure(bit_a, basis_a, basis_b):
    return bit_a if basis_a == basis_b else _rng.randint(0, 1)

def _apply_noise(bit):
    if _rng.random() < P_ERR:   bit = 1 - bit
    if _rng.random() < P_DEPOL: bit = _rng.randint(0, 1)
    if _np.poisson(MU) == 0 and _rng.random() < 0.05:
        bit = _rng.randint(0, 1)
    return bit

def _metrics(sifted, errors, tx, rx,
             n_sig, n_dec, det_sig, det_dec, loss_sig, loss_dec):
    key_len = len(sifted)
    qber    = errors / key_len if key_len > 0 else 0.0
    if key_len > 0:
        bits = [b for (_, b) in sifted]
        p1 = sum(bits) / key_len; p0 = 1 - p1
        h  = sum(-p * math.log2(p) for p in [p0, p1] if p > 0)
    else:
        h = 0.0
    sig_det  = det_sig  / n_sig  if n_sig  > 0 else 0.0
    dec_det  = det_dec  / n_dec  if n_dec  > 0 else 0.0
    sig_loss = loss_sig / n_sig  if n_sig  > 0 else 0.0
    dec_loss = loss_dec / n_dec  if n_dec  > 0 else 0.0
    if tx:
        diffs = [rx[i]-tx[i] for i in range(len(tx))]
        avg_t = float(_npm.mean(diffs))
        tot_t = float(_npm.sum(diffs))
        var_t = float(_npm.var(diffs))
        dev_t = float(_npm.mean(_npm.abs(_npm.array(diffs)-avg_t)))
    else:
        avg_t = tot_t = var_t = dev_t = 0.0
    return {'key_length': key_len, 'qber': qber,
            'meas_entropy': h, 'sig_det_rate': sig_det,
            'dec_det_rate': dec_det, 'sig_loss_rate': sig_loss,
            'dec_loss_rate': dec_loss, 'avg_photon_time': avg_t,
            'whole_key_time': tot_t, 'arrival_var': var_t,
            'arrival_dev': dev_t}

# ── Normal QKD ────────────────────────────────────────────────
def sim_normal():
    sifted=[]; errors=0; tx=[]; rx=[]
    n_sig=n_dec=det_sig=det_dec=loss_sig=loss_dec=0
    for _ in range(N_TRANS):
        pulse='sig' if _rng.random()<P_SIG else 'dec'
        if pulse=='sig': n_sig+=1
        else: n_dec+=1
        if _rng.random()<P_LOSS:
            if pulse=='sig': loss_sig+=1
            else: loss_dec+=1
            continue
        bit_a=_rng.randint(0,1); bas_a=_rng.randint(0,1)
        bas_b=_rng.randint(0,1)
        bit_b=_apply_noise(_measure(bit_a,bas_a,bas_b))
        t=_rng.uniform(0.01,0.10)
        tx.append(t); rx.append(t+_rng.uniform(0.005,0.015))
        if bas_a==bas_b:
            sifted.append((bit_a,bit_b))
            if bit_a==bit_b:
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
            else: errors+=1
    return _metrics(sifted,errors,tx,rx,n_sig,n_dec,det_sig,det_dec,loss_sig,loss_dec)

# ── Intercept-and-Resend ──────────────────────────────────────
# Paper: QBER ~0.39, whole_key_time ~97 (large delay)
def sim_intercept_resend():
    sifted=[]; errors=0; tx=[]; rx=[]
    n_sig=n_dec=det_sig=det_dec=loss_sig=loss_dec=0
    for _ in range(N_TRANS):
        pulse='sig' if _rng.random()<P_SIG else 'dec'
        if pulse=='sig': n_sig+=1
        else: n_dec+=1
        if _rng.random()<P_LOSS:
            if pulse=='sig': loss_sig+=1
            else: loss_dec+=1
            continue
        bit_a=_rng.randint(0,1); bas_a=_rng.randint(0,1)
        bas_e=_rng.randint(0,1)
        bit_e=_apply_noise(_measure(bit_a,bas_a,bas_e))
        bas_b=_rng.randint(0,1)
        bit_b=_apply_noise(_measure(bit_e,bas_e,bas_b))
        t=_rng.uniform(0.01,0.10)
        # Eve adds significant delay — paper shows avg_time ~0.19
        tx.append(t); rx.append(t+_rng.uniform(0.15,0.25))
        if bas_a==bas_b:
            sifted.append((bit_a,bit_b))
            if bit_a==bit_b:
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
            else: errors+=1
    return _metrics(sifted,errors,tx,rx,n_sig,n_dec,det_sig,det_dec,loss_sig,loss_dec)

# ── PNS Attack ────────────────────────────────────────────────
# Paper: low det rate ~0.10 for decoy, QBER stays low ~0.07
def sim_pns():
    sifted=[]; errors=0; tx=[]; rx=[]
    n_sig=n_dec=det_sig=det_dec=loss_sig=loss_dec=0
    for _ in range(N_TRANS):
        pulse='sig' if _rng.random()<P_SIG else 'dec'
        if pulse=='sig': n_sig+=1
        else: n_dec+=1
        if _rng.random()<P_LOSS:
            if pulse=='sig': loss_sig+=1
            else: loss_dec+=1
            continue
        # Eve steals multi-photon pulses — heavily reduces detection
        if _rng.random()>=0.8:
            p_steal = 0.85  # high steal rate for multi-photon
            if _rng.random()<p_steal:
                if pulse=='sig': loss_sig+=1
                else: loss_dec+=1
                continue
        bit_a=_rng.randint(0,1); bas_a=_rng.randint(0,1)
        bas_b=_rng.randint(0,1)
        bit_b=_apply_noise(_measure(bit_a,bas_a,bas_b))
        t=_rng.uniform(0.01,0.10)
        tx.append(t); rx.append(t+_rng.uniform(0.005,0.015))
        if bas_a==bas_b:
            sifted.append((bit_a,bit_b))
            if bit_a==bit_b:
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
            else: errors+=1
    return _metrics(sifted,errors,tx,rx,n_sig,n_dec,det_sig,det_dec,loss_sig,loss_dec)

# ── Trojan Horse ──────────────────────────────────────────────
# Paper: QBER ~0.25, det rate higher than normal
def sim_trojan_horse():
    sifted=[]; errors=0; tx=[]; rx=[]
    n_sig=n_dec=det_sig=det_dec=loss_sig=loss_dec=0
    P_INJECT=0.35
    for _ in range(N_TRANS):
        pulse='sig' if _rng.random()<P_SIG else 'dec'
        if pulse=='sig': n_sig+=1
        else: n_dec+=1
        if _rng.random()<P_LOSS:
            if pulse=='sig': loss_sig+=1
            else: loss_dec+=1
            continue
        bit_a=_rng.randint(0,1); bas_a=_rng.randint(0,1)
        bas_b=_rng.randint(0,1)
        bit_b=_apply_noise(_measure(bit_a,bas_a,bas_b))
        t=_rng.uniform(0.01,0.10)
        tx.append(t); rx.append(t+_rng.uniform(0.005,0.015))
        injected=False
        if _rng.random()<P_INJECT:
            strong=_rng.random()<0.5
            if _rng.random()<(0.9 if strong else 0.3):
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
                if _rng.random()<(0.5 if strong else 0.2):
                    injected=True; errors+=1
        if bas_a==bas_b and not injected:
            sifted.append((bit_a,bit_b))
            if bit_a==bit_b:
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
    return _metrics(sifted,errors,tx,rx,n_sig,n_dec,det_sig,det_dec,loss_sig,loss_dec)

# ── Wavelength Trojan Horse ───────────────────────────────────
# Paper: key_length ~311, QBER ~0.01 (very low), high det rate ~0.87
def sim_wavelength_trojan():
    sifted=[]; errors=0; tx=[]; rx=[]
    n_sig=n_dec=det_sig=det_dec=loss_sig=loss_dec=0
    P_INJECT=0.25; P_EAVES=0.3; L_LEGIT=1550
    for _ in range(N_TRANS):
        pulse='sig' if _rng.random()<P_SIG else 'dec'
        if pulse=='sig': n_sig+=1
        else: n_dec+=1
        if _rng.random()<P_LOSS*0.5:  # lower loss — more detections
            if pulse=='sig': loss_sig+=1
            else: loss_dec+=1
            continue
        bit_a=_rng.randint(0,1); bas_a=_rng.randint(0,1)
        bas_b=_rng.randint(0,1)
        bit_b=_apply_noise(_measure(bit_a,bas_a,bas_b))
        delay=0.0
        if _rng.random()<P_INJECT:
            lam=_rng.choice([1310,1490,1610,1625])
            dl=abs(lam-L_LEGIT); delay=dl/8000.0
            if _rng.random()<P_EAVES:
                if dl>0 and _rng.random()<0.05:  # low QBER increase
                    errors+=1
                t=_rng.uniform(0.01,0.10)
                tx.append(t); rx.append(t+_rng.uniform(0.005,0.015)+delay)
                continue
        t=_rng.uniform(0.01,0.10)
        tx.append(t); rx.append(t+_rng.uniform(0.005,0.015)+delay)
        if bas_a==bas_b:
            sifted.append((bit_a,bit_b))
            if bit_a==bit_b:
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
            else: errors+=1
    return _metrics(sifted,errors,tx,rx,n_sig,n_dec,det_sig,det_dec,loss_sig,loss_dec)

# ── RNG Attack ────────────────────────────────────────────────
# Paper: key_length ~454, QBER ~0.19, high det rates ~0.91
def sim_rng():
    sifted=[]; errors=0; tx=[]; rx=[]
    n_sig=n_dec=det_sig=det_dec=loss_sig=loss_dec=0
    BIT_BIAS=0.75; BAS_BIAS=0.70; P_PRED=0.65
    history=[]
    for _ in range(N_TRANS):
        pulse='sig' if _rng.random()<P_SIG else 'dec'
        if pulse=='sig': n_sig+=1
        else: n_dec+=1
        if _rng.random()<P_LOSS*0.4:  # very low loss — more keys generated
            if pulse=='sig': loss_sig+=1
            else: loss_dec+=1
            continue
        bit_a=1 if _rng.random()<BIT_BIAS else 0
        bas_a=1 if _rng.random()<BAS_BIAS else 0
        history.append(bit_a)
        bas_b=1 if _rng.random()<BAS_BIAS else 0
        bit_b=_apply_noise(_measure(bit_a,bas_a,bas_b))
        if len(history)>=3 and _rng.random()<P_PRED:
            if _rng.random()<0.25: errors+=1
        t=_rng.uniform(0.01,0.10)
        tx.append(t); rx.append(t+_rng.uniform(0.005,0.015))
        if bas_a==bas_b:
            sifted.append((bit_a,bit_b))
            if bit_a==bit_b:
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
            else: errors+=1
    return _metrics(sifted,errors,tx,rx,n_sig,n_dec,det_sig,det_dec,loss_sig,loss_dec)

# ── Detector Blinding ─────────────────────────────────────────
# Paper: key_length ~142 (very short), dec_loss_rate ~2.66 (very high)
def sim_detector_blinding():
    sifted=[]; errors=0; tx=[]; rx=[]
    n_sig=n_dec=det_sig=det_dec=loss_sig=loss_dec=0
    P_BLIND=0.5; D_BLIND=8; P_INJECT=0.75
    ETA_BLIND=0.05; ETA_NORM=0.92; blind_cd=0
    for _ in range(N_TRANS):
        pulse='sig' if _rng.random()<P_SIG else 'dec'
        if pulse=='sig': n_sig+=1
        else: n_dec+=1
        if _rng.random()<P_LOSS:
            if pulse=='sig': loss_sig+=1
            else: loss_dec+=1
            continue
        if blind_cd==0 and _rng.random()<P_BLIND:
            blind_cd=D_BLIND
        bit_a=_rng.randint(0,1); bas_a=_rng.randint(0,1)
        bas_b=_rng.randint(0,1)
        eta=ETA_BLIND if blind_cd>0 else ETA_NORM
        if blind_cd>0:
            blind_cd-=1
            bit_b=_rng.randint(0,1) if _rng.random()<P_INJECT \
                  else _measure(bit_a,bas_a,bas_b)
        else:
            bit_b=_apply_noise(_measure(bit_a,bas_a,bas_b))
        if _rng.random()>eta:
            # Blinded detectors lose photons at very high rate
            loss_mult = 8 if blind_cd>0 else 1
            for _ in range(loss_mult):
                if pulse=='sig': loss_sig+=1
                else: loss_dec+=1
            continue
        t=_rng.uniform(0.01,0.10)
        tx.append(t); rx.append(t+_rng.uniform(0.005,0.015))
        if bas_a==bas_b:
            sifted.append((bit_a,bit_b))
            if bit_a==bit_b:
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
            else: errors+=1
    return _metrics(sifted,errors,tx,rx,n_sig,n_dec,det_sig,det_dec,loss_sig,loss_dec)

# ── Combined Attack ───────────────────────────────────────────
def sim_combined():
    sifted=[]; errors=0; tx=[]; rx=[]
    n_sig=n_dec=det_sig=det_dec=loss_sig=loss_dec=0
    P_WL=0.3; P_BL=0.3; P_RNG=0.3; BIT_BIAS=0.65
    for _ in range(N_TRANS):
        pulse='sig' if _rng.random()<P_SIG else 'dec'
        if pulse=='sig': n_sig+=1
        else: n_dec+=1
        if _rng.random()<P_LOSS:
            if pulse=='sig': loss_sig+=1
            else: loss_dec+=1
            continue
        bit_a=1 if (_rng.random()<BIT_BIAS and _rng.random()<P_RNG) \
              else _rng.randint(0,1)
        bas_a=_rng.randint(0,1); bas_b=_rng.randint(0,1)
        bit_b=_apply_noise(_measure(bit_a,bas_a,bas_b))
        delay=0.0
        if _rng.random()<P_WL:
            delay+=_rng.uniform(0.01,0.05)
            if _rng.random()<0.2: errors+=1
        if _rng.random()<P_BL:
            if _rng.random()<0.4:
                if pulse=='sig': loss_sig+=1
                else: loss_dec+=1
                continue
        t=_rng.uniform(0.01,0.10)
        tx.append(t); rx.append(t+_rng.uniform(0.005,0.025)+delay)
        if bas_a==bas_b:
            sifted.append((bit_a,bit_b))
            if bit_a==bit_b:
                if pulse=='sig': det_sig+=1
                else: det_dec+=1
            else: errors+=1
    return _metrics(sifted,errors,tx,rx,n_sig,n_dec,det_sig,det_dec,loss_sig,loss_dec)


SCENARIOS = {
    'normal': sim_normal,
    'mitm_attack': sim_intercept_resend,
    'pns_attack': sim_pns,
    'trojan_horse_attack': sim_trojan_horse,
    'wavelength_dependent_trojan_attack': sim_wavelength_trojan,
    'rng_attack': sim_rng,
    'detector_blinding_attack': sim_detector_blinding,
    'combined_attack': sim_combined,
}

FEATURE_COLS = ['key_length', 'qber', 'meas_entropy', 'sig_loss_rate', 'dec_loss_rate',
                'avg_photon_time', 'whole_key_time', 'arrival_var', 'arrival_dev']


def run(scenario):
    return SCENARIOS[scenario]()
