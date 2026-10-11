"""Forward dispersion models used both to simulate the world and to invert it.

Ground stations: steady-state Gaussian plume (Briggs urban sigmas).
Satellite: a wide Gaussian kernel nudged downwind, mimicking a column
measurement that smears point sources over tens of km.
"""
import math
import numpy as np

from .geo import km_offsets

STACK_HEIGHT_M = 50.0
MIN_DOWNWIND_M = 300.0


def plume_weight(src_lat, src_lon, rec_lat, rec_lon, wind_from_deg, wind_speed):
    """Concentration (µg/m³) at receptor per 1 kg/h emitted at source."""
    de, dn = km_offsets(src_lat, src_lon, rec_lat, rec_lon)
    # Wind blows *from* wind_from_deg, so it travels towards wind_from_deg + 180.
    to = math.radians((wind_from_deg + 180.0) % 360.0)
    ux, uy = math.sin(to), math.cos(to)
    x = (de * ux + dn * uy) * 1000.0          # downwind, m
    y = (-de * uy + dn * ux) * 1000.0         # crosswind, m
    if x <= 0:
        return 0.0
    x = max(x, MIN_DOWNWIND_M)
    sy = 0.32 * x / math.sqrt(1 + 0.0004 * x)  # Briggs urban, neutral-ish
    sz = 0.24 * x * math.sqrt(1 + 0.001 * x)
    q = 1000.0 / 3600.0                       # 1 kg/h in g/s
    u = max(wind_speed, 0.5)
    c = q / (math.pi * u * sy * sz) * math.exp(-y * y / (2 * sy * sy)) \
        * math.exp(-STACK_HEIGHT_M ** 2 / (2 * sz * sz))
    return c * 1e6                            # g/m³ → µg/m³


def satellite_weight(src_lat, src_lon, cell_lat, cell_lon, wind_from_deg, wind_speed):
    """Column enhancement (arbitrary µmol/m² units) per 1 kg/h."""
    to = math.radians((wind_from_deg + 180.0) % 360.0)
    shift_km = 4.0 * min(wind_speed, 6.0) / 3.0
    de, dn = km_offsets(src_lat, src_lon, cell_lat, cell_lon)
    de -= shift_km * math.sin(to)
    dn -= shift_km * math.cos(to)
    sigma = 7.0
    return 1.5 * math.exp(-(de * de + dn * dn) / (2 * sigma * sigma))


def influence_matrix(stacks, receptors, wind_from_deg, wind_speed, kind="plume"):
    fn = plume_weight if kind == "plume" else satellite_weight
    W = np.zeros((len(receptors), len(stacks)))
    for i, (rlat, rlon) in enumerate(receptors):
        for j, s in enumerate(stacks):
            W[i, j] = fn(s.lat, s.lon, rlat, rlon, wind_from_deg, wind_speed)
    return W
