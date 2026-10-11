"""Static geography for the Delhi NCR demo scenario.

Station names are real CAAQMS locations; every reading attached to them in this
project is simulated. Stacks and schools are fictional.
"""
from dataclasses import dataclass
import math


@dataclass
class Stack:
    id: str
    name: str
    lat: float
    lon: float
    base_so2: float          # kg/h at full load
    base_nox: float
    base_pm: float
    behaviour: str = "honest"  # see sensors.BEHAVIOURS
    so2_limit: float = 0.0   # consent limit, kg/h; defaults to 1.5 x base_so2 (compliant at full load)

    def __post_init__(self):
        if not self.so2_limit:
            self.so2_limit = 1.5 * self.base_so2


@dataclass
class Station:
    id: str
    name: str
    lat: float
    lon: float


@dataclass
class School:
    id: str
    name: str
    lat: float
    lon: float
    students: int


STACKS = [
    Stack("OKH-01", "Okhla Thermal Unit", 28.530, 77.285, 140, 95, 40, "clip_at_limit"),
    Stack("WZP-02", "Wazirpur Steel Pickling", 28.700, 77.165, 60, 40, 30, "honest"),
    Stack("NRL-03", "Narela Plastics Moulding", 28.850, 77.095, 35, 30, 55, "honest"),
    Stack("BWN-04", "Bawana Rubber Works", 28.800, 77.040, 50, 35, 45, "honest"),
    Stack("MYP-05", "Mayapuri Metal Recovery", 28.635, 77.125, 45, 28, 60, "honest"),
    Stack("SBD-06", "Sahibabad Dyeing Cluster", 28.680, 77.345, 80, 50, 35, "honest"),
    Stack("FBD-07", "Faridabad Forging Plant", 28.400, 77.310, 90, 70, 50, "honest"),
    Stack("MDK-08", "Mundka Brick Kiln Row", 28.680, 77.030, 70, 45, 80, "honest"),
]

STATIONS = [
    Station("ANV", "Anand Vihar", 28.647, 77.316),
    Station("ITO", "ITO", 28.629, 77.241),
    Station("RKP", "R.K. Puram", 28.563, 77.187),
    Station("PJB", "Punjabi Bagh", 28.674, 77.131),
    Station("OKH", "Okhla Phase-2", 28.531, 77.271),
    Station("WZP", "Wazirpur", 28.700, 77.165),
    Station("NRL", "Narela", 28.823, 77.102),
    Station("BWN", "Bawana", 28.776, 77.051),
    Station("MDK", "Mundka", 28.684, 77.077),
    Station("FBD", "Faridabad Sec-16", 28.409, 77.315),
]

SCHOOLS = [
    School("S01", "Govt. Sr. Sec. School, Okhla", 28.545, 77.278, 1800),
    School("S02", "Sarvodaya Vidyalaya, Wazirpur", 28.705, 77.172, 1400),
    School("S03", "Govt. Boys School, Narela", 28.840, 77.090, 1100),
    School("S04", "Primary School, Anand Vihar", 28.650, 77.300, 900),
    School("S05", "Model School, Punjabi Bagh", 28.670, 77.140, 1600),
    School("S06", "Govt. Girls School, Faridabad", 28.415, 77.305, 1300),
    School("S07", "Kendriya Vidyalaya, R.K. Puram", 28.566, 77.180, 2100),
    School("S08", "Pratibha Vidyalaya, Mundka", 28.690, 77.060, 1000),
]

# Satellite grid covering the scenario (Sentinel-5P pixels are ~5.5 x 3.5 km;
# we use a coarser 6x6 grid to keep the demo light).
GRID_LAT = (28.38, 28.88)
GRID_LON = (77.00, 77.38)
GRID_N = 6


def grid_cells():
    cells = []
    dlat = (GRID_LAT[1] - GRID_LAT[0]) / GRID_N
    dlon = (GRID_LON[1] - GRID_LON[0]) / GRID_N
    for i in range(GRID_N):
        for j in range(GRID_N):
            cells.append((GRID_LAT[0] + (i + 0.5) * dlat, GRID_LON[0] + (j + 0.5) * dlon))
    return cells


def km_offsets(lat1, lon1, lat2, lon2):
    """East/north offset in km from point 1 to point 2."""
    dn = (lat2 - lat1) * 111.0
    de = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return de, dn


def haversine_km(lat1, lon1, lat2, lon2):
    de, dn = km_offsets(lat1, lon1, lat2, lon2)
    return math.hypot(de, dn)
