# Real-Time IoT Analytics with Apache Cassandra

A production-like **real-time IoT pipeline** that ingests sensor data via **Kafka**, processes it with **Spark Streaming**, and stores it in a **3-node Apache Cassandra cluster** to showcase Cassandra’s **distributed architecture, tunable consistency, and compaction strategies**.

> Built as a university project to demonstrate **Cassandra internals** rather than just using it as a generic NoSQL store.

---

## Architecture

```text
100 IoT Sensors (Python Faker)
        │   100 events/sec (JSON)
        ▼
Apache Kafka (sensor-events topic)
        ▼
Spark Structured Streaming
   ├─ Raw events  → Cassandra.sensor_events   (CL=ONE, SizeTiered)
   └─ Hourly aggs → Cassandra.hourly_aggregates (CL=QUORUM, Leveled)
        ▼
3-Node Cassandra Cluster (RF=3, vnodes)
```

**Key ideas:**

- **Streaming ingestion**: ~100 events/sec from 100 virtual devices
- **Dual-table design**:
  - `sensor_events` → write-optimized (SizeTiered)
  - `hourly_aggregates` → read-optimized (Leveled)
- **Cassandra as the focus**: consistency levels, token ring, vnodes, compaction behavior

---

## Project Goals

- Demonstrate **Cassandra’s flagship features** in a realistic setting:
  - Distributed hash ring & **virtual nodes**
  - **Tunable consistency** (ONE, QUORUM, ALL)
  - **Write path**: CommitLog → MemTable → SSTable
  - **Compaction strategies**: SizeTiered, Leveled, TimeWindow
- Show end-to-end **real-time data flow** with:
  - Kafka as the streaming backbone
  - Spark for processing and aggregation
  - Cassandra as the primary data store

---

## Tech Stack

- **Languages**: Python 3.10, CQL
- **Streaming**: Apache Kafka (Confluent images)
- **Processing**: Apache Spark 3.5 (Structured Streaming)
- **Database**: Apache Cassandra 4.1 (3 nodes, RF=3)
- **Orchestration**: Docker & docker-compose
- **Monitoring**: `nodetool`, custom shell scripts

---

## Repository Structure

```text
.
├── docker-compose.yml          # Kafka, Zookeeper, Cassandra cluster
├── cassandra/
│   └── init.cql                # Keyspace + 3 tables (STCS, LCS, TWCS)
├── src/
│   ├── producer.py             # IoT device simulator → Kafka
│   └── spark_consumer.py       # Kafka → Spark → Cassandra
├── monitoring/
│   ├── monitor.sh              # Cluster + table stats dashboard
│   ├── cassandra_auto_flush.sh # Force flush to trigger compaction
│   └── compaction_monitor.sh   # Live compaction monitoring
├── report.md                   # Technical report (Cassandra focus)
└── README.md                   # This file
```

---

## Prerequisites

### **Hardware**:

**Hardware**:
- **16 GB RAM** (Docker + Spark + OS)
  - The pipeline is **RAM-hungry** because it runs multiple JVM-based services (Cassandra, Kafka, Spark) that require significant heap + off-heap memory for production-like workloads.
  - Given these memory requirements, I applied some memory constraints in the `docker-compose.yml` file.
#### **Memory Breakdown & Constraints**

| Component | **Allocated Limit** | **Actual Usage** | **Heap Size** | **Notes** |
|-----------|---------------------|------------------|---------------|-----------|
| **Cassandra (3 nodes)** | **2 GB each** (`mem_limit: 2g`) | **1.0-1.2 GB each** | **768 MB** (`MAX_HEAP_SIZE`) | Off-heap (Bloom filters, buffers): ~400 MB. **Initial problem**: Unconstrained heap → 31 GB spike!  |
| **Kafka** | **2 GB** (`mem_limit: 2g`) | **~850 MB** | **1 GB max** (`KAFKA_HEAP_OPTS`) | Page cache + network buffers |
| **Zookeeper** | **512 MB** (`mem_limit: 512m`) | **~280 MB** | N/A | Kafka coordination |
| **Total Docker** | **8.5 GB** | **6-8 GB** | - | Conservative limits prevent OOM kills |
| **Spark Streaming** | **No Docker limit** (host process) | **2-3 GB** | **Default** (~1.5 GB) | PySpark driver + executors. Peak during micro-batch processing |
| **Producer (Python)** | Host process | **~200 MB** | N/A | Minimal |
| **OS + Apps** | - | **2-3 GB** | N/A | Kubuntu 22.04 + desktop |
| **TOTAL SYSTEM** | **16 GB** | **13-14 GB** | - | **2-3 GB safety margin** (no swap thrashing) |

## **Why So Much RAM?**

1. **Cassandra** (biggest consumer):
   - **Heap (768 MB)**: MemTables, caches
   - **Off-heap (~400 MB)**: Bloom filters, compression buffers, index summaries
   - **Per node**: 2 GB limit → **6 GB total** for 3-node cluster

2. **Initial Problem**: No `mem_limit` → **31 GB spike** (system freeze). 
   - **Solution**: Docker limits + JVM tuning (`MAX_HEAP_SIZE`)

3. **Spark** adds **2-3 GB** during streaming (checkpoints, shuffle buffers)

4. **Replication Factor 3**: Data stored 3x → more memory for caches/indexes

## **How Constraints Were Applied**

```yaml
# docker-compose.yml excerpts
cassandra-1:
  mem_limit: 2g                    # Hard Docker ceiling
  environment:
    MAX_HEAP_SIZE: 768M           # JVM heap cap (38% of container)
    HEAP_NEWSIZE: 200M            # Young gen for short-lived objects

kafka:
  mem_limit: 2g
  environment:
    KAFKA_HEAP_OPTS: "-Xmx1G -Xms512M"  # Heap 1 GB max
```

**Result**: Stable **13-14 GB usage** with **2-3 GB free** → reliable for demos.

**Recommendation**: **16 GB minimum**, **24 GB optimal** for smooth operation.

**Software**:
- Docker 24.x
- docker-compose 1.29.x
- Python 3.10+
- Java 17+
- Apache Spark 3.5.x installed locally

Full list of requirements can be found in the file `requirements.txt`.

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Pippinu/iot-cassandra-pipeline.git
cd iot-cassandra-pipeline
```

### 2. Start the infrastructure (Kafka + Cassandra)

```bash
docker-compose up -d
# Wait ~2–3 minutes for Cassandra cluster to form
docker exec cassandra-1 nodetool status
```

You should see **3 nodes** with status `UN` (Up/Normal) and RF=3 for keyspace `iot_analytics`.

### 3. Create keyspace and tables

```bash
docker cp cassandra/init.cql cassandra-1:/init.cql
docker exec cassandra-1 cqlsh -f /init.cql
```

### 4. Start the IoT producer (Kafka)

```bash
cd src
python3 producer.py
# Generates ~100 events/sec into topic "sensor-events"
```

### 5. Start Spark Streaming (Kafka → Cassandra)

In another terminal:

```bash
cd src
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,com.datastax.spark:spark-cassandra-connector_2.12:3.5.0 \
  --conf spark.cassandra.connection.host=localhost \
  --conf spark.cassandra.connection.port=9042 \
  spark_consumer.py
```

This will:

- Read from Kafka topic `sensor-events`
- Write raw events to `iot_analytics.sensor_events` (CL=ONE, SizeTiered)
- Compute hourly aggregates into `iot_analytics.hourly_aggregates` (CL=QUORUM, Leveled)

---

## Cassandra Features Demonstrated

### 1. Distributed Hash Ring & Virtual Nodes

- 3-node cluster, **RF=3**, **16 vnodes** per node
- Data distributed using Murmur3 hash over token ring
- Commands:

```bash
docker exec cassandra-1 nodetool status
docker exec cassandra-1 nodetool ring
```

### 2. Tunable Consistency Levels

- Raw writes: `CONSISTENCY ONE` (through Spark)
- Analytics reads: `CONSISTENCY QUORUM`

Example (inside `cqlsh`):

```sql
CONSISTENCY ONE;
SELECT COUNT(*) FROM iot_analytics.sensor_events;

CONSISTENCY QUORUM;
SELECT COUNT(*) FROM iot_analytics.hourly_aggregates;
```

### 3. Write Path (CommitLog → MemTable → SSTable)

- High write throughput using append-only design
- Visible via `tpstats` and SSTable counts:

```bash
docker exec cassandra-1 nodetool tpstats
docker exec cassandra-1 nodetool tablestats iot_analytics.sensor_events | grep "SSTable count"
```

### 4. Compaction Strategies

Tables:

- `sensor_events` → **SizeTieredCompactionStrategy (STCS)**  
- `hourly_aggregates` → **LeveledCompactionStrategy (LCS)**  
- `devices` → **TimeWindowCompactionStrategy (TWCS)**

You can observe compaction activity with:

```bash
cd monitoring
./cassandra_auto_flush.sh         # Force flushes to generate SSTables
./compaction_monitor.sh           # Watch compactions in real time
```

---

## Quick Validation

Check that data is flowing end-to-end:

```bash
# Raw events count
docker exec cassandra-1 cqlsh -e "USE iot_analytics; SELECT COUNT(*) FROM sensor_events;"

# Aggregates count
docker exec cassandra-1 cqlsh -e "USE iot_analytics; SELECT COUNT(*) FROM hourly_aggregates;"

# Sample rows
docker exec cassandra-1 cqlsh -e "USE iot_analytics; SELECT * FROM sensor_events LIMIT 5;"
docker exec cassandra-1 cqlsh -e "USE iot_analytics; SELECT * FROM hourly_aggregates LIMIT 5;"
```

---

## Monitoring & Demo Scripts

From `monitoring/`:

```bash
./monitor.sh
```

Shows:

- Cluster status (UN/DN)
- Token ownership per node
- SSTable counts & space usage
- Read/write counts per table
- Row counts in main tables

For a live compaction demo:

```bash
./cassandra_auto_flush.sh     # Keep running for a few minutes
./compaction_monitor.sh       # Watch compaction history + active tasks
```

These scripts are designed for a **15-minute live presentation** to visually show:

- How data accumulates in SSTables
- When and how compactions occur
- That the cluster stays healthy under load

---

## License

MIT License – feel free to use this project as a reference for learning Cassandra, Kafka, or Spark Streaming, or as a starting point for your own experiments. 
