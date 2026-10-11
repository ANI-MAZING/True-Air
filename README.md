# TrueAir

**Air track · Emissions integrity for Indian cities.**

**Live demo:** https://5ecvfcrz6g.ap-south-1.awsapprunner.com (AWS App Runner, ap-south-1)

Pollution control boards decide alerts, school advisories and penalties from data that factories report about themselves. That data gets manipulated: readings capped just under the consent limit, analysers bypassed, old packets replayed, uplinks that go "offline" on bad days. TrueAir checks every stack's self-reported emissions against independent evidence. It flags plants whose numbers don't add up and warns the schools downwind.

> Everything in this repo runs on **simulated data**. Station names are real Delhi CAAQMS locations; all readings, stacks and schools are synthetic.

## What it does

| Layer | How |
|---|---|
| **Signed readings** | Each stack's monitor has a secure element that signs `{reading, counter, timestamp}` with Ed25519. Edits after signing fail verification; replays fail the counter/timestamp check. |
| **Physics checks** | Flatlines below analyser noise, readings piling up just under the consent limit, data gaps. |
| **Independent estimate** | An inverse dispersion model (Gaussian plume + satellite column kernel, solved with NNLS over a 4-hour window) estimates what each stack *actually* emitted from 10 ambient stations and a satellite SO₂ grid. |
| **Learned baseline** | IsolationForest trained only on honest plants flags behaviour that doesn't look like any of them. |
| **Trust score** | Lost fast, regained slowly (+2 per 15 min), so a plant that cheats only on bad days stays flagged. Untrusted stacks are replaced by their inferred emissions everywhere downstream. |
| **School advisories** | AQI at each school (IDW of nearest stations), CPCB/GRAP-aligned actions, and the largest upwind industrial source, with a warning when that source's data isn't trusted. Pushed via SNS when a school's level rises. |
| **Quantum-secure backbone** | BB84 QKD sessions on the regulator links (CPCB ↔ state boards), classified each tick into normal or one of 7 attacks. On attack, keys are discarded and the link falls back to hybrid post-quantum TLS. |

### Default scenario

Seven of the eight plants run clean and report honestly; their emissions stay under their consent limits and the city AQI sits in the Good/Satisfactory range (51-79 across test runs), so schools get no alerts. One plant (OKH-01) runs with its scrubber off and caps its reported SO₂ just under the limit; TrueAir flags it as compromised and over limit.

Any other behaviour can be switched on from the dashboard. Every non-honest behaviour also means the plant runs dirty (scrubber bypassed, 1.9x emissions), which is the reason operators cheat.

### Measured detection

0 false alarms on honest plants across 3,360 stack-checks (6 runs x 80 ticks). Time to detection after switching a clean plant (1 tick = 15 simulated minutes):

| What the operator does | Caught after | Caught by |
|---|---|---|
| Rewrites readings in transit | 1 tick | Signature check |
| Replays old signed packets | 1 tick | Counter / timestamp check |
| Scrubber off, reports honestly | 1 tick | Over limit (data still trusted) |
| Bypasses the analyser (flatline) | 3-5 ticks | Reported value doesn't match the air |
| Goes offline when over the limit | 6 ticks | Missing data |
| Caps readings under the limit | 7 ticks | Readings pile up under the limit; air shows more |
| Sends a false reading in transit | 1 tick | Signature check |
| Feeds a false low/high value into the analyser | 4-6 ticks | Doesn't match stations + satellite |

A plant that is honest but over its limit stays **trusted + over limit**. Clean data about real pollution is a different finding from dishonest data.

## Where quantum fits, and where it doesn't

- **The anti-tampering engine is classical.** Most tampering happens at the source, before any encryption, so QKD can't stop it.
- **QKD protects the regulator backbone**, where data from many plants comes together. The BB84 simulator and 8-scenario attack dataset are ported from [Hybrid-Quantum-Classical-LSTM-for-QKD](https://github.com/ANI-MAZING/Hybrid-Quantum-Classical-LSTM-for-Quantum-Key-Distribution). The live classifier is a random forest. Real QKD needs dedicated fibre and works over ~100 km, so this is a forward-looking demo; hybrid PQ-TLS (X25519 + ML-KEM) is what's deployable today.
- **Quantum lab benchmark** (`scripts/qlstm_benchmark.py`, 2240 train / 960 test sessions, 15 epochs):

  | Model | Accuracy | Train |
  |---|---|---|
  | Random forest | 100.0 % | 0.2 s |
  | Classical LSTM | 99.4 % | 0.3 s |
  | Hybrid QLSTM (4-qubit VQC + LSTM, simulated) | 97.8 % | 2.2 s |

  The script fixes a bug in the original notebook: `torch.tensor(res)` detached the circuit output, so the quantum weights never trained. With the fix they do train (mean |Δθ| ≈ 0.35), and classical models still match or beat the hybrid at this scale.

## Run locally

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --app-dir backend --port 8000
```

Open http://localhost:8000. Demo script:
1. Click **OKH-01** in the ledger. Its reported SO₂ sits flat under the limit while the inferred line runs well above it.
2. Toggle **Show ground truth** to show the judges the inferred line tracks reality.
3. Pick an honest stack (e.g. SBD-06), type a false reading such as `5` into **Send a false SO₂ reading** and send it. In transit, it's caught on the next tick; fed into the analyser, it's caught within a few ticks because the air disagrees. Or switch its behaviour to `mitm_edit`, `flatline`, etc.
4. Turn on **Smog episode**. School advisories escalate, and the event log shows the SNS alerts.
5. Set a QKD link to **Intercept-resend**. QBER jumps past 11 %, the attack is classified and the link falls back to PQ-TLS.

Tests: `.venv/bin/pytest -q`
Quantum lab: `uv pip install --python .venv -r requirements-quantum.txt && .venv/bin/python scripts/qlstm_benchmark.py`

## Deploy on AWS

App Runner (container) + DynamoDB (event log) + SNS (alerts), via CloudFormation:

```bash
AWS_REGION=ap-south-1 ./scripts/deploy.sh you@example.com
```

Needs the AWS CLI, Docker and credentials. The simulation is in-memory, so the service is pinned to one instance.

## Layout

```
backend/app/
  world.py        ground truth: weather, loads, emissions, station + satellite observations
  sensors.py      secure-element signing and the six operator behaviours
  dispersion.py   Gaussian plume + satellite kernel (forward model)
  integrity.py    evidence checks, NNLS inversion, IsolationForest, trust score
  alerts.py       school AQI, advisories, upwind attribution
  quantum/        BB84 simulator (ported) + live QKD link monitor
  aws.py          optional DynamoDB / SNS sinks
  engine.py       tick loop and dashboard snapshot
  main.py         FastAPI
frontend/         console (Leaflet, vanilla JS)
scripts/          qlstm_benchmark.py, deploy.sh
infra/            CloudFormation template
```

## Simulation assumptions to be upfront about

- The satellite grid updates every tick. Real TROPOMI passes once a day at ~13:30 and is much noisier for SO₂, so in practice the stations carry more weight.
- The plume model is steady-state with a fixed stack height and Briggs urban sigmas.
- The secure element is software; in hardware it would be an ATECC608-class chip.
