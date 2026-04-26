# What is Apache Cassandra?

**Apache Cassandra** is a **decentralized, distributed NoSQL wide-column store** designed for **high write throughput, linear scalability, and always-on availability** across commodity hardware or cloud. It combines **Amazon Dynamo**'s distributed hash ring with **Google BigTable**'s LSM-tree storage engine, optimized for time-series, logs, and IoT data at planetary scale.

**Key characteristics**:
```
✅ Peer-to-peer (no masters)
✅ Tunable consistency (ONE → ALL)
✅ Multi-DC replication
✅ Millions writes/sec, 100s PB data
✅ Used by: Netflix, Apple, Uber, Discord
```

## Original Paper (2009): Facebook's Inbox Search Engine

**Authors**: Avinash Lakshman & Prashant Malik (Facebook)
**Problem**: Facebook's **Inbox Search** needed **billions writes/day** across 250M users with <100ms latency—no RDBMS could scale.

**Paper Cassandra (2008 internal → 2009 open-sourced)**:
```
Core innovations:
├── Dynamo ring + tunable consistency (RF=3, QUORUM writes)
├── BigTable LSM: commitlog → memtable → SSTables (256K indexes)
├── Gossip (Scuttlebutt) for membership
├── Single table per cluster (Inbox = one wide row)
├── Thrift RPC, no SQL (CLI queries)
├── Manual token balancing (nodetool move)
├── Rack-unaware replication only
├── Facebook-only (no security, auth)
```

**Limitations** (paper era):
```
❌ No CQL (Thrift RPC hell)
❌ Uneven ring distribution
❌ No multi-DC
❌ Production ops painful
❌ Facebook abandoned for HBase (2010)
```

## Modern Cassandra (2026): Apache Top-Level Project

**Evolution** (2009 → now, 250+ contributors, 6k+ JIRAs):

| **Era** | **Key Milestone** | **Big Changes** |
|---------|------------------|-----------------|
| **2009** | Apache Incubator | Facebook → open source |
| **2010** | Top-level project | Rackspace (Jonathan Ellis) leads |
| **2011-12** | CQL 1.0-2.0 | SQL-like queries, drivers |
| **2012** | VNodes (1.2) | Auto-balancing rings |
| **2015** | 3.0 | NetworkTopologyStrategy, security |
| **2020** | 4.0 | SAI indexes, materialized views |
| **2024** | 5.0 | Java 17, vector search, CQL enhancements |

### Key Transformations

**1. From Thrift → CQL**:
```
Paper: curl -d 'ThriftBinary' localhost:9160
Modern: SELECT * FROM sensors WHERE id = ?  # SQL-like
```

**2. Manual → Auto-balancing**:
```
Paper: nodetool move 123456789 (manual ops hell)
Modern: num_tokens: 256 → auto even distribution
```

**3. Single-DC → Global**:
```
Paper: SimpleStrategy (one cluster)
Modern: {'dc1':3, 'dc2':2, 'dc3':1} → Netflix global
```

**4. Write-only → Full-featured**:
```
Paper: Inbox logs (high writes)
Modern: IoT + analytics + ML vectors
```

**5. Facebook toy → Enterprise**:
```
Paper: Internal Facebook only
Modern: Netflix (2k nodes), Apple (75k nodes), Discord
```

### Technical Maturity
```
✅ CQL3+ (full SQL subset)
✅ Materialized views (auto-denormalization)
✅ SAI (secondary indexes)
✅ Change Data Capture (CDC)
✅ Vector search (Cassandra 5.0)
✅ Java 17, GraalVM support
```

## Your Project Context
```
Paper Cassandra: Raw sensor writes → ONE consistency
Modern Cassandra: 
├── Raw stream (sensors.readings) → Kafka→Cassandra
├── Aggregates (hourly_stats) → Spark→Cassandra QUORUM  
├── Dashboard queries → CQL materialized views
├── Global replication → EU/US DCs
```

**Bottom line**: **2009 research prototype → 2026 production powerhouse** powering Netflix recommendations, Apple iMessage, and your IoT pipeline. Same core ring+LSM DNA, vastly improved ops and features.

## 1. Distributed, Masterless Architecture + Hash Ring

Cassandra's **peer-to-peer ring architecture** eliminates single points of failure by making every node equal—no masters, no leaders, no coordinators that can become bottlenecks.

### Masterless Architecture

**Traditional databases**: One primary/master node handles reads/writes, replicas are read-only or failovers.
```
Master → Replicas (read-only)
  ↓ crash = cluster outage
```

**Cassandra peer-to-peer**:
```
Client → ANY Node (coordinator)
  ↓ ALL nodes equal
NodeA ↔ NodeB ↔ NodeC (all read/write)
```

**Key implications**:
- **No leader election** = instant failover (milliseconds)
- **Any node can service** any read/write
- **No write bottleneck** (master can't overload)
- **Symmetric roles** = easier operations

### Consistent Hash Ring (Data Distribution)

**Problem**: How to partition data across N nodes without hotspots?

**Solution**: Virtual ring where **partition keys → tokens → node ownership**.

```
Ring (2^127 positions):
0 ---------------- 2^127
| NodeA(10) |NodeB(50)|NodeC(200)
  ↑owns 0-10 ↑owns10-50↑owns50-200
```

**How it works**:
```
1. partition_key → hash(MD3/Murmur3) → token (160-bit number)
2. Find FIRST node clockwise from token
3. That node = primary replica owner

user_id="alice123" → hash() → token=42 → NodeB owns
```

### Visual Demo (nodetool ring)
```bash
nodetool ring keyspace
Address         DC       Rack   Status State   Load           Owns                Token
c1              dc1      rack1  Up     Normal  1.23 GB        33.33%              -9223372036854775808
c2              dc1      rack1  Up     Normal  1.21 GB        33.33%              0
c3              dc1      rack1  Up     Normal  1.25 GB        33.34%              6148914691236517205
```

### Replication on Ring
```
Key "alice" → token 42 → NodeB (primary)
RF=3 → NodeB + next 2 clockwise = NodeB, NodeC, NodeA
```

```
Write "alice":
NodeB (coord): writes locally → forwards to NodeC, NodeA
All 3 replicas confirm → client ACK
```

### Scaling Benefits
```
Add NodeD (token 100):
• NodeB shrinks (10-100 → 10-50-100)
• NodeD takes 100-200 from NodeC
• ~1/N data movement (not full reshuffle)
```

### Your IoT Demo Context
```
sensor_001 → token 42 → NodeB + NodeC + NodeA replicas
sensor_002 → token 150 → NodeD + NodeB + NodeC replicas

Kafka partition → Cassandra partition_key → automatic sharding
Spark aggregates hit different nodes naturally
```

### Production Reality Check
```
✅ No master = 99.99% uptime possible
✅ Client drivers auto-discover topology
❌ Hot partitions still overload nodes (hash("trending_sensor") → NodeB)
✅ VNodes (256 tokens/node) → even distribution
```

**Demo sequence** (3 minutes):
1. `nodetool ring` → show token ownership
2. Insert 3 keys → `nodetool getEndpoints` → show replicas  
3. Kill NodeB → writes to NodeC → cluster continues
4. Restart NodeB → hinted handoff repairs automatically

**Bottom line**: **Every node equal + automatic data distribution = elastic, fault-tolerant writes at planetary scale.**

## 2. Horizontal Scalability & Elasticity

Cassandra **scales linearly** by adding commodity nodes—reads and writes both scale proportionally without application changes or downtime.

### How It Scales

**Traditional vertical scaling**:
```
1 beefy server → $50k → 100k ops/sec
2 beefy servers → $100k → ? (complex replication)
```

**Cassandra horizontal**:
```
1 node → 10k writes/sec
10 nodes → 100k writes/sec
100 nodes → 1M writes/sec
```

**Mechanism**: Ring automatically redistributes data as nodes join/leave.

### Online Elastic Scaling (Zero Downtime)

```
Production cluster (10 nodes):
1. Add node11 → auto-picks tokens → streams ~10% data from neighbors
2. Clients continue writing → new node immediately serves traffic
3. Remove node5 → neighbors take ownership → data streamed away
```

**Demo** (nodetool status before/after):
```bash
# Before: 3 nodes, 33% each
nodetool status

# Add node4
docker-compose up -d cassandra-4

# After: 4 nodes, 25% each (streaming in progress)
nodetool status
# State: "Joining" → "Normal"
```

### Capacity Planning Math
```
Target: 1TB data, 100k writes/sec
RF=3 → 3TB total storage

Per node:
Storage: 3TB ÷ 10 nodes = 300GB/node
Throughput: 100k ÷ 10 = 10k writes/sec/node
```

### Your IoT Project Scaling Demo
```
Day 1: 100 sensors → 3 nodes OK
Day 2: 10,000 sensors → node overload
Day 3: Add 3 nodes → capacity doubles

Spark job auto-discovers new nodes via topology awareness
```

### Read + Write Scaling (Independent)
```
Writes scale by data ownership (ring tokens)
Reads scale by ANY node (coordinator + replicas)
```
```
High writes → add nodes for data partitioning
High reads → add replicas (RF=5) or replicas nodes
```

### Real-World Numbers
```
Netflix: 2,000 nodes → 1.5PB data → millions ops/sec
Apple: 75,000 nodes → iMessage scale
```

### Limitations (Be Honest)
```
❌ Hot partitions (viral sensor) → single node overload
❌ Cross-partition queries slow (JOINs impossible)
✅ Application must model for distribution (sensor_id as partition key)
```

### Demo Sequence (2 minutes)
1. **Baseline**: 3 nodes, insert 1k sensor readings → measure throughput
2. **Scale up**: Add 2 nodes → re-measure (2x faster)
3. **`nodetool cleanup`**: Remove old data ranges from original nodes
4. **Kill node**: Show reads continue via replicas

```
nodetool tpstats  # Thread pool stats
# Before: WriteThreads=10 active
# After scale: WriteThreads distributed
```

**Bottom line**: **Add COTS hardware → multiply capacity instantly, no code changes.** Perfect for unpredictable IoT workloads.

## 3. Replication & Multi-Data-Center Awareness

Cassandra **automatically replicates data** across multiple nodes, racks, and data centers with configurable policies for fault tolerance and latency.

### Replication Basics

**Replication Factor (RF)**: How many copies of each partition.
```
RF=1: single node (fast but risky)
RF=3: 3 copies (typical production)
```

**Ring replication**: Sequential clockwise from primary owner.
```
Key=42 → NodeB (primary) → NodeC → NodeA (RF=3)
```

### Replication Strategies

**SimpleStrategy** (single DC, dev/demo):
```sql
CREATE KEYSPACE demo 
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};
```

**NetworkTopologyStrategy** (production, rack/DC aware):
```sql
CREATE KEYSPACE prod 
WITH replication = {
  'class': 'NetworkTopologyStrategy', 
  'dc1': 3,      # 3 replicas in Europe
  'dc2': 2       # 2 replicas in US
};
```

### Rack & Data Center Awareness

**Topology file** defines real network layout:
```
# cassandra-rackdc.properties
dc=dc1
rack=rack1

# Node2
dc=dc1
rack=rack2
```

**Placement rules**:
```
RF=3 in dc1 (2 racks):
Primary → rack1 → rack2 → rack1 (never 2x same rack)
```

### Your IoT Demo
```
sensors_eu (dc1, RF=3): Europe sensors
sensors_us (dc2, RF=2): US sensors

Kafka Europe → Cassandra dc1
Kafka US → Cassandra dc2 (low latency writes)
```

### Cross-DC Operations
```
Write to dc1 → asynchronously replicates to dc2
LOCAL_QUORUM: Only dc1 replicas (fast)
EACH_QUORUM: dc1+dc2 both need quorum (slow but strong)
```

### Verification Commands
```bash
# Replica locations for specific partition
nodetool getEndpoints prod sensors 123e4567-e89b-12d3-a456-426614174000

# Cluster topology
nodetool describecluster
nodetool status
```

### Demo Sequence (2 minutes)
1. **Create keyspaces**: SimpleStrategy vs NetworkTopologyStrategy
2. **Insert data**: Same partition key from different nodes
3. **`getEndpoints`**: Show replicas spread across racks
4. **Kill rack1**: Reads continue via rack2 replicas
5. **Multi-DC**: Show dc1/dc2 topology (fake with properties file)

```
Output example:
cassandra-1  dc1  rack1  Up  Normal
cassandra-2  dc1  rack2  Up  Normal  
cassandra-3  dc2  rack1  Up  Normal
```

### Production Benefits
```
✅ Survive entire rack/DC failure
✅ Low-latency local writes (LOCAL_QUORUM)
✅ Disaster recovery (async DC replication)
✅ Global apps (write EU, read US)
```

### Gotchas
```
❌ RF=3 needs 4+ nodes minimum
❌ Cross-DC writes slower (network RTT)
✅ Driver topology awareness = smart routing
```

**Bottom line**: **Automatic, configurable data redundancy across real network topology** = rack/DC fault tolerance without complex failover logic.

## 4. Tunable Consistency & Availability Model

Cassandra lets you **choose consistency vs. availability per-operation** using configurable consistency levels—trading strict guarantees for speed and fault tolerance (CAP theorem in practice). [docs.datastax](https://docs.datastax.com/en/cassandra-oss/3.0/cassandra/dml/dmlConfigConsistency.html)

### CAP Theorem Trade-off

```
Traditional RDBMS: C+P (consistency + partition tolerance) → unavailable during failures
Cassandra: Tunable CP ↔ AP per operation
```

**Eventual consistency**: All replicas converge to same value *eventually* (via read repair, anti-entropy). [geeksforgeeks](https://www.geeksforgeeks.org/dbms/gossip-protocol-in-cassandra/)

### Consistency Levels (CL)

**Write levels**:
```
ANY: Hinted handoff OK (fastest, weakest)
ONE: 1 replica ACKs
TWO: 2 replicas ACK
QUORUM: (RF/2)+1 replicas ACK (typical)
ALL: All RF replicas ACK (slowest, strongest)
LOCAL_QUORUM: Quorum in local DC only
EACH_QUORUM: Quorum in every DC
```

**Read levels**:
```
ONE: 1 replica responds
QUORUM: (RF/2)+1 replicas, return latest timestamp
ALL: All replicas respond
LOCAL_QUORUM: Quorum in local DC
```

### Quorum Math
```
RF=3:
QUORUM = (3/2)+1 = 2 replicas

RF=5:
QUORUM = (5/2)+1 = 3 replicas
```

### Strong Consistency Formula
```
Write CL + Read CL > RF = Strong consistency

Example (RF=3):
QUORUM write + QUORUM read: 2+2 > 3 ✅ (overlapping replicas)
ONE write + ONE read: 1+1 < 3 ❌ (stale reads possible)
```

### Your IoT Demo Use Cases

**High-volume raw sensors** (availability > consistency):
```sql
-- Fast writes, OK if 1 reading lost
INSERT INTO sensors.readings (...) 
USING CONSISTENCY ONE;

-- Fast reads, stale data acceptable
SELECT * FROM sensors.readings 
WHERE sensor_id = ? 
USING CONSISTENCY ONE;
```

**Critical aggregates** (consistency matters):
```sql
-- Hourly averages, must be durable
INSERT INTO sensors.hourly_avg (...) 
USING CONSISTENCY QUORUM;

-- Dashboard queries need accurate data
SELECT * FROM sensors.hourly_avg 
WHERE sensor_id = ? 
USING CONSISTENCY QUORUM;
```

### Availability During Failures

```
Cluster: 3 nodes, RF=3
Node2 crashes (2 replicas up)

ONE: ✅ Writes/reads succeed
QUORUM: ✅ 2 replicas available (2 ≥ 2)
ALL: ❌ Unavailable (only 2/3 up)
```

### Demo Sequence (3 minutes)

**1. Setup test keyspace**:
```sql
CREATE KEYSPACE test_cl 
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};

CREATE TABLE test_cl.sensors (
    id UUID PRIMARY KEY,
    value INT
);
```

**2. Write at different CLs**:
```bash
# Fast write
cqlsh -e "INSERT INTO test_cl.sensors (id, value) VALUES (uuid(), 100) USING CONSISTENCY ONE;"

# Quorum write
cqlsh -e "INSERT INTO test_cl.sensors (id, value) VALUES (uuid(), 200) USING CONSISTENCY QUORUM;"
```

**3. Kill a node**:
```bash
docker stop cassandra-3
```

**4. Try operations**:
```bash
# ONE still works
cqlsh cassandra-1 -e "INSERT INTO test_cl.sensors (id, value) VALUES (uuid(), 300) USING CONSISTENCY ONE;"

# QUORUM still works (2/3 up)
cqlsh cassandra-1 -e "INSERT INTO test_cl.sensors (id, value) VALUES (uuid(), 400) USING CONSISTENCY QUORUM;"

# ALL fails (unavailable)
cqlsh cassandra-1 -e "INSERT INTO test_cl.sensors (id, value) VALUES (uuid(), 500) USING CONSISTENCY ALL;"
# ❌ WriteTimeout: code=1100 [Unavailable exception]
```

**5. Read repair demonstration**:
```bash
# Write at ONE (only 1 replica gets it)
cqlsh cassandra-1 -e "INSERT INTO test_cl.sensors (id, value) VALUES (123-abc, 999) USING CONSISTENCY ONE;"

# Read at QUORUM (coordinator fetches from 2 nodes, sees inconsistency)
cqlsh cassandra-2 -e "SELECT * FROM test_cl.sensors WHERE id = 123-abc USING CONSISTENCY QUORUM;"
# → Background read repair updates stale replica
```

### Hinted Handoff (Availability Enhancement)
```
Node3 down → Write CL=ONE:
Coordinator writes to Node1, stores hint for Node3
Node3 up → replays hints → eventual consistency
```

```bash
nodetool statushandoff
nodetool truncatehints # Clear hint queue
```

### Real-World Patterns

**Netflix**:
```
Writes: LOCAL_QUORUM (fast, durable in DC)
Reads: ONE (fast, stale OK for recommendations)
```

**Banking**:
```
Account balance: QUORUM/QUORUM (strong consistency)
Activity logs: ONE/ONE (eventual, high throughput)
```

### Configuration
```
# Default CL in cassandra.yaml
read_consistency: ONE
write_consistency: ONE

# Per-session in driver
session.execute(query, ConsistencyLevel.QUORUM)
```

### Limitations
```
❌ No read-your-writes at ONE (unless same coordinator)
❌ Quorum slower (network RTT × RF/2)
✅ Flexible per-table/query tuning
```

**Bottom line**: **Per-operation consistency dial** = optimize for latency OR correctness depending on data criticality. Your IoT raw data → ONE, analytics → QUORUM.

## 5. Write-Optimized Storage Engine (LSM Tree)

Cassandra uses a **Log-Structured Merge (LSM) tree** architecture that makes writes extremely fast by converting random disk I/O into sequential appends, then organizing reads through layered, immutable files. [cassandra.apache](https://cassandra.apache.org/doc/latest/cassandra/architecture/storage-engine.html)

### LSM Tree Components

```
Memory Tier:
├─ Commit Log (WAL - Write-Ahead Log)
└─ Memtable (sorted in-memory tree)

Disk Tier:
├─ SSTables (Sorted String Tables - immutable)
└─ Bloom Filters + Indexes
```

### Write Path (Deep Dive)

```
Client write → Coordinator → Replicas:

1. COMMIT LOG (durability)
   ↓ Sequential append to log file
   ↓ fsync() before ACK (configurable)
   
2. MEMTABLE (performance)
   ↓ Insert into in-memory red-black tree
   ↓ Sorted by partition key + clustering columns
   ↓ ACK to client immediately
   
3. FLUSH (threshold trigger)
   ↓ Memtable full (256MB default) OR time limit
   ↓ Write entire memtable → new SSTable
   ↓ Sequential disk write (fast)
   ↓ Create partition/column indexes
   ↓ Truncate commit log segment
   
4. COMPACTION (background)
   ↓ Merge overlapping SSTables
   ↓ Remove tombstones/old versions
   ↓ Improve read performance
```

### Why Writes Are Fast: O(1)

**Traditional B-Tree (RDBMS)**:
```
1. Find page on disk → random seek (10ms)
2. Lock page → modify → write back
3. Update indexes → more seeks
= 50-100 writes/sec/disk
```

**Cassandra LSM**:
```
1. Append to commit log → sequential (0.1ms)
2. Insert to memtable → in-memory (0.01ms)
= 10,000+ writes/sec/node
```

### SSTable Structure

```
Immutable file on disk:
/var/lib/cassandra/data/keyspace/table/
├─ Data.db          (actual data, sorted)
├─ Index.db         (partition key → offset)
├─ Summary.db       (sparse index sample)
├─ Filter.db        (Bloom filter)
├─ Statistics.db    (metadata, min/max timestamps)
└─ CompressionInfo.db
```

**Key properties**:
- **Immutable**: Never modified after creation
- **Sorted**: By partition key, then clustering columns
- **Timestamped**: Each cell has write timestamp (LWW - Last Write Wins)

### Read Path with LSM

```
Read query:
1. Check memtable → O(log n) tree lookup
2. Check row cache (if enabled)
3. Bloom filters → skip 90%+ SSTables → O(1) per file
4. Partition index → O(log n) binary search
5. Column index → jump to 256KB chunk → O(log n)
6. Read data blocks
7. MERGE results by timestamp → return latest
```

### Compaction Strategies

**Size-Tiered (STCS)** - default, write-heavy:
```
Tier 0: 4 small SSTables (64MB each)
Tier 1: 4 medium SSTables (256MB each)
Tier 2: 4 large SSTables (1GB each)

When 4 at same size → compact into 1 larger
```

**Leveled (LCS)** - read-heavy:
```
L0: 4 SSTables (no overlap)
L1: 40 SSTables (10x, no overlap within level)
L2: 400 SSTables (10x)

Guarantees: max 1-2 SSTables per read
```

**Time-Window (TWCS)** - time-series (YOUR PROJECT):
```
Window 1: 2026-01-21 00:00-01:00
Window 2: 2026-01-21 01:00-02:00
...
Expire old windows easily (delete files)
```

### Your IoT Demo Configuration

```sql
CREATE TABLE sensors.readings (
    sensor_id UUID,
    timestamp TIMESTAMP,
    temperature DOUBLE,
    PRIMARY KEY (sensor_id, timestamp)
) WITH CLUSTERING ORDER BY (timestamp DESC)
  AND compaction = {'class': 'TimeWindowCompactionStrategy',
                     'compaction_window_size': '1',
                     'compaction_window_unit': 'HOURS'};
```

**Why TWCS**:
- Each hour = 1 SSTable
- Old hours expire → just delete file (no tombstone overhead)
- Read recent hour → 1 SSTable only

### Tombstones (Deletes)

Cassandra doesn't delete immediately:
```
DELETE FROM sensors.readings WHERE sensor_id = ?;
→ Writes TOMBSTONE marker (timestamp)
→ Compaction removes tombstone+data later (gc_grace_seconds)
```

**TTL (Time-To-Live)**:
```sql
INSERT INTO sensors.readings (...) USING TTL 86400; -- 24 hours
→ Auto-tombstone after expiry
```

### Demo Sequence (4 minutes)

**1. Write performance test**:
```bash
# cassandra-stress benchmark
cassandra-stress write n=100000 -rate threads=50

# Output: ~50k ops/sec on 3-node cluster
```

**2. Check SSTables**:
```bash
nodetool flush sensors readings  # Force memtable flush

# List SSTables
ls -lh /var/lib/cassandra/data/sensors/readings*/
# Shows Data.db, Filter.db, Index.db files

nodetool tablestats sensors.readings
# SSTables: 3, Read latency: 0.5ms, Write latency: 0.05ms
```

**3. Compaction monitoring**:
```bash
nodetool compactionstats
# Active: 1, Pending: 2

watch nodetool cfstats sensors.readings
# SSTable count changes as compaction runs
```

**4. Commit log inspection**:
```bash
ls -lh /var/lib/cassandra/commitlog/
# Sequential log files, rotated when full

nodetool drain  # Flushes memtables before shutdown
```

**5. Bloom filter effectiveness**:
```bash
nodetool tablehistograms sensors readings
# Shows Bloom filter false positive rate (~1%)
```

### Performance Characteristics

**Writes**:
```
✅ O(1) average (append-only)
✅ 10k-50k ops/sec/node
✅ No read-before-write overhead
❌ Compaction CPU/disk cost (background)
```

**Reads**:
```
✅ O(log n) with indexes
❌ Slower than writes (multiple SSTables)
✅ Caching helps (row cache, key cache)
❌ Tombstone scans slow queries
```

### Configuration Tuning

**cassandra.yaml**:
```yaml
commitlog_sync: periodic  # or batch
commitlog_sync_period_in_ms: 10000  # 10s batching

memtable_flush_writers: 4  # Parallel flushers

concurrent_compactors: 4  # CPU cores for compaction
```

### Your IoT Context

```
100 sensors × 1 reading/sec = 100 writes/sec
→ Memtable absorbs all in memory
→ Flush every 256MB (~45 min @ 100 writes/sec)
→ Sequential SSTables per hour
→ Kafka → Spark → Cassandra pipeline never bottlenecked
```

### Real-World Numbers

**Apple iMessage**:
- 100k writes/sec/node
- Commit log on NVMe SSD
- TWCS for message history

**Netflix**:
- LCS for user profiles (read-heavy)
- STCS for event logs (write-heavy)

### Limitations

```
❌ Deletes expensive (tombstones linger)
❌ Range scans cross many SSTables (slow)
❌ Updates = append (space amplification)
✅ Perfect for write-heavy, append-only workloads
```

**Bottom line**: **Sequential writes + immutable files = 10-100x faster writes than RDBMS**, at the cost of more complex reads and compaction overhead. Perfect for IoT sensor streams.

## 6. Flexible, Query-Driven Data Model (CQL)

Cassandra uses **CQL (Cassandra Query Language)**—SQL-like syntax over a **denormalized, partition-centric model** optimized for specific queries, not general-purpose relations.

### Core Data Model

**Partition + Clustering**:
```sql
CREATE TABLE sensors.readings (
    sensor_id   UUID,        -- PARTITION KEY (hash → node)
    timestamp   TIMEUUID,    -- CLUSTERING KEY (sort order)
    temperature DOUBLE,
    humidity    DOUBLE,
    PRIMARY KEY (sensor_id, timestamp)
) WITH CLUSTERING ORDER BY (timestamp DESC);
```

**Physical layout**:
```
sensor_001:
  2026-01-21T10:00:00Z: {temp:25.5, hum:60}
  2026-01-21T10:00:01Z: {temp:25.7, hum:59}
  ... (sorted by time DESC)

sensor_002:
  2026-01-21T10:00:00Z: {temp:24.8, hum:62}
```

### Query Patterns (Fast)
```
-- Efficient (partition + range)
SELECT * FROM readings 
WHERE sensor_id = 123-abc 
  AND timestamp > '2026-01-21T09:00';

-- Efficient (full partition)
SELECT * FROM readings WHERE sensor_id = 123-abc;
```

### Query Patterns (Slow/Impossible)
```
❌ SELECT * FROM readings WHERE temperature > 25;  -- no index
❌ SELECT * FROM users JOIN readings;              -- no JOINs
❌ SELECT * FROM readings WHERE sensor_id IN (...); -- limit 100
```

### Denormalization (Query-First Design)
**Wrong** (normalize like SQL):
```
users → sensors → readings (JOIN hell)
```

**Right** (duplicate for queries):
```sql
-- Raw time-series
sensors.readings (sensor_id, time, temp)

-- Latest per sensor
sensors.latest (sensor_id, temp, updated_at)

-- Hourly aggregates  
sensors.hourly (sensor_id, hour_bucket, avg_temp)

-- Alerts (hot sensors)
sensors.alerts (alert_id, sensor_id, severity)
```

### Materialized Views (Auto-Duplication)
```sql
CREATE MATERIALIZED VIEW latest_readings AS
SELECT sensor_id, temperature, timestamp
FROM readings
WHERE sensor_id IS NOT NULL AND timestamp IS NOT NULL
PRIMARY KEY (sensor_id, timestamp)
WITH CLUSTERING ORDER BY (timestamp DESC);
```

**Automatic**: Writes to base → auto-written to view.

### Collections & Static Columns
```sql
CREATE TABLE sensor_metadata (
    sensor_id UUID PRIMARY KEY,
    location TEXT,
    tags SET<TEXT>,           -- ['indoor', 'critical']
    config MAP<TEXT, DOUBLE>, -- {'threshold': 30.0}
    readings LIST<DOUBLE>     -- Recent temps
);
```

### Secondary Indexes (SAI - Modern)
```sql
-- Traditional (slow)
CREATE INDEX ON readings (temperature);

-- SAI (Storage Attached Index - Cassandra 4.0+)
CREATE INDEX latest_idx ON readings (temperature) USING 'sai';
```

### Your IoT Project Schema
```
1. Raw stream (Kafka → Spark → Cassandra)
sensors.raw_readings (sensor_id, time, temp, hum)

2. Latest readings (fast dashboard)
sensors.current (sensor_id, temp, hum, updated)

3. Analytics (Spark computes)
sensors.hourly_stats (sensor_id, hour, avg_temp, max_temp)

4. Alerts
sensors.alerts (alert_id, sensor_id, reason, time)
```

### CQL Demo (nodetool + cqlsh)
```
1. Create tables with partition/clustering keys
2. Insert 1000 readings
3. Query patterns:
   SELECT * FROM raw_readings WHERE sensor_id = ?;  ✅ Fast
   SELECT * FROM raw_readings LIMIT 10;             ✅ Fast (scatter read)
   SELECT * FROM raw_readings WHERE temp > 30;      ❌ Slow

4. Show denormalized queries:
   SELECT temp FROM current WHERE sensor_id = ?;    ✅ Instant latest
```

### Wide Rows (Time-Series Power)
```
sensor_001 partition = 1GB of 1-second readings (millions rows)
→ Single row scan = fast range queries
→ Perfect for IoT logs, events, metrics
```

### Limitations (Be Honest)
```
❌ No ad-hoc queries (must model upfront)
❌ Deletes = tombstones (space overhead)
❌ Secondary indexes = anti-pattern (use Spark)
✅ Spark/Kafka handle complex analytics
```

### Evolution from 2009 Paper
```
Thrift → CQL (SQL-like, 1.2)
Wide-column families → tables
CLI → cqlsh → drivers
```

**Bottom line**: **Query-first denormalization + time-series optimized clustering** = sub-ms lookups for your exact access patterns, Spark handles the rest.

## 7. Virtual Nodes (VNodes) & Automatic Load Balancing

**VNodes** (introduced 1.2, default 2.2+) solve token ring imbalance by giving each physical node **multiple small token ranges** (256 default), enabling automatic, even data distribution.

### The Random Token Problem (Pre-VNodes)

```
3 nodes, random tokens:
NodeA: token 5 → owns 0-5, 50-100 (55% ring!) 
NodeB: token 10 → owns 5-10, 10-50 (15%)
NodeC: token 60 → owns 100-360 (30%)
→ NodeA overloaded!
```

**Manual fix**: `nodetool move` → fragmented ranges → performance issues.

### VNodes Solution

**Each physical node = 256 virtual nodes**:
```
Physical NodeA:
vnode1: token 123 → owns 123-124
vnode2: token 456 → owns 456-457
...
vnode256: token 2^127-1 → owns 2^127-1 to 0

→ ~0.4% ring per vnode → perfectly even!
```

### Auto-Balancing Magic

```
New node joins:
1. Generates 256 random tokens across entire ring
2. Steals tiny ranges from 256 neighbors (~1/N total data move)
3. Streaming happens in parallel → fast join

No manual intervention needed!
```

### Demo (nodetool ring)

**Without VNodes** (`num_tokens: 1`):
```
nodetool ring  # Uneven ranges, manual balancing needed
```

**With VNodes** (default):
```
nodetool ring
Address    Load       Owns      Token
cassandra1 1.2GB    33.33%    1,234 tokens (256 vnodes)
cassandra2 1.1GB    33.33%    1,234 tokens
cassandra3 1.3GB    33.34%    1,234 tokens
```

### Configuration
```yaml
# cassandra.yaml
num_tokens: 256  # Default, good for most
# num_tokens: 1   # Legacy single-token mode
```

### Your IoT Scaling Demo
```
Day 1: 3 nodes × 256 vnodes = 768 ranges → even sensor distribution
Day 2: Add 2 nodes → 5×256 = 1280 ranges → auto-rebalance
       Kafka/Spark continue without config change
```

### Production Benefits
```
✅ Add/remove nodes = ~1/N data movement (not full reshuffle)
✅ Heterogenous hardware OK (NodeA slow → gets fewer vnodes over time)
✅ No token math planning
✅ Smaller ranges = better streaming speed
```

### Advanced: Token Auto-Adjustment
```
Cassandra 4.0+: Dynamic vnode adjustment
Overloaded node → releases vnodes to neighbors
Underloaded → claims more automatically
```

### Commands to Show VNodes
```bash
# VNode count per node
nodetool describecluster

# Streaming progress (during join)
nodetool netstats

# Range ownership
nodetool ring keyspace | grep Owns
```

### Demo Sequence (1 minute)
```
1. Baseline 3-node cluster:
nodetool ring  # 256 tokens/node

2. Add node4:
docker-compose up -d cassandra-4

3. Watch join:
nodetool status  # "Joining" → "Normal"
nodetool netstats  # "Streaming 50MB from cassandra1"

4. Verify balance:
nodetool ring  # 4 nodes, ~25% each
```

### Trade-offs
```
✅ Auto-balancing, simple ops
❌ Slightly higher metadata (256 ranges vs 1)
❌ More streaming threads during rebalance
✅ Negligible for modern hardware
```

### Comparison: VNodes vs Dynamo (Paper Reference)
```
Paper chose "manual moves" over Dynamo's multi-tokens
VNodes = Cassandra adopting the "Dynamo way" + improvements
```

**Bottom line**: **256-token auto-balancing** = add commodity servers → instant capacity scaling without ops nightmares. Your Kafka→Cassandra pipeline scales effortlessly.

## 8. Gossip and Failure Detection

Cassandra uses **Gossip protocol** (Scuttlebutt variant) for **decentralized cluster coordination**—nodes share state with random peers every second, spreading information cluster-wide exponentially.

### Gossip Protocol Basics

**No central service** (unlike ZooKeeper):
```
NodeA ↔ NodeB ↔ NodeC ↔ NodeD (random pairs every 1s)
↓
Local knowledge → cluster-wide convergence (exponential)
```

**What gossips**:
```
- Node status (Up/Down)
- Heartbeats
- Load/ownership (tokens)
- Schema versions
- DC/rack topology
- Hints status
```

### Scuttlebutt Anti-Entropy

**Problem**: NodeA thinks NodeC up, NodeB thinks down → inconsistent views.

**Solution**: Versioned digests exchanged:
```
NodeA sends: "NodeC:up@version123"
NodeB: "NodeC:down@version124" → NodeA updates
```

**Converges**: All nodes agree on state within seconds.

### Failure Detection (Phi Accrual)

**Adaptive heartbeat timeouts**:
```
Fast network: timeout = 500ms
Slow/high-latency: timeout = 2s

Phi accrual: "NodeX φ=1.2 → 70% likely dead"
```

**Demo**: `nodetool gossipinfo`
```
/127.0.0.1: Schema:1|Token:123|Status:Normal|Load:1.2GB
/127.0.0.2: Schema:1|Token:456|Status:Normal|Load:1.1GB
/127.0.0.3: Schema:1|Token:789|Status:Down|Phi:2.1
```

### Your IoT Demo Context
```
Sensor spike → NodeB load spikes → gossiped
Other nodes aware → client driver routes around
NodeC joins → gossiped → Spark driver discovers
```

### Demo Sequence (1 minute)
```
1. Healthy cluster:
nodetool gossipinfo  # All nodes NORMAL

2. Kill node3:
docker stop cassandra-3

3. Watch convergence:
nodetool status      # Node3 DOWN (within 2 φ accruals)
nodetool gossipinfo  # Status:Down gossiped everywhere

4. Restart:
docker start cassandra-3
nodetool status      # Node3 UP → NORMAL
```

### Production Resilience
```
✅ Survive entire rack failure (gossip via other racks)
✅ Detect flapping nodes (φ accrual damping)
✅ Schema changes propagate (versioned)
✅ No ZooKeeper dependency
```

### Commands
```
nodetool status          # High-level view
nodetool gossipinfo      # Raw gossip state
nodetool describecluster # Topology summary
nodetool ring            # Token ownership (gossip derived)
```

### Gossip Configuration
```yaml
# cassandra.yaml
phi_convict_threshold: 8      # φ > 8 = DOWN (default)
gossip_interval: PT1S         # Every 1 second
conviction_policy: Percentile # Adaptive timeouts
```

### Advanced: Cross-DC Gossip
```
DC1 ↔ DC2 (lower frequency, seed nodes)
LOCAL_QUORUM ignores remote DC status
```

### Limitations
```
❌ Gossip storms (rare, network partitions)
❌ Eventual convergence (not instant)
✅ Seconds to minutes, not hours
```

### Comparison: Gossip vs Heartbeats
```
Central monitor: Single point of failure
Gossip: Decentralized, self-healing
```

**Bottom line**: **Self-organizing cluster state** via lightweight peer gossip = resilient coordination without centralized services. Your 3-node Docker demo proves it works even with node failures.