# Baseline Architecture

## Overview

This document describes the baseline implementation of the IoT streaming
pipeline — the foundation on which all subsequent features are built. It
covers infrastructure setup, schema design, stream processing, and the
key engineering decisions and challenges encountered during construction.

---

## Data Flow

```text
100 IoT Sensors (Python + Faker)
        │   ~100 events/sec · JSON
        ▼
Apache Kafka (sensor-events topic)
        ▼
Spark Structured Streaming
   ├─ Raw events  → Cassandra.sensor_events      (CL=ONE,    SizeTiered)
   └─ Hourly aggs → Cassandra.hourly_aggregates  (CL=QUORUM, Leveled)
        ▼
3-Node Cassandra Cluster (RF=3, 16 vnodes/node)
```

---

## Infrastructure

### Memory Constraints

Running multiple JVM-based services concurrently requires explicit resource
budgeting. Without limits, initial testing caused an unbounded Cassandra JVM
heap allocation that consumed 31GB RAM and froze the system.

The solution was to apply hard `mem_limit` constraints in `docker-compose.yml`
and tune each JVM separately:

| Component | `mem_limit` | JVM Heap | Notes |
|---|---|---|---|
| Cassandra × 3 | 1.2 GB each | 512 MB | Off-heap: Bloom filters, buffers |
| Kafka | 1 GB | 512 MB max | Page cache in off-heap |
| Zookeeper | 512 MB | — | Lightweight coordination |
| Spark (host) | — | ~1.5 GB default | Driver + executors, not containerized |
| **Total Docker** | **~4.1 GB** | | |
| **Total system** | **~13–14 GB** | | 2–3 GB safety margin |

**Key principle**: Cassandra heap should be 25–50% of container RAM.
Excessive heap triggers GC pressure because Cassandra relies heavily on
off-heap memory for Bloom filters, compression buffers, and network I/O.

### Cluster Formation

All three Cassandra nodes join the same cluster (`IoT-Cluster`, datacenter
`dc1`) using `cassandra-1` as the seed node. Verification:

```bash
docker exec cassandra-1 nodetool status
```

Expected output — all nodes `UN` (Up/Normal), 16 tokens each, 100% ownership
per node (300% total reflects RF=3 full replication):

```
--  Address     Load       Tokens  Owns    Host ID    Rack
UN  172.18.0.6  75.5 KiB   16      100.0%  abc123...  rack1
UN  172.18.0.3  70.1 KiB   16      100.0%  def456...  rack1
UN  172.18.0.5  68.9 KiB   16      100.0%  ghi789...  rack1
```

---

## Cassandra Schema

### Keyspace

```sql
CREATE KEYSPACE IF NOT EXISTS iot_analytics
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};
```

`SimpleStrategy` is appropriate for a single-datacenter deployment.
RF=3 means every partition is stored on all three nodes, providing fault
tolerance: the cluster survives one node failure at `CL=QUORUM` (2 of 3
replicas remain available).

### Table 1: `sensor_events` — Write-Heavy

```sql
CREATE TABLE sensor_events (
    device_id UUID,
    timestamp BIGINT,
    temperature FLOAT,
    humidity FLOAT,
    location TEXT,
    PRIMARY KEY ((device_id), timestamp)
) WITH CLUSTERING ORDER BY (timestamp DESC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
};
```

- **Partition key** `device_id`: Murmur3 hash distributes data evenly across
  the token ring
- **Clustering key** `timestamp DESC`: Enables efficient "most recent events
  for a device" queries
- **SizeTieredCompactionStrategy**: Optimized for write throughput. Groups
  SSTables into size tiers and merges them when a tier accumulates 4+ files.
  Write amplification: 5–10×. Read amplification: 10–30 SSTables (acceptable
  since raw events are rarely queried directly)

### Table 2: `hourly_aggregates` — Read-Heavy

```sql
CREATE TABLE hourly_aggregates (
    device_id UUID,
    hour_bucket BIGINT,
    avg_temperature FLOAT,
    max_temperature FLOAT,
    min_temperature FLOAT,
    event_count INT,
    PRIMARY KEY ((device_id), hour_bucket)
) WITH CLUSTERING ORDER BY (hour_bucket DESC)
AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
};
```

- **Clustering key** `hour_bucket`: Unix epoch seconds truncated to the hour
  start, enabling efficient time-range queries per device
- **LeveledCompactionStrategy**: Organizes SSTables into non-overlapping
  levels (L0 → L1 → L2). Each level is 10× larger than the previous.
  Read amplification: 1–10 SSTables (predictable latency for dashboard
  queries). Write amplification: 10–30× (accepted trade-off)

### Table 3: `devices` — Reference Data

```sql
CREATE TABLE devices (
    device_id UUID PRIMARY KEY,
    device_name TEXT,
    location TEXT,
    created_at TIMESTAMP,
    last_updated TIMESTAMP
) WITH compaction = {
    'class': 'TimeWindowCompactionStrategy',
    'compaction_window_unit': 'DAYS',
    'compaction_window_size': 1
};
```

- **TimeWindowCompactionStrategy**: Groups SSTables into daily time buckets.
  Entire windows are dropped atomically when data expires via TTL, avoiding
  tombstone accumulation. Included to demonstrate all three major compaction
  strategies in one project.

### Compaction Strategy Decision Matrix

| Workload | Strategy | Write Amp | Read Amp |
|---|---|---|---|
| Write-heavy ingestion | **SizeTiered** | 5–10× ✅ | 10–30 SSTables ⚠️ |
| Read-heavy analytics | **Leveled** | 10–30× ⚠️ | 1–10 SSTables ✅ |
| Time-series + TTL | **TimeWindow** | 5–10× ✅ | 5–15 SSTables |

---

## Producer

The producer simulates 100 IoT devices using the `Faker` library, generating
temperature (15–35°C) and humidity (30–90%) readings distributed across 7
Italian cities. Each batch of 100 events is sent every second, targeting
~100 events/sec sustained throughput.

```python
producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    acks=1,
    compression_type='gzip',
    batch_size=16384,
    linger_ms=10
)
```

**Note on compression**: `snappy` was the initial choice but required a
native library not available in the Python environment. Switched to `gzip`
(Python built-in) with negligible performance impact at this throughput.

Each JSON message is approximately 200 bytes:

```json
{
  "device_id": "abc12345-...",
  "device_name": "Sensor-042",
  "timestamp": 1737211200000,
  "temperature": 23.45,
  "humidity": 67.89,
  "location": "Rome"
}
```

---

## Spark Consumer

### Dependency Management

Initial attempts to manually download JARs for the Kafka and Cassandra
connectors resulted in cascading `NoClassDefFoundError` failures due to
shaded dependency conflicts inside the Cassandra connector. The correct
approach is to delegate resolution entirely to Maven via `--packages`:

```bash
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,\
com.datastax.spark:spark-cassandra-connector_2.12:3.5.0 \
  --conf spark.cassandra.connection.host=localhost \
  --conf spark.cassandra.connection.port=9042 \
  spark_consumer.py
```

This automatically resolves and downloads 28 JARs (~60MB) with guaranteed
version compatibility. Manual JAR management should never be used for
connectors with shaded dependencies.

### Dual-Stream Architecture

The consumer runs two concurrent streams from the same `events_df` source:

**Stream 1 — Raw events → `sensor_events`**
- `CL=ONE`: Only 1 of 3 replicas needs to acknowledge the write
- Optimizes for write throughput; eventual consistency is acceptable for
  raw archival data
- Explicit `.select()` used to match Cassandra columns exactly — derived
  columns (`device_name`, `event_time`) are excluded

**Stream 2 — Hourly aggregates → `hourly_aggregates`**
- `CL=QUORUM`: 2 of 3 replicas must acknowledge
- 1-hour tumbling window with 1-minute watermark for late data tolerance
- `processingTime="10 seconds"` trigger keeps aggregate freshness reasonable
- `CL=QUORUM` ensures analytics reads are always consistent

### Consistency Levels

| | `sensor_events` | `hourly_aggregates` |
|---|---|---|
| **Write CL** | ONE | QUORUM |
| **Replicas required** | 1 of 3 | 2 of 3 |
| **Rationale** | Speed — raw ingestion | Correctness — analytics |
| **Fault tolerance** | Survives 2 node failures | Survives 1 node failure |

---

## Monitoring

The `monitoring/` directory contains three shell scripts for operational
visibility:

- **`monitor.sh`**: Full cluster dashboard — node status, token ownership,
  SSTable counts, read/write counters, row counts, pipeline process health
- **`compaction_monitor.sh`**: Live compaction tracking — active compactions,
  SSTable counts per table, compaction history, refreshes every 5 seconds
- **`cassandra_auto_flush.sh`**: Forces MemTable flushes to generate SSTables
  and trigger compactions, useful for demonstrating compaction behavior without
  waiting for organic data accumulation

> **Note**: Scripts set `LC_NUMERIC=C` to avoid decimal formatting issues on
> Italian locale systems where numbers use commas instead of dots
> (e.g. `12,345` vs `12345`), which broke `grep` numeric range patterns.

### Useful `nodetool` Commands

```bash
# Cluster health
docker exec cassandra-1 nodetool status

# Token ring distribution
docker exec cassandra-1 nodetool ring

# Thread pool stats (MutationStage, ReadStage, CompactionExecutor)
docker exec cassandra-1 nodetool tpstats

# Per-table metrics (SSTable count, space used, read/write counts)
docker exec cassandra-1 nodetool tablestats iot_analytics.sensor_events

# Active compactions
docker exec cassandra-1 nodetool compactionstats

# Compaction history
docker exec cassandra-1 nodetool compactionhistory
```

---

## Key Engineering Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Replication strategy | SimpleStrategy RF=3 | Single datacenter; full replication across all nodes |
| Dual-table design | `sensor_events` + `hourly_aggregates` | Separate write-optimized and read-optimized workloads |
| Consistency split | CL=ONE writes / CL=QUORUM reads | Balance ingestion throughput with analytics correctness |
| 16 vnodes per node | Reduced from default 256 | Smaller cluster; less gossip overhead |
| Spark `--packages` | Maven resolution | Avoids shaded dependency conflicts in connectors |
| `gzip` compression | Over `snappy` | No native library dependency; negligible difference at 100 events/sec |

---

## Observed Performance

After 5 minutes of continuous operation:

```
Producer rate         : ~105 events/sec
Total events ingested : 20,000
Spark batch size      : ~100 events / 10-second batch
SSTable count (sensor_events)      : 12
SSTable count (hourly_aggregates)  : 3
Cassandra data size                : ~2.5 MB total
Memory usage (Docker containers)   : ~4.3 GB / 8.5 GB allocated
Memory usage (total system)        : ~13 GB / 16 GB available
```

---

## Known Limitations Addressed by Later Features

| Limitation | Feature |
|---|---|
| No schema enforcement — producer can send malformed JSON silently | [Data Contracts](./data-contracts.md) |
| JSON is verbose (~200 bytes/message) | [Data Contracts](./data-contracts.md) |
| No contract between producer and consumer — schema drift risk | [Data Contracts](./data-contracts.md) |
| Dead `spark.jars` config block in `SparkSession` | Baseline fix (pre-data-contracts cleanup) |