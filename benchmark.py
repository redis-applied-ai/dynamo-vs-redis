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
DDB_TABLE = env("DDB_TABLE", required=True)
AWS_REGION = env("AWS_REGION", "us-east-1")

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
        elif task == "read":
            r.get(key)
        times.append(time.perf_counter() - start)
    
    return times

def redis_cleanup():
    """Redis cleanup - flush the entire database for efficiency"""
    r = redis.Redis(**REDIS_OPTS)
    start = time.perf_counter()
    r.flushdb()
    return time.perf_counter() - start

def dynamo_worker(work_batch):
    """DynamoDB worker that processes a batch of operations with a single connection"""
    task, work_items = work_batch
    
    # Establish connection once per process with retry logic
    ddb = boto3.client(
        "dynamodb",
        region_name=AWS_REGION,
        config=Config(
            retries={"max_attempts": 3, "mode": "adaptive"}, 
            max_pool_connections=50
        ),
    )
    times = []
    
    for key, vector in work_items:
        start = time.perf_counter()
        if task == "write":
            ddb.put_item(TableName=DDB_TABLE,
                         Item={"id": {"S": key}, "vec": {"B": vector}})
        elif task == "read":
            ddb.get_item(TableName=DDB_TABLE, Key={"id": {"S": key}})
        times.append(time.perf_counter() - start)
    
    return times

def dynamo_cleanup_batch(all_keys):
    """DynamoDB cleanup using batch_write_item - sequential like Redis FLUSHDB"""
    ddb = boto3.client(
        "dynamodb", 
        region_name=AWS_REGION,
        config=Config(
            retries={"max_attempts": 5, "mode": "adaptive"},
            max_pool_connections=10
        )
    )
    
    start_time = time.perf_counter()
    total_deleted = 0
    
    # Process in batches of 25 (DynamoDB batch_write_item limit)
    batch_size = 25
    for i in range(0, len(all_keys), batch_size):
        batch_keys = all_keys[i:i + batch_size]
        
        # Create delete requests
        delete_requests = [
            {"DeleteRequest": {"Key": {"id": {"S": key}}}}
            for key in batch_keys
        ]
        
        try:
            # Execute batch delete
            response = ddb.batch_write_item(
                RequestItems={DDB_TABLE: delete_requests}
            )
            
            # Handle unprocessed items
            unprocessed = response.get('UnprocessedItems', {})
            while unprocessed:
                time.sleep(0.1)  # Brief pause before retry
                response = ddb.batch_write_item(RequestItems=unprocessed)
                unprocessed = response.get('UnprocessedItems', {})
            
            total_deleted += len(batch_keys)
            
        except Exception as e:
            print(f"   ⚠️  Warning: Failed to delete batch starting at {batch_keys[0]}: {e}")
            continue
    
    elapsed = time.perf_counter() - start_time
    return elapsed, total_deleted

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
    
    # Pretty header
    service_name = "Redis Cloud" if cfg.db == "redis" else "Amazon DynamoDB"
    print("\n" + "="*60)
    print(f"🚀 VECTOR STORAGE BENCHMARK - {service_name.upper()}")
    print("="*60)
    print(f"📊 Configuration:")
    print(f"   • Service: {service_name}")
    print(f"   • Processes: {cfg.proc}")
    print(f"   • Operations: {cfg.ops:,}")
    print(f"   • Vector Dimension: {VECTOR_DIM}")
    print(f"   • Vector Size: {VEC_BYTES:,} bytes")
    print("-"*60)
    
    # Generate vectors and keys upfront
    print("⚙️  Generating vectors...")
    all_vectors = generate_vectors(cfg.ops)
    all_keys = [f"vec:{i}" for i in range(cfg.ops)]
    
    # Run write phase
    print(f"\n📝 WRITE PERFORMANCE TEST")
    print(f"   Testing {cfg.ops:,} write operations across {cfg.proc} processes...")
    write_res = run_phase(cfg.db, "write", cfg.proc, all_keys, all_vectors)
    
    print(f"\n   ✅ WRITE RESULTS:")
    print(f"      Throughput: {write_res['qps']:,.1f} QPS")
    print(f"      Latency P50: {write_res['p50_ms']:.2f} ms")
    print(f"      Latency P95: {write_res['p95_ms']:.2f} ms") 
    print(f"      Latency P99: {write_res['p99_ms']:.2f} ms")
    
    # Run read phase
    print(f"\n📖 READ PERFORMANCE TEST")
    print(f"   Testing {cfg.ops:,} read operations across {cfg.proc} processes...")
    read_res = run_phase(cfg.db, "read", cfg.proc, all_keys, None)
    
    print(f"\n   ✅ READ RESULTS:")
    print(f"      Throughput: {read_res['qps']:,.1f} QPS")
    print(f"      Latency P50: {read_res['p50_ms']:.2f} ms")
    print(f"      Latency P95: {read_res['p95_ms']:.2f} ms")
    print(f"      Latency P99: {read_res['p99_ms']:.2f} ms")
    
    # Enhanced summary
    print(f"\n" + "="*60)
    print(f"📈 FINAL RESULTS SUMMARY - {service_name.upper()}")
    print("="*60)
    
    print(f"\n🔸 WRITE OPERATIONS:")
    print(f"   Throughput: {write_res['qps']:>10,.1f} QPS")
    print(f"   P50 Latency: {write_res['p50_ms']:>8.2f} ms")
    print(f"   P95 Latency: {write_res['p95_ms']:>8.2f} ms")
    print(f"   P99 Latency: {write_res['p99_ms']:>8.2f} ms")
    
    print(f"\n🔸 READ OPERATIONS:")
    print(f"   Throughput: {read_res['qps']:>10,.1f} QPS")
    print(f"   P50 Latency: {read_res['p50_ms']:>8.2f} ms")
    print(f"   P95 Latency: {read_res['p95_ms']:>8.2f} ms")
    print(f"   P99 Latency: {read_res['p99_ms']:>8.2f} ms")
    
    print("\n" + "="*60)
    print("✨ Benchmark completed successfully!")
    print("="*60 + "\n")

    # Cleanup phase
    print(f"\n🧹 CLEANUP PHASE")
    print(f"   Removing {cfg.ops:,} keys to ensure clean slate...")
    
    if cfg.db == "redis":
        # Use fast FLUSHDB for Redis
        cleanup_time = redis_cleanup()
        print(f"   ✅ Redis cleanup completed")
    else:
        # Use efficient batch deletion for DynamoDB
        cleanup_time, deleted_count = dynamo_cleanup_batch(all_keys)
        print(f"   ✅ DynamoDB cleanup completed")

if __name__ == "__main__":
    # Removed problematic signal handlers that interfere with multiprocessing
    main()
