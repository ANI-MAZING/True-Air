"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const AQI_BANDS = [50, 100, 200, 300, 400, Infinity];
const aqiColor = (a) => css(`--aqi-${AQI_BANDS.findIndex((b) => a <= b) + 1}`);
const STATUS_LABEL = { trusted: "Trusted", suspect: "Suspect", compromised: "Compromised", warming_up: "Warming up" };
const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

let meta = null;
let state = null;
let selected = null;
let showTruth = false;
let showSat = true;
let paused = false;

// ---------------- map ----------------
const map = L.map("map", { zoomControl: true, attributionControl: true, scrollWheelZoom: false }).setView([28.63, 77.2], 10);
const dark = () => matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light"
  || document.documentElement.dataset.theme === "dark";
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap contributors", maxZoom: 18,
}).addTo(map);
map.fitBounds([[28.38, 77.0], [28.88, 77.4]]);
function setTiles() { document.documentElement.classList.toggle("darkTiles", dark()); }
setTiles();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", setTiles);

const layers = {
  sat: L.layerGroup().addTo(map),
  links: L.layerGroup().addTo(map),
  stations: L.layerGroup().addTo(map),
  schools: L.layerGroup().addTo(map),
  stacks: L.layerGroup().addTo(map),
};
const markers = { stacks: {}, stations: {}, schools: {} };

function upsert(group, key, latlng, html, popup, onClick) {
  let m = markers[group][key];
  const icon = L.divIcon({ className: "", html, iconSize: null });
  if (!m) {
    m = L.marker(latlng, { icon, keyboard: true }).addTo(layers[group]);
    if (onClick) m.on("click", onClick);
    m.bindTooltip("", { direction: "top", offset: [0, -14] });
    markers[group][key] = m;
  } else {
    m.setIcon(icon);
  }
  m.setTooltipContent(popup);
  return m;
}

function drawMap(s) {
  layers.sat.clearLayers();
  if (showSat) {
    const vals = s.satellite.map((c) => c.so2);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const dLat = (28.88 - 28.38) / 6 / 2, dLon = (77.38 - 77.0) / 6 / 2;
    const sulfur = css("--sulfur");
    s.satellite.forEach((c) => {
      const k = (c.so2 - lo) / Math.max(hi - lo, 1);
      L.rectangle([[c.lat - dLat, c.lon - dLon], [c.lat + dLat, c.lon + dLon]], {
        stroke: false, fillColor: sulfur, fillOpacity: 0.04 + 0.32 * k, interactive: false,
      }).addTo(layers.sat);
    });
  }

  layers.links.clearLayers();
  s.qkd.forEach((l) => {
    L.polyline([l.a_ll, l.b_ll], {
      color: l.secure ? css("--ok") : css("--bad"), weight: 3, dashArray: l.secure ? "1 6" : "8 4", lineCap: "round",
    }).bindTooltip(`QKD ${esc(l.a)} ↔ ${esc(l.b)}: ${l.secure ? "secure" : esc(l.detected_label)}`).addTo(layers.links);
  });

  s.stations.forEach((st) => upsert("stations", st.id, [st.lat, st.lon],
    `<div class="stationMarker" style="background:${aqiColor(st.aqi)}">${st.aqi}</div>`,
    `<b>${esc(st.name)}</b> · AQI ${st.aqi} (${esc(st.category)})<br>PM2.5 ${st.concs.pm25} · NO₂ ${st.concs.no2} · SO₂ ${st.concs.so2} µg/m³`));

  s.schools.forEach((sc) => upsert("schools", sc.id, [sc.lat, sc.lon],
    `<div class="schoolMarker l${sc.level}"></div>`,
    `<b>${esc(sc.name)}</b><br>AQI ${sc.aqi} · ${esc(sc.title)}`));

  s.stacks.forEach((k) => upsert("stacks", k.id, [k.lat, k.lon],
    `<div class="stackMarker ${k.status}${selected === k.id ? " sel" : ""}">${esc(k.id.slice(0, 3))}</div>`,
    `<b>${esc(k.name)}</b> · ${STATUS_LABEL[k.status]} (${k.score}/100)`,
    () => select(k.id)));
}

// ---------------- panels ----------------
function drawHeader(s) {
  const a = $("cityAqi");
  a.textContent = s.city.aqi;
  a.style.background = aqiColor(s.city.aqi);
  a.style.color = "#fff";
  $("cityCat").textContent = s.city.category;
  $("simTime").textContent = s.t.slice(11, 16);
  $("dayNight").textContent = `${s.t.slice(0, 10)} · ${s.night ? "night (shallow mixing)" : "day"}`;
  $("windArrow").style.transform = `rotate(${s.wind.from}deg)`;
  $("windTxt").textContent = `${s.wind.speed.toFixed(1)} m/s`;
  $("windFrom").textContent = `from ${COMPASS[Math.round(s.wind.from / 22.5) % 16]} (${Math.round(s.wind.from)}°)`;
  $("btnSmog").setAttribute("aria-pressed", s.smog);
}

function drawLedger(s) {
  const order = { compromised: 0, suspect: 1, warming_up: 2, trusted: 3 };
  const rows = [...s.stacks].sort((a, b) => order[a.status] - order[b.status] || a.score - b.score);
  $("stackList").innerHTML = rows.map((k) => {
    const why = k.reasons.length ? esc(k.reasons[0]) :
      (k.exceeding_limit ? `Honest data, but SO₂ ${k.reported_so2} kg/h is over its ${k.so2_limit} kg/h limit` : `Reporting ${k.reported_so2 ?? "–"} kg/h SO₂`);
    return `<li class="stackRow ${k.status}${selected === k.id ? " sel" : ""}" data-id="${esc(k.id)}" tabindex="0">
      <span class="stripe"></span>
      <span class="stackName"><span class="id">${esc(k.id)}</span>${esc(k.name)}</span>
      <span>${k.exceeding_limit ? '<span class="pill exceed">Over limit</span> ' : ""}<span class="pill ${k.status}">${STATUS_LABEL[k.status]}</span></span>
      <span class="stackWhy">${why}${showTruth ? ` <em>· sim: ${esc(meta?.behaviours?.[k.behaviour] ?? k.behaviour)}</em>` : ""}</span>
    </li>`;
  }).join("");
}

function drawSchools(s) {
  const rows = [...s.schools].sort((a, b) => b.aqi - a.aqi);
  $("schoolList").innerHTML = rows.map((sc) => `<li class="school">
    <span class="aqiChip" style="background:${aqiColor(sc.aqi)}">${sc.aqi}</span>
    <div><b>${esc(sc.name)}</b>
      <p><strong>${esc(sc.title)}.</strong> ${esc(sc.text)}</p>
      ${sc.contributor && sc.level >= 2 ? `<p class="${sc.contributor.trust !== "trusted" ? "src" : ""}">Upwind source: ${esc(sc.contributor.name)} (+${sc.contributor.so2_ugm3} µg/m³ SO₂${sc.contributor.trust !== "trusted" ? ", data not trusted" : ""})</p>` : ""}
    </div></li>`).join("");
}

function drawQkd(s) {
  const scen = meta ? Object.entries(meta.qkd.scenarios) : [];
  $("qkdList").innerHTML = s.qkd.map((l) => `<div class="link ${l.secure ? "" : "insecure"}">
    <span class="ends">${esc(l.a)} ↔ ${esc(l.b)}</span>
    <span class="pill ${l.secure ? "trusted" : "compromised"}">${l.secure ? "Secure" : esc(l.detected_label)}</span>
    <div class="qberBar" title="QBER on a 0–30 % scale; the line marks the 11 % BB84 abort threshold"><span style="width:${Math.min(100, l.qber / 0.30 * 100)}%"></span></div>
    <div class="stats"><span>QBER <b>${(l.qber * 100).toFixed(1)}%</b></span><span>Key <b>${l.key_length}</b> bits</span>
      <span>Classifier <b>${esc(l.detected_label)}</b> (${Math.round(l.confidence * 100)}%)</span><span>Keys distilled <b>${l.keys_distilled}</b></span></div>
    ${l.fallback ? `<div class="fallback">${esc(l.fallback)}</div>` : ""}
    <div class="field" style="grid-column:1/3"><label for="atk-${esc(l.id)}">Simulate on this link</label>
      <select id="atk-${esc(l.id)}" data-link="${esc(l.id)}">${scen.map(([k, v]) => `<option value="${esc(k)}"${k === l.injected ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
  </div>`).join("");
}

function drawEvents(s) {
  $("eventList").innerHTML = s.events.length ? s.events.map((e) => `<li class="event ${esc(e.severity)}">
    <time>${esc(e.t.slice(11, 16))}</time><span class="kind">${esc(e.kind)}</span><span>${esc(e.message)}</span></li>`).join("")
    : `<li class="empty">No events yet. Try the smog toggle or an attack on a QKD link.</li>`;
}

// ---------------- stack detail ----------------
function chartSvg(hist, limit) {
  const W = 640, H = 220, P = { l: 40, r: 12, t: 10, b: 24 };
  const pts = hist.slice(-96);
  if (!pts.length) return "";
  const vals = pts.flatMap((h) => [h.reported, h.inferred, showTruth ? h.true : null]).filter((v) => v != null);
  const ymax = Math.max(limit * 1.15, ...vals) * 1.05;
  const x = (i) => P.l + (i / Math.max(pts.length - 1, 1)) * (W - P.l - P.r);
  const y = (v) => P.t + (1 - v / ymax) * (H - P.t - P.b);
  const path = (key) => {
    let d = "", pen = false;
    pts.forEach((h, i) => {
      const v = h[key];
      const okPoint = v != null && (key !== "reported" || h.status === "ok");
      if (okPoint) { d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; } else pen = false;
    });
    return d;
  };
  const step = ymax > 150 ? 50 : ymax > 60 ? 20 : 10;
  const ticks = []; for (let v = 0; v <= ymax; v += step) ticks.push(v);
  const marks = pts.map((h, i) => h.status === "missing"
    ? `<rect class="miss" x="${x(i) - 2}" y="${H - P.b + 4}" width="4" height="6"><title>${h.t.slice(11, 16)} no data</title></rect>`
    : h.status !== "ok" ? `<rect class="bad" x="${x(i) - 2}" y="${H - P.b + 4}" width="4" height="6"><title>${h.t.slice(11, 16)} ${h.status}</title></rect>` : "").join("");
  const xl = [[0, "start"], [Math.floor(pts.length / 2), "middle"], [pts.length - 1, "end"]].map(([i, a]) =>
    `<text x="${x(i)}" y="${H - 1}" text-anchor="${a}">${pts[i].t.slice(11, 16)}</text>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="SO2 time series">
    <g class="grid">${ticks.map((v) => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${P.l - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("")}</g>
    <line class="lim" x1="${P.l}" x2="${W - P.r}" y1="${y(limit)}" y2="${y(limit)}"/>
    <text x="${W - P.r}" y="${y(limit) - 4}" text-anchor="end" style="fill:var(--bad)">consent limit ${limit}</text>
    ${showTruth ? `<path class="tru" d="${path("true")}"/>` : ""}
    <path class="inf" d="${path("inferred")}"/>
    <path class="rep" d="${path("reported")}"/>
    ${marks}${xl}
  </svg>`;
}

async function drawDetail() {
  if (!selected || !state) return;
  const k = state.stacks.find((s) => s.id === selected);
  const hist = await fetch(`/api/stacks/${encodeURIComponent(selected)}/history`).then((r) => r.json());
  $("detailH").textContent = `${k.id} · ${k.name}`;
  const behaviours = meta ? Object.entries(meta.behaviours) : [];
  const focused = document.activeElement?.id === "behaviourSel";
  if (focused) return; // don't rebuild the select while someone is using it
  $("detailBody").innerHTML = `
    <div><div class="chartWrap">${chartSvg(hist, k.so2_limit)}</div>
      <div class="chartKey"><span><i style="border-color:var(--ink)"></i>Reported (verified packets only)</span>
      <span><i style="border-color:var(--sulfur);border-top-style:dashed"></i>Inferred from stations + satellite</span>
      ${showTruth ? `<span><i style="border-color:var(--muted)"></i>Ground truth (sim)</span>` : ""}
      <span><i style="border-color:var(--bad)"></i>Tick marks: rejected / missing packets</span></div></div>
    <div class="facts">
      <div class="fact"><span>Trust score</span><span class="num">${k.score}/100 · <span class="pill ${k.status}">${STATUS_LABEL[k.status]}</span></span></div>
      <div class="fact"><span>Last packet</span><span class="num">${esc(k.packet_status ?? "–")}</span></div>
      <div class="fact"><span>Reported SO₂</span><span class="num">${k.reported_so2 ?? "–"} kg/h</span></div>
      <div class="fact"><span>Inferred SO₂ (4 h mean)</span><span class="num">${k.inferred_so2 ?? "not observable"}${k.inferred_so2 != null ? " kg/h" : ""}</span></div>
      ${showTruth ? `<div class="fact"><span>True SO₂ (sim)</span><span class="num">${k.true_so2} kg/h</span></div>` : ""}
      <div class="fact"><span>Anomaly score</span><span class="num">${k.anomaly}</span></div>
      ${k.reasons.length ? `<ul class="reasons">${k.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : `<p class="empty">No integrity issues in the last 4 hours.</p>`}
      <div class="field"><label for="behaviourSel">Operator behaviour (simulation control)</label>
        <select id="behaviourSel">${behaviours.map(([b, d]) => `<option value="${esc(b)}"${b === k.behaviour ? " selected" : ""}>${esc(b)}: ${esc(d)}</option>`).join("")}</select></div>
    </div>`;
}

function select(id) {
  selected = id;
  if (state) { drawLedger(state); drawMap(state); }
  drawDetail();
}

async function drawBenchmark() {
  const b = await fetch("/api/quantum/benchmark").then((r) => r.json());
  const q = meta.qkd;
  $("qkdModel").textContent = `Live classifier: ${q.model}, ${(q.test_accuracy * 100).toFixed(1)}% held-out accuracy, ${q.infer_ms.toFixed(3)} ms/session`;
  if (!b.available) { $("bench").innerHTML = `<p>Quantum lab: ${esc(b.hint)}</p>`; return; }
  $("bench").innerHTML = `<p><b>Quantum lab benchmark</b> (${esc(b.note ?? "")})</p><div class="benchWrap"><table>
    <thead><tr><th>Model</th><th class="num">Accuracy</th><th class="num">Train s</th><th class="num">ms / sample</th></tr></thead>
    <tbody>${b.models.map((m) => `<tr><td>${esc(m.name)}</td><td class="num">${(m.accuracy * 100).toFixed(1)}%</td><td class="num">${m.train_seconds.toFixed(1)}</td><td class="num">${m.infer_ms.toFixed(3)}</td></tr>`).join("")}</tbody></table></div>`;
}

// ---------------- loop ----------------
async function refresh() {
  try {
    state = await fetch("/api/state").then((r) => r.json());
    drawHeader(state); drawMap(state); drawLedger(state); drawSchools(state); drawEvents(state);
    if (!document.activeElement?.dataset?.link) drawQkd(state);
    drawDetail();
  } catch (e) { console.warn("refresh failed", e); }
}

const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

document.addEventListener("click", (e) => {
  const row = e.target.closest(".stackRow");
  if (row) select(row.dataset.id);
});
document.addEventListener("keydown", (e) => {
  const row = e.target.closest?.(".stackRow");
  if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(row.dataset.id); }
});
document.addEventListener("change", async (e) => {
  if (e.target.id === "behaviourSel") {
    await post(`/api/control/stacks/${encodeURIComponent(selected)}`, { behaviour: e.target.value });
    e.target.blur(); refresh();
  } else if (e.target.dataset.link) {
    await post(`/api/control/qkd/${encodeURIComponent(e.target.dataset.link)}`, { scenario: e.target.value });
    e.target.blur(); refresh();
  } else if (e.target.id === "chkSat") {
    showSat = e.target.checked; if (state) drawMap(state);
  }
});
$("btnSmog").addEventListener("click", async () => {
  await post("/api/control/smog", { on: $("btnSmog").getAttribute("aria-pressed") !== "true" }); refresh();
});
$("btnTruth").addEventListener("click", () => {
  showTruth = !showTruth; $("btnTruth").setAttribute("aria-pressed", showTruth); refresh();
});
$("btnPause").addEventListener("click", async () => {
  paused = !paused; $("btnPause").setAttribute("aria-pressed", paused);
  $("btnPause").textContent = paused ? "Resume" : "Pause";
  await post("/api/control/pause", { on: paused });
});

(async function boot() {
  meta = await fetch("/api/meta").then((r) => r.json());
  const aws = meta.aws;
  $("awsStatus").textContent = aws.dynamodb || aws.sns
    ? `Persisting to DynamoDB ${aws.dynamodb ?? "off"} · SNS ${aws.sns ? "on" : "off"}`
    : "Local mode: events kept in memory (set TRUEAIR_TABLE / TRUEAIR_TOPIC_ARN on AWS)";
  await refresh();
  const first = state?.stacks.find((k) => k.status === "compromised") ?? state?.stacks[0];
  if (first) select(first.id);
  drawBenchmark();
  setInterval(refresh, 2000);
})();
