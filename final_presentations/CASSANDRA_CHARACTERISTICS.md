# Cassandra Characteristics Quick Reference
## For Your 10-15 Minute Exam Presentation

---

## 🎯 The 6 Main Characteristics to Discuss

### 1️⃣ MASTERLESS P2P ARCHITECTURE
**What**: Any node can be coordinator; no single master  
**How**: Gossip protocol - nodes exchange state every 1 second  
**Why for Big Data**: 
- ✓ No single point of failure (SPOF)
- ✓ Linear scalability: add node → +capacity
- ✗ Trade-off: Complex consistency management

**Demo Code**:
```bash
docker exec cassandra-1 nodetool status
# Output shows: UN (Up/Normal) for all nodes
# No "Master" marker - all equal!
```

---

### 2️⃣ CAP THEOREM: Cassandra chooses A + P
**What**: You can only have 2 of 3:
- C = Consistency (all replicas agree)
- A = Availability (always respond)
- P = Partition Tolerance (survive network failures)

**Cassandra's Choice**: A + P (Eventual Consistency)

**Why**:
- Network partitions ALWAYS happen
- Choosing C requires coordination → latency
- For Big Data velocity: availability wins

**Visual**:
```
Traditional SQL:  C + A (single node)
Cassandra:       A + P (distributed)

In a partition:
SQL:        "Can't respond" (chooses C over A)
Cassandra:  "Responds with best-guess" (chooses A over C)
           Syncs later (repairs)
```

---

### 3️⃣ TUNABLE CONSISTENCY LEVELS
**What**: Choose consistency level per operation

**Three Levels**:
| Level | Write | Read | Speed | Consistency |
|-------|-------|------|-------|-------------|
| ONE | 1 replica | 1 replica | ⚡⚡⚡ Fast | ⚠️ May be stale |
| QUORUM | ⌈n/2⌉ | ⌈n/2⌉ | ⚡ Balanced | ✓ Correct |
| ALL | all | all | Slow | ✓✓ Guaranteed |

**Strategy for this project**: 
- Write at ONE (fast ingestion for sensors)
- Read at QUORUM (verify correctness for queries)

**Demo Code**:
```sql
-- Fast writes (accept temporary inconsistency)
CONSISTENCY ONE;
INSERT INTO sensor_events (...) VALUES (...);

-- Verified reads (wait for 2/3 replicas)
CONSISTENCY QUORUM;
SELECT * FROM sensor_events WHERE device_id = ? LIMIT 1;

-- Safe but slow (wait for all replicas)
CONSISTENCY ALL;
SELECT COUNT(*) FROM sensor_events;
```

**Key Insight**: This flexibility is unique to Cassandra!

---

### 4️⃣ EVENTUAL CONSISTENCY & BACKGROUND REPAIR
**What**: Temporary inconsistency is OK; system self-heals

**How It Works**:
```
Time 0: All replicas have v=10
        ┌─────┬─────┬─────┐
        │  10 │  10 │  10 │
        └─────┴─────┴─────┘

Time 1: Write CL=ONE (only 1 replica gets update)
        ┌─────┬─────┬─────┐
        │  20 │  10 │  10 │  ← Inconsistent!
        └─────┴─────┴─────┘

Time 2: Read CL=QUORUM (2 replicas confirm v=20)
        Newer value wins
        Background repair: update other replicas

Time 3: All replicas synced to v=20
        ┌─────┬─────┬─────┐
        │  20 │  20 │  20 │  ← Consistent again!
        └─────┴─────┴─────┘
```

**This is "Eventual Consistency"**: System reaches consistency eventually

**Repair Mechanisms**:
- **Read Repair**: On read, fix stale replicas
- **Hinted Handoff**: Temporary data holder passes data to proper node
- **Anti-Entropy Repair**: Periodic full sync (background)

**For Big Data**: Speed to write >> occasional inconsistency

---

### 5️⃣ DISTRIBUTED HASH RING & SCALING
**What**: Data distributed via consistent hashing on ring

**How**:
```
partition_key → hash_function → token (0 to 2^127)
                                ↓
                        Token range on ring
                                ↓
                    Which node stores this partition?
```

**Visualization**:
```
              Node A (tokens 0-100)
          ┌─────────────────────┐
      ┌───┤                     ├───┐
  ┌───┤   │    Gossip Protocol  │   ├───┐
  │   │   │    (No ZooKeeper!)  │   │   │
  │   └───┤                     ├───┘   │
  │       └─────────────────────┘       │
  │                                     │
  │  Node C         Node B              │
  │ (200-300)     (100-200)             │
  └─────────────────────────────────────┘

Virtual Nodes (vnodes): Each physical node = 16 tokens
Benefits:
- Automatic load balancing
- Smooth scaling (new node takes ~1/4 of load from each node)
- No resharding!
```

**Demo**: `nodetool ring` shows token distribution

---

### 6️⃣ COMPACTION STRATEGIES (Performance Tuning)
**What**: Different disk-optimization strategies for different workloads

**The Three Strategies**:

**A. SizeTiered (sensor_events table)**
- How: Groups similar-sized SSTables, merges 4+ together
- Write Speed: ⚡⚡⚡ Ultra-fast
- Read Speed: ⚡ Many files to scan
- Best For: Write-heavy (logs, time-series)
- Write Amplification: 5-10x

**B. Leveled (hourly_aggregates table)**
- How: Maintains non-overlapping levels (L0, L1, L2...)
- Write Speed: ⚡ Frequent compaction
- Read Speed: ⚡⚡⚡ Few files to scan
- Best For: Read-heavy (analytics queries)
- Read Amplification: 1-10 SSTables

**C. TimeWindow (for TTL-based data)**
- How: Compaction based on time windows
- Write Speed: ⚡ Fast
- Read Speed: ⚡ Balanced
- Best For: Events with TTL expiry
- Use: Logs that auto-delete after 30 days

**Key Insight**: No "best" strategy - match to workload!

**Demo Code**:
```bash
docker exec cassandra-1 nodetool compactionstats
docker exec cassandra-1 nodetool compactionhistory

# Shows which strategy is running on each table
DESCRIBE TABLE sensor_events;      -- SizeTiered
DESCRIBE TABLE hourly_aggregates;  -- Leveled
```

---

## 🌍 How These Tackle Big Data Challenges

| Big Data Challenge | Cassandra Feature | Connection |
|------------------|-------------------|-----------|
| **Volume** | Scale-out + hash ring | Add nodes, data redistributes |
| **Velocity** | Write-optimized (append-only) | 100K+ events/sec |
| **Variety** | Schemaless/column-family | Dynamic columns, sparse storage |
| **Veracity** | Tunable consistency + repair | Read at QUORUM, fix stale replicas |

---

## 📊 Numbers to Remember

| Metric | Value | Why It Matters |
|--------|-------|---|
| Events per second | 100 | Velocity challenge |
| Devices | 100 | Volume growth |
| Replication Factor | 3 | Survives 1 node failure |
| Consistency Levels | ONE, QUORUM, ALL | Flexibility for different scenarios |
| Virtual Nodes | 16 per node | Load balancing |
| Typical Throughput | 100K+/sec per node | Linear scaling |
| Read Latency (CL=ONE) | 100+ μs | Ultra-fast |
| Read Latency (CL=QUORUM) | 1-2 ms | Balanced |

---

## 🎤 How to Explain Each Characteristic

### For Masterless Architecture:
*"Unlike traditional databases with a single master, Cassandra is peer-to-peer. Any node can coordinate requests. Nodes gossip with each other (exchange state every second) so they all know the cluster state. This means no single point of failure and true linear scalability."*

### For CAP Theorem:
*"In a distributed system, you can have at most 2 of 3 properties: Consistency, Availability, Partition tolerance. Network partitions happen, so we can't drop P. We choose A+P, meaning Cassandra prioritizes availability. We accept temporary inconsistency but repair automatically in the background."*

### For Tunable Consistency:
*"This is Cassandra's secret sauce. You choose consistency level per operation. Writes use CL=ONE (100μs, fast) because we're ingesting sensor data. Reads use CL=QUORUM (1-2ms, accurate) because we need correct values for analytics. This flexibility is why Cassandra dominates at scale."*

### For Eventual Consistency:
*"If we write with CL=ONE, only 1 of 3 replicas gets the update initially. The system is temporarily inconsistent. But when we read with CL=QUORUM, we contact 2 replicas and return the newer value. Background repair ensures all replicas sync. This is 'eventual consistency' - the system self-heals."*

### For Hash Ring:
*"Each data partition gets a token via hashing. This token maps to a position on the ring. RF=3 means the next 3 nodes clockwise store the data. When we add a new node, it takes some tokens, redistributing data automatically. No manual resharding - that's massive for Big Data."*

### For Compaction:
*"Cassandra appends writes (no read-before-write). But this creates many files. Compaction merges files. Different strategies optimize for different workloads: SizeTiered for writes, Leveled for reads. You choose based on whether your table is write-heavy or read-heavy."*

---

## ⚡ Quick Demo Commands

```bash
# Show cluster health
docker exec cassandra-1 nodetool status

# Show token ring
docker exec cassandra-1 nodetool ring

# Test consistency levels
docker exec cassandra-1 cqlsh -e "CONSISTENCY ONE; USE iot_analytics; SELECT COUNT(*) FROM sensor_events;"
docker exec cassandra-1 cqlsh -e "CONSISTENCY QUORUM; USE iot_analytics; SELECT COUNT(*) FROM sensor_events;"

# Monitor compaction
docker exec cassandra-1 nodetool compactionstats

# View table schemas
docker exec cassandra-1 cqlsh -e "USE iot_analytics; DESCRIBE TABLE sensor_events;"
docker exec cassandra-1 cqlsh -e "USE iot_analytics; DESCRIBE TABLE hourly_aggregates;"

# Sample data
docker exec cassandra-1 cqlsh -e "USE iot_analytics; SELECT * FROM sensor_events LIMIT 5;"
```

---

## 🎯 Exam Tip

Focus on these 3 things in Part 3 (Cassandra Deep Dive):

1. **Why is it different from SQL?** (Masterless, tunable consistency)
2. **How does it handle Big Data?** (Scale-out, write-optimized)
3. **What are the trade-offs?** (No ACID, eventual consistency, no joins)

The examiners want to see you understand the *why*, not just the *what*.

---

## 💾 Data to Show

After running your pipeline for 5 minutes:

| Table | Expected Rows | Why |
|-------|---|---|
| sensor_events | ~30,000 | 100 events/sec × 300 sec |
| hourly_aggregates | ~100 | 100 devices, ~1 hour window |
| Total data size | ~2-3 MB | Small demo, but concept scales to petabytes |

These numbers prove your system works!

---

Good luck! Remember: **Understand the why, not just the what.** 🚀