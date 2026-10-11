"""Indian National AQI (CPCB) sub-index calculation."""

# (conc_lo, conc_hi, index_lo, index_hi)
BREAKPOINTS = {
    "pm25": [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200),
             (91, 120, 201, 300), (121, 250, 301, 400), (251, 500, 401, 500)],
    "pm10": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200),
             (251, 350, 201, 300), (351, 430, 301, 400), (431, 600, 401, 500)],
    "no2":  [(0, 40, 0, 50), (41, 80, 51, 100), (81, 180, 101, 200),
             (181, 280, 201, 300), (281, 400, 301, 400), (401, 800, 401, 500)],
    "so2":  [(0, 40, 0, 50), (41, 80, 51, 100), (81, 380, 101, 200),
             (381, 800, 201, 300), (801, 1600, 301, 400), (1601, 2400, 401, 500)],
}

CATEGORIES = [(50, "Good"), (100, "Satisfactory"), (200, "Moderate"),
              (300, "Poor"), (400, "Very Poor"), (500, "Severe")]


def sub_index(pollutant, conc):
    bps = BREAKPOINTS[pollutant]
    conc = max(0.0, conc)
    for k, (lo, hi, ilo, ihi) in enumerate(bps):
        # CPCB bands are integer ranges (0-30, 31-60...); treat each as [lo, next_lo).
        next_lo = bps[k + 1][0] if k + 1 < len(bps) else float("inf")
        if conc < next_lo:
            c = min(max(conc, lo), hi)
            return ilo + (ihi - ilo) * (c - lo) / (hi - lo)
    return 500.0


def category(aqi):
    for limit, name in CATEGORIES:
        if aqi <= limit:
            return name
    return "Severe"


def compute(concs):
    """concs: dict pollutant -> µg/m³. Returns (aqi, category, dominant)."""
    subs = {p: sub_index(p, c) for p, c in concs.items() if p in BREAKPOINTS}
    dominant = max(subs, key=subs.get)
    aqi = round(subs[dominant])
    return aqi, category(aqi), dominant
