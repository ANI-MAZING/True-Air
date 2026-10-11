# TrueAir: submission video script (under 3 minutes)

About 380 spoken words, which leaves room for the demo to breathe. Timings are targets.
Open the live site before recording: https://5ecvfcrz6g.ap-south-1.awsapprunner.com

---

## 0:00 – 0:30 · About the project

**Show:** the dashboard, zoomed out on the map. Hover over a red stack.

> In India, highly polluting factories have to stream their own emissions data to the pollution control board. That data drives penalties, AQI alerts and school closures. But the factory owns the monitor, and there are known ways to cheat: capping readings just under the limit, bypassing the analyser, replaying clean data, or going offline on bad days.
>
> TrueAir checks whether factories are telling the truth about their pollution, and warns the schools downwind when the air turns bad.

## 0:30 – 1:40 · Live demo

**Show:** click OKH-01 in the stack ledger.

> Okhla reports a steady 195 kilograms an hour of SO₂, just under its 210 limit. But the dashed line is what the air itself says. TrueAir works backwards from ten ambient stations and satellite SO₂ readings, using the wind and a dispersion model, to estimate what each chimney really emitted. The air says about 280. So the plant is flagged compromised and over limit.

**Show:** turn on Show ground truth for two seconds, then off.

> Ground truth from the simulator confirms the estimate tracks reality.

**Show:** click SBD-06, an honest plant. Type 5 in Send a false SO₂ reading, choose Rewrite it in transit, press Send.

> Now I'll fake a reading on an honest plant. Each monitor signs its readings in a secure chip, so a value changed in transit fails the signature check on the very next reading.

**Show:** the stack turns red. Scroll to the event log.

> If the operator feeds the fake value into the analyser instead, the signature is valid, but within a few readings the air disagrees and it's caught anyway.

**Show:** turn on Smog episode. Scroll to School advisories.

> On a smog day, every school gets an action from CPCB and GRAP guidance, plus the factory upwind of it, with a warning when that factory's data isn't trusted.

## 1:40 – 2:05 · Where quantum fits

**Show:** the QKD panel. Set CPCB ↔ HSPCB to Intercept-resend.

> Data from many plants flows over the links between the central and state boards. Those links run BB84 quantum key distribution. An eavesdropper pushes the error rate past eleven percent, a classifier identifies the attack, and the link falls back to post-quantum TLS. Our benchmark is honest: on this data, classical models still beat the hybrid quantum LSTM.

## 2:05 – 2:40 · Tech stack, architecture and AWS

**Show:** the architecture slide or the README architecture section.

> The backend is Python and FastAPI, with SciPy for the inverse model, scikit-learn for anomaly detection, Ed25519 signatures, and PennyLane for the quantum experiments. The dashboard is Leaflet and plain JavaScript.
>
> On AWS, the app is a Docker image in Amazon ECR, running on AWS App Runner in Mumbai. Every integrity verdict and alert is stored in DynamoDB. Amazon SNS sends alert digests to subscribers, and the whole stack is one CloudFormation template, with IAM roles and an AWS Budgets alarm.

## 2:40 – 3:00 · Learning and growth

> Along the way I learned how organisation-level policies can block an account no matter what IAM says, why alert systems need throttling, and that I had a gradient bug in my own quantum model. Fixing it taught me to benchmark quantum honestly. TrueAir is simulated today. The next step is real CPCB and Sentinel-5P data. Thanks for watching.

---

## Recording checklist

- **Window:** 1920×1080 browser window, page zoom 110–125% so text is readable.
- **Before recording:** let the simulation run about 30 seconds so the charts have history. Switch Smog episode off and set the QKD links to Normal.
- **Tools:** QuickTime (File → New Screen Recording) or OBS. Record the voice-over separately if you stumble; it's easier to edit.
- **Upload:** YouTube as **Unlisted**, title "TrueAir: catching tampered factory emissions data (AWS hackathon)". Put the repo and live links in the description.
- **Before submitting:** check the final length is under 3:00.
