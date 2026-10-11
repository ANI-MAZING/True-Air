import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import Engine

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = Path(os.getenv("TRUEAIR_FRONTEND", ROOT / "frontend"))
BENCHMARK = Path(os.getenv("TRUEAIR_BENCHMARK", ROOT / "benchmarks" / "qkd_benchmark.json"))

state = {}


@asynccontextmanager
async def lifespan(app):
    engine = Engine(tick_seconds=float(os.getenv("TRUEAIR_TICK_SECONDS", "2")))
    stop = threading.Event()
    th = threading.Thread(target=engine.run_forever, args=(stop,), daemon=True)
    th.start()
    state["engine"] = engine
    yield
    stop.set()


app = FastAPI(title="TrueAir", lifespan=lifespan)


def eng() -> Engine:
    return state["engine"]


class Behaviour(BaseModel):
    behaviour: str


class Injection(BaseModel):
    so2: float
    method: str = "transit"   # transit | analyser
    ticks: int = 8


class Toggle(BaseModel):
    on: bool


class Attack(BaseModel):
    scenario: str


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/state")
def get_state():
    return eng().snapshot


@app.get("/api/meta")
def meta():
    return eng().meta()


@app.get("/api/stacks/{stack_id}/history")
def history(stack_id: str):
    try:
        return eng().stack_history(stack_id)
    except KeyError:
        raise HTTPException(404, "unknown stack")


@app.post("/api/control/stacks/{stack_id}")
def set_behaviour(stack_id: str, body: Behaviour):
    try:
        eng().set_behaviour(stack_id, body.behaviour)
    except KeyError as e:
        raise HTTPException(400, f"unknown {e}")
    return {"ok": True}


@app.post("/api/control/stacks/{stack_id}/inject")
def inject(stack_id: str, body: Injection):
    if not 0 <= body.so2 <= 5000 or not 1 <= body.ticks <= 48:
        raise HTTPException(400, "so2 must be 0-5000 kg/h and ticks 1-48")
    try:
        eng().inject_reading(stack_id, body.so2, body.method, body.ticks)
    except (KeyError, StopIteration) as e:
        raise HTTPException(400, f"unknown {e}")
    return {"ok": True}


@app.post("/api/control/smog")
def smog(body: Toggle):
    eng().set_smog(body.on)
    return {"ok": True}


@app.post("/api/control/pause")
def pause(body: Toggle):
    eng().paused = body.on
    return {"ok": True}


@app.post("/api/control/qkd/{link_id}")
def qkd_attack(link_id: str, body: Attack):
    try:
        eng().set_qkd_attack(link_id, body.scenario)
    except KeyError as e:
        raise HTTPException(400, f"unknown {e}")
    return {"ok": True}


@app.get("/api/quantum/benchmark")
def benchmark():
    if not BENCHMARK.exists():
        return {"available": False,
                "hint": "Run scripts/qlstm_benchmark.py to compare the hybrid QLSTM against classical models."}
    return {"available": True, **json.loads(BENCHMARK.read_text())}


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
