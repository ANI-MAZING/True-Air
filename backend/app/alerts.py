"""School advisories for bad-air days.

Levels follow CPCB health-advisory bands and Delhi's GRAP stages.
"""
from . import aqi as aqi_mod
from .dispersion import plume_weight
from .geo import haversine_km

LEVELS = [
    (100, 0, "Normal day", "No restrictions."),
    (200, 1, "Caution", "Children with asthma should skip strenuous outdoor PE today."),
    (300, 2, "Move indoors", "Hold PE and morning assembly inside. Keep classroom windows shut during peak traffic hours."),
    (400, 3, "No outdoor activity", "Cancel outdoor sport and recess. Run classroom air purifiers. Notify parents of children with asthma."),
    (10_000, 4, "Consider hybrid classes", "AQI is Severe (GRAP Stage IV territory). Recommend hybrid/online classes for primary grades."),
]


def level_for(aqi):
    for limit, lvl, title, text in LEVELS:
        if aqi <= limit:
            return lvl, title, text
    return LEVELS[-1][1:]


def school_aqi(school, stations, station_aqi):
    """Inverse-distance weighted AQI from the three nearest stations."""
    d = sorted((haversine_km(school.lat, school.lon, s.lat, s.lon), station_aqi[s.id]) for s in stations)[:3]
    w = [1 / max(km, 0.5) ** 2 for km, _ in d]
    return round(sum(wi * a for wi, (_, a) in zip(w, d)) / sum(w)), round(d[0][0], 1)


def top_contributor(school, stacks, ledgers, wind_from, wind_speed):
    """Which stack is pushing the most SO₂ towards this school right now, using
    the best available emission estimate (inferred if the stack isn't trusted)."""
    best = None
    for s in stacks:
        L = ledgers[s.id]
        rate = L.inferred if (L.status != "trusted" and L.inferred) else (
            L.events[-1]["so2"] if L.events and L.events[-1]["so2"] is not None else 0)
        c = plume_weight(s.lat, s.lon, school.lat, school.lon, wind_from, wind_speed) * rate
        if c > 0.3 and (best is None or c > best[1]):
            best = (s, c)
    if not best:
        return None
    s, c = best
    return {"stack_id": s.id, "name": s.name, "so2_ugm3": round(c, 1), "trust": ledgers[s.id].status}


def advisory(school, a, nearest_km, contributor):
    lvl, title, text = level_for(a)
    msg = f"{school.name}: AQI {a} ({aqi_mod.category(a)}). {title}: {text}"
    if contributor and lvl >= 2:
        flag = " (its self-reported data is NOT trusted)" if contributor["trust"] in ("suspect", "compromised") else ""
        msg += f" Largest local industrial source upwind: {contributor['name']}{flag}."
    return {"level": lvl, "title": title, "text": text, "message": msg}
