"""Quantum lab: hybrid QLSTM vs classical models on the 8-class QKD attack dataset.

Same data generator and QLSTM architecture as the original notebook, with two fixes:
  1. Gradient flow. The notebook built the quantum output with
     `torch.tensor(res)`, which detaches it from the graph, so the circuit
     weights never trained (the VQC acted as a fixed random feature map).
     Here the circuit outputs are stacked as tensors and gradients reach q_params.
  2. Evaluation. Full stratified held-out set (the notebook stopped at ~512
     test samples and trained on 15 %).

Usage:
  pip install -r requirements-quantum.txt
  python scripts/qlstm_benchmark.py --per-class 400 --epochs 10
Writes benchmarks/qkd_benchmark.json, which the dashboard's Quantum lab panel reads.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402
from sklearn.preprocessing import LabelEncoder, StandardScaler  # noqa: E402

from app.quantum.qkd_monitor import build_dataset  # noqa: E402


def timed_eval(predict, X, y):
    t = time.time()
    acc = float((predict(X) == y).mean())
    return acc, (time.time() - t) / len(X) * 1000


def run_rf(Xtr, ytr, Xte, yte):
    t = time.time()
    clf = RandomForestClassifier(n_estimators=200, random_state=0, n_jobs=-1).fit(Xtr, ytr)
    train_s = time.time() - t
    acc, ms = timed_eval(clf.predict, Xte, yte)
    return {"name": "Random forest (classical)", "accuracy": acc, "train_seconds": train_s, "infer_ms": ms}


def run_torch(Xtr, ytr, Xte, yte, epochs, quantum, seed=0):
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)
    Xtr_t = torch.tensor(Xtr.reshape(-1, 3, 3), dtype=torch.float32)
    Xte_t = torch.tensor(Xte.reshape(-1, 3, 3), dtype=torch.float32)
    ytr_t = torch.tensor(ytr, dtype=torch.long)

    if quantum:
        import pennylane as qml

        dev = qml.device("default.qubit", wires=4)

        @qml.qnode(dev, interface="torch")
        def q_gate(inputs, weights):
            # Data re-uploading, as in the notebook. inputs: (batch, 3)
            qml.AngleEmbedding(inputs, wires=range(3), rotation="Y")
            qml.StronglyEntanglingLayers(weights[0], wires=range(4))
            qml.AngleEmbedding(inputs, wires=range(3), rotation="X")
            qml.StronglyEntanglingLayers(weights[1], wires=range(4))
            return [qml.expval(qml.PauliZ(i)) for i in range(4)]

        class HybridQLSTM(nn.Module):
            def __init__(self):
                super().__init__()
                self.q_params = nn.Parameter(0.01 * torch.randn(2, 1, 4, 3))
                self.lstm = nn.LSTM(input_size=4, hidden_size=32, batch_first=True)
                self.fc = nn.Linear(32, 8)

            def forward(self, x):
                b, t, f = x.shape
                # One broadcast circuit call for every (sample, step); torch.stack keeps the graph.
                q = torch.stack(q_gate(x.reshape(b * t, f), self.q_params), dim=-1).float()
                _, (h, _) = self.lstm(q.reshape(b, t, 4))
                return self.fc(h[-1])

        model, lr, name = HybridQLSTM(), 0.01, "Hybrid QLSTM (4-qubit VQC + LSTM)"
    else:
        class ClassicalLSTM(nn.Module):
            def __init__(self):
                super().__init__()
                self.lstm = nn.LSTM(input_size=3, hidden_size=64, batch_first=True)
                self.fc = nn.Linear(64, 8)

            def forward(self, x):
                _, (h, _) = self.lstm(x)
                return self.fc(h[-1])

        model, lr, name = ClassicalLSTM(), 0.005, "Classical LSTM"

    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    q0 = model.q_params.detach().clone() if quantum else None
    t = time.time()
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(Xtr_t))
        for i in range(0, len(perm), 64):
            idx = perm[i:i + 64]
            opt.zero_grad()
            loss = loss_fn(model(Xtr_t[idx]), ytr_t[idx])
            loss.backward()
            opt.step()
        print(f"  {name}: epoch {ep + 1}/{epochs} loss {loss.item():.3f}", flush=True)
    train_s = time.time() - t

    model.eval()

    def predict(X):
        with torch.no_grad():
            return model(torch.tensor(X.reshape(-1, 3, 3), dtype=torch.float32)).argmax(1).numpy()

    acc, ms = timed_eval(predict, Xte, yte)
    out = {"name": name, "accuracy": acc, "train_seconds": train_s, "infer_ms": ms,
           "params": sum(p.numel() for p in model.parameters())}
    if quantum:
        out["q_params_moved"] = float((model.q_params.detach() - q0).abs().mean())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=400)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--skip-quantum", action="store_true")
    args = ap.parse_args()

    X, labels = build_dataset(args.per_class, seed=42)
    y = LabelEncoder().fit_transform(labels)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)
    sc = StandardScaler().fit(Xtr)
    Xtr_s, Xte_s = sc.transform(Xtr).astype(np.float32), sc.transform(Xte).astype(np.float32)
    Xtr_s += np.random.default_rng(0).normal(0, 0.05, Xtr_s.shape).astype(np.float32)  # paper Eq. 10

    models = [run_rf(Xtr, ytr, Xte, yte), run_torch(Xtr_s, ytr, Xte_s, yte, args.epochs, quantum=False)]
    if not args.skip_quantum:
        models.append(run_torch(Xtr_s, ytr, Xte_s, yte, args.epochs, quantum=True))

    result = {
        "note": f"{len(Xtr)} train / {len(Xte)} test BB84 sessions, 8 classes, {args.epochs} epochs, simulated circuit",
        "models": models,
    }
    out = ROOT / "benchmarks" / "qkd_benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    for m in models:
        print(f"{m['name']:38s} acc {m['accuracy']:.3%}  train {m['train_seconds']:.1f}s  infer {m['infer_ms']:.3f} ms")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
