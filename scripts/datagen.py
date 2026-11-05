"""Deterministic dataset generator. Same profile + seed => identical keys, sizes and bytes.

Note: the 'logs' kind is gzip-compressed; its exact bytes depend on the local zlib build, so
sizes are not pre-computable (seed skips existing log keys by presence). All other kinds are
byte-for-byte reproducible and sizes are known up front.
"""
from __future__ import annotations

import gzip
import json
import random
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
DEPTS = ["accounting", "treasury", "payroll", "tax", "audit", "fpa"]
SERVICES = ["api", "auth", "billing", "worker", "gateway"]


def load_profile(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if not p.exists():
        p = PROFILES_DIR / f"{name_or_path}.json"
    if not p.exists():
        raise SystemExit(f"Profile not found: {name_or_path}")
    return json.loads(p.read_text(encoding="utf-8"))


def _rng(seed: int, prefix: str, i: int) -> random.Random:
    return random.Random(f"{seed}|{prefix}|{i}")


def _size(rng: random.Random, ds: dict) -> int:
    lo, hi = ds["min_size"], ds["max_size"]
    return lo + int((hi - lo) * rng.random() ** 2)  # skewed toward smaller objects


def key_and_size(seed: int, ds: dict, i: int) -> tuple[str, int | None]:
    """Return (key, exact_size or None when size is not known before generation)."""
    rng = _rng(seed, ds["prefix"], i)
    kind = ds["kind"]
    if kind == "finance":
        year = rng.choice([2021, 2022, 2023, 2024, 2025])
        month = rng.randint(1, 12)
        dept = rng.choice(DEPTS)
        ext, stem = rng.choices([("csv", "ledger"), ("json", "invoice"), ("pdf", "statement")], [5, 3, 2])[0]
        return f"{ds['prefix']}{year}/{month:02d}/{dept}/{stem}-{i:06d}.{ext}", _size(rng, ds)
    if kind == "customers":
        return f"{ds['prefix']}{i % 256:03d}/cust-{i:06d}.json", _size(rng, ds)
    if kind == "media":
        return f"{ds['prefix']}{i % 50:02d}/clip-{i:05d}.bin", _size(rng, ds)
    if kind == "logs":
        y, m, d = 2026, rng.randint(1, 12), rng.randint(1, 28)
        svc = rng.choice(SERVICES)
        return f"{ds['prefix']}{y}/{m:02d}/{d:02d}/{svc}-{i:06d}.log.gz", None
    raise ValueError(f"unknown kind {kind}")


def _tile(block: bytes, n: int) -> bytes:
    return (block * (n // max(len(block), 1) + 1))[:n]


def _json_body(rng: random.Random, size: int, extra: dict) -> bytes:
    rows = [{"id": rng.getrandbits(40), "amount": round(rng.random() * 10000, 2),
             "ref": rng.randbytes(6).hex()} for _ in range(6)]
    head = json.dumps({**extra, "records": rows, "pad": ""}, separators=(",", ":")).encode()
    head = head[: -len('""}')]  # strip closing of empty pad
    pad = _tile(rng.randbytes(48).hex().encode(), max(size - len(head) - 3, 0))
    return head + b'"' + pad + b'"}'


def make_body(seed: int, ds: dict, i: int) -> tuple[str, bytes]:
    key, size = key_and_size(seed, ds, i)
    rng = _rng(seed, ds["prefix"], i)
    _size(rng, ds) if size is not None else None  # keep rng stream aligned with key_and_size
    kind = ds["kind"]
    if kind == "finance":
        if key.endswith(".csv"):
            rows = "".join(f"{rng.getrandbits(32)},{round(rng.random() * 9999, 2)},{rng.randbytes(4).hex()}\n"
                           for _ in range(12))
            return key, _tile(("id,amount,ref\n" + rows).encode(), size)
        if key.endswith(".json"):
            return key, _json_body(rng, size, {"type": "invoice", "n": i})
        stub = b"%PDF-1.4\n" + _tile(rng.randbytes(32).hex().encode() + b"\n", max(size - 15, 0)) + b"\n%%EOF\n"
        return key, stub[:size] if len(stub) > size else stub + b" " * (size - len(stub))
    if kind == "customers":
        return key, _json_body(rng, size, {"type": "customer", "n": i, "name": f"cust-{i}"})
    if kind == "media":
        return key, rng.randbytes(size)
    # logs
    target = rng.randint(ds["min_size"], ds["max_size"])
    raw = "\n".join(f"2026-01-01T00:00:{n % 60:02d}Z INFO req={rng.randbytes(8).hex()} {rng.randbytes(32).hex()}"
                    for n in range(max(target // 110, 1))).encode()
    return key, gzip.compress(raw, compresslevel=6, mtime=0)
