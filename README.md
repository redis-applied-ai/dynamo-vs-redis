# Redis vs DynamoDB Benchmarking

A performance comparison tool for Redis and DynamoDB, designed to benchmark read and write operations to help you choose the right database for your use case.

## What We're Benchmarking

This project compares:
- **Redis** - In-memory data structure store
- **DynamoDB** - AWS managed NoSQL database

**Benchmark Operations:**
- ✅ **Write Performance** - Insert operations throughput and latency
- ✅ **Read Performance** - Query operations throughput and latency

## Setup

### 1. System Dependencies on AWS EC2 Instance (Run Once)

```bash
# Update system and install essential tools
sudo dnf update -y
sudo dnf install -y git curl wget

# Install build tools and Python development dependencies  
sudo dnf install -y gcc gcc-c++ make libffi-devel openssl-devel python3-pip

# Verify Python 3 is available
python3 --version
```

### 2. Python Environment Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd dynamo-vs-redis

# Upgrade pip
python3 -m pip install --upgrade pip --user

# Install pipx (Python package installer)
python3 -m pip install --upgrade pipx --user

# Ensure ~/.local/bin is on PATH
export PATH="$HOME/.local/bin:$PATH"
pipx ensurepath

# Install uv (fast Python package manager)
pipx install uv

# Create virtual environment and install dependencies
uv sync
```

### 3. Run Benchmarks

```bash
# Basic Redis benchmark (runs both write and read tests)
uv run python benchmark.py --db redis

# Basic DynamoDB benchmark (runs both write and read tests)
uv run python benchmark.py --db dynamo

# Advanced usage with custom settings
uv run python benchmark.py --db redis --proc 4 --ops 1000
uv run python benchmark.py --db dynamo --proc 16 --ops 5000
```

## Requirements

- **AWS EC2 instance** (Amazon Linux 2023 recommended)
- **Python 3.11+**
- **Redis server** (for Redis benchmarks)
- **AWS credentials** configured (for DynamoDB benchmarks)

### Environment Variables

**For Redis:**
- `REDIS_HOST` - Redis server hostname (required)
- `REDIS_PASSWORD` - Redis password (required)  
- `REDIS_PORT` - Redis port (default: 6379)

**For DynamoDB:**
- `DDB_TABLE` - DynamoDB table name (required)
- `AWS_REGION` - AWS region (default: us-east-1)

## Project Structure

```
dynamo-vs-redis/
├── benchmark.py      # Main benchmark script
├── pyproject.toml   # Python dependencies
└── README.md        # This file
```

## Configuration

The benchmark script accepts these command-line arguments:

- `--db {redis,dynamo}` - Database to benchmark (required)
- `--proc N` - Number of parallel processes (default: 8)
- `--ops N` - Total number of operations per test (default: 2000)

**Note:** Each benchmark run executes both write and read tests automatically, providing comprehensive performance metrics including QPS, P50, P95, and P99 latencies. 