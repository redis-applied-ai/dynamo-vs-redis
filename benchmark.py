#!/usr/bin/env python3
"""
Latency-focused head-to-head: Redis Cloud vs DynamoDB for raw vector storage.
Author: Tyler @ Redis Applied-AI
"""

import argparse, logging, os, signal, sys, time
from statistics import median, quantiles
import numpy as np, redis, boto3, multiprocessing as mp
from botocore.config import Config

# ---------- Config helpers ----------
def env(name, default=None, required=False):
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Env var {name} is required")
    return val

REDIS_OPTS = dict(
    host=env("REDIS_HOST", required=True),
    port=int(env("REDIS_PORT", 6379)),
    password=env("REDIS_PASSWORD", required=True),
    socket_timeout=2,
)

DDB_TABLE = env("DDB_TABLE", required=True)
AWS_REGION = env("AWS_REGION", "us-east-1")

VECTOR_DIM = 1024
DTYPE = np.float32
VEC_BYTES = VECTOR_DIM * np.dtype(DTYPE).itemsize

# ---------- Vector helpers ----------
def random_vector():
    return np.random.rand(VECTOR_DIM).astype(DTYPE).tobytes()

# ---------- Workers ----------
def redis_worker(task, n_ops):
    r = redis.Redis(**REDIS_OPTS)
    times = []
    for i in range(n_ops):
        k = f"vec:{mp.current_process().pid}:{i}"
        payload = random_vector()
        start = time.perf_counter()
        (r.set if task == "write" else r.get)(k, payload if task == "write" else None)
        times.append(time.perf_counter() - start)
    return times

def dynamo_worker(task, n_ops):
    ddb = boto3.client(
        "dynamodb",
        region_name=AWS_REGION,
        config=Config(retries={"max_attempts": 0}, max_pool_connections=50),
    )
    times = []
    for i in range(n_ops):
        k = f"vec-{mp.current_process().pid}-{i}"
        payload = random_vector()
        start = time.perf_counter()
        if task == "write":
            ddb.put_item(TableName=DDB_TABLE,
                         Item={"id": {"S": k}, "vec": {"B": payload}})
        else:
            ddb.get_item(TableName=DDB_TABLE, Key={"id": {"S": k}})
        times.append(time.perf_counter() - start)
    return times

# ---------- Benchmark orchestrator ----------
def run(db, task, processes, ops):
    worker = redis_worker if db == "redis" else dynamo_worker
    with mp.Pool(processes, maxtasksperchild=ops) as pool:
        results = pool.starmap(worker, [(task, ops)] * processes)
    lat = [t for sub in results for t in sub]
    return {
        "ops": len(lat),
        "qps": len(lat) / sum(lat),
        "p50_ms": median(lat) * 1_000,
        "p95_ms": quantiles(lat, n=100)[94] * 1_000,
        "p99_ms": quantiles(lat, n=100)[98] * 1_000,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["redis", "dynamo"], required=True)
    ap.add_argument("--task", choices=["write", "read"], required=True)
    ap.add_argument("-p", "--proc", type=int, default=8)
    ap.add_argument("-n", "--ops", type=int, default=2_000)
    cfg = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.info("Running %s %s test (%s proc × %s ops)...",
                 cfg.db.upper(), cfg.task, cfg.proc, cfg.ops)
    res = run(cfg.db, cfg.task, cfg.proc, cfg.ops)
    logging.info("Results →  QPS: %.1f  P50: %.2fms  P95: %.2fms  P99: %.2fms",
                 res['qps'], res['p50_ms'], res['p95_ms'], res['p99_ms'])

if __name__ == "__main__":
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: sys.exit(0))
    main()
