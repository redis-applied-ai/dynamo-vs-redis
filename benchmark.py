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

# DynamoDB config (will be set when needed)
DDB_TABLE = None
AWS_REGION = None

VECTOR_DIM = 1024
DTYPE = np.float32
VEC_BYTES = VECTOR_DIM * np.dtype(DTYPE).itemsize

# ---------- Vector helpers ----------
def generate_vectors(num_vector: int):
    """Generate n_ops random vectors"""
    vectors = np.random.rand(num_vector, VECTOR_DIM).astype(DTYPE)
    return [vec.tobytes() for vec in vectors]

# ---------- Workers ----------
def redis_worker(work_batch):
    """Redis worker that processes a batch of operations with a single connection"""
    task, work_items = work_batch
    
    # Establish connection once per process
    r = redis.Redis(**REDIS_OPTS)
    times = []
    
    for key, vector in work_items:
        start = time.perf_counter()
        if task == "write":
            r.set(key, vector)
        else:  # read
            r.get(key)
        times.append(time.perf_counter() - start)
    
    return times

def dynamo_worker(work_batch):
    """DynamoDB worker that processes a batch of operations with a single connection"""
    task, work_items = work_batch
    
    # Establish connection once per process
    ddb = boto3.client(
        "dynamodb",
        region_name=AWS_REGION,
        config=Config(retries={"max_attempts": 0}, max_pool_connections=50),
    )
    times = []
    
    for key, vector in work_items:
        start = time.perf_counter()
        if task == "write":
            ddb.put_item(TableName=DDB_TABLE,
                         Item={"id": {"S": key}, "vec": {"B": vector}})
        else:  # read
            ddb.get_item(TableName=DDB_TABLE, Key={"id": {"S": key}})
        times.append(time.perf_counter() - start)
    
    return times

# ---------- Benchmark orchestrator ----------
def run_phase(db, task, processes, all_keys, all_vectors=None):
    """Run a single phase (write or read) of the benchmark"""
    worker = redis_worker if db == "redis" else dynamo_worker
    
    # Create work items (key, vector) pairs
    if task == "write":
        work_items = list(zip(all_keys, all_vectors))
    else:  # read
        work_items = [(key, None) for key in all_keys]
    
    # Distribute work items across processes
    items_per_process = len(work_items) // processes
    extra_items = len(work_items) % processes
    
    work_batches = []
    start_idx = 0
    
    for i in range(processes):
        # Some processes get an extra item if work doesn't divide evenly
        batch_size = items_per_process + (1 if i < extra_items else 0)
        end_idx = start_idx + batch_size
        
        batch_items = work_items[start_idx:end_idx]
        work_batches.append((task, batch_items))
        start_idx = end_idx
    
    # Execute batches in parallel - each process handles multiple operations
    with mp.Pool(processes) as pool:
        results = pool.map(worker, work_batches)
    
    # Flatten results from all processes
    all_times = [time for batch_times in results for time in batch_times]
    
    return {
        "ops": len(all_times),
        "qps": len(all_times) / sum(all_times) if sum(all_times) > 0 else 0,
        "p50_ms": median(all_times) * 1000,
        "p95_ms": quantiles(all_times, n=100)[94] * 1000,
        "p99_ms": quantiles(all_times, n=100)[98] * 1000,
    }

def main():
    global DDB_TABLE, AWS_REGION
    
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["redis", "dynamo"], required=True)
    ap.add_argument("-p", "--proc", type=int, default=8, help="Number of processes")
    ap.add_argument("-n", "--ops", type=int, default=2000, help="Total number of operations")
    cfg = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    # Set DynamoDB config if needed
    if cfg.db == "dynamo":
        DDB_TABLE = env("DDB_TABLE", required=True)
        AWS_REGION = env("AWS_REGION", "us-east-1")
    
    # Generate vectors and keys upfront
    logging.info("Generating %d vectors...", cfg.ops)
    all_vectors = generate_vectors(cfg.ops)
    all_keys = [f"vec:{i}" for i in range(cfg.ops)]
    
    # Run write phase
    logging.info("Running %s WRITE test (%d proc × %d ops)...",
                 cfg.db.upper(), cfg.proc, cfg.ops)
    write_res = run_phase(cfg.db, "write", cfg.proc, all_keys, all_vectors)
    logging.info("WRITE Results → QPS: %.1f  P50: %.2fms  P95: %.2fms  P99: %.2fms",
                 write_res['qps'], write_res['p50_ms'], write_res['p95_ms'], write_res['p99_ms'])
    
    # Run read phase
    logging.info("Running %s READ test (%d proc × %d ops)...",
                 cfg.db.upper(), cfg.proc, cfg.ops)
    read_res = run_phase(cfg.db, "read", cfg.proc, all_keys, None)
    logging.info("READ Results → QPS: %.1f  P50: %.2fms  P95: %.2fms  P99: %.2fms",
                 read_res['qps'], read_res['p50_ms'], read_res['p95_ms'], read_res['p99_ms'])
    
    # Summary
    logging.info("\n=== SUMMARY ===")
    logging.info("WRITE: QPS=%.1f, P50=%.2fms, P95=%.2fms, P99=%.2fms", 
                 write_res['qps'], write_res['p50_ms'], write_res['p95_ms'], write_res['p99_ms'])
    logging.info("READ:  QPS=%.1f, P50=%.2fms, P95=%.2fms, P99=%.2fms",
                 read_res['qps'], read_res['p50_ms'], read_res['p95_ms'], read_res['p99_ms'])

if __name__ == "__main__":
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: sys.exit(0))
    main()
