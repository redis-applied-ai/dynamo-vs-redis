# Redis vs DynamoDB Benchmarking

A performance comparison tool for Redis and DynamoDB, designed to benchmark read and write operations to help you choose the right database for your use case.

## What We're Benchmarking

This project compares:
- **Redis** - In-memory data structure store
- **DynamoDB** - AWS managed NoSQL database

**Benchmark Operations:**
- ✅ **Write Performance** - Insert operations throughput and latency
- ✅ **Read Performance** - Query operations throughput and latency

## Quick Start

### 1. Setup Environment (AWS EC2)

```bash
# Clone the repo and run setup
git clone <your-repo-url>
cd dynamo-vs-redis
chmod +x setup.sh
./setup.sh
```

The setup script will:
- Install system dependencies
- Install UV (Python package manager)
- Create virtual environment and install Python dependencies

### 2. Run Benchmarks

```bash
# Redis benchmarks
uv run python benchmark.py --db redis --task write
uv run python benchmark.py --db redis --task read

# DynamoDB benchmarks  
uv run python benchmark.py --db dynamo --task write
uv run python benchmark.py --db dynamo --task read
```

## Requirements

- **AWS EC2 instance** (Amazon Linux 2023 recommended)
- **Python 3.11+**
- **Redis server** (for Redis benchmarks)
- **AWS credentials** configured (for DynamoDB benchmarks)

## Project Structure

```
dynamo-vs-redis/
├── benchmark.py      # Main benchmark script
├── setup.sh         # Environment setup for EC2
├── pyproject.toml   # Python dependencies
└── README.md        # This file
```

## Configuration

The benchmark script accepts command-line arguments to configure:
- Database type (`--db redis` or `--db dynamo`)
- Operation type (`--task read` or `--task write`)

Results will show throughput, latency, and other performance metrics to help you make informed database choices. 