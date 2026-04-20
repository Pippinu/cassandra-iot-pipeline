# Apache Cassandra — Complete Study Notes

---

## 1. Core Architecture

Cassandra is a **masterless**, **peer-to-peer (P2P)** distributed database. All nodes are equal, any node can serve any request, and there is no single point of failure. This makes it fundamentally different from traditional databases that rely on a master-slave topology.

### 1.1 Node Responsibilities

Every node in a Cassandra cluster handles three core responsibilities:

1. **Request Coordination**: Any node can act as a **coordinator** for a client request. When a client connects, the receiving node becomes the coordinator for that operation. It is responsible for:
   - Hashing the partition key to locate the correct token on the ring
   - Identifying the replica nodes responsible for that token range
   - Routing the request to those replicas
   - Enforcing the Consistency Level and Replication Factor

In particular: 

```
Client  → connects to Node A (coordinator) →
        → Node A hashes the partition key → token lands on Node C →
        → Node A routes the write to Node C (primary owner), Node D, Node E (replicas)
```

2. **Ring Membership & Failure Detection** (via the Gossip Protocol): Cassandra must continuously track which nodes are alive or down. This is handled entirely through gossip:
   - Every second, each node initiates a gossip round with up to 3 randomly chosen peers
   - Each round exchanges state information about the node itself and about other nodes it knows of
   - Over time, state information propagates to the entire cluster without any central coordinator

3. **Local Storage**: Each node stores its share of data using an **LSM-Tree (Log-Structured Merge-Tree)** engine (see Section 4).

---

### 1.2 Ring Architecture & Consistent Hashing

Cassandra achieves horizontal scalability by distributing data across nodes using **consistent hashing**.

#### The Problem with Naive Hashing

A naive approach assigns data by computing `hash(key) % number_of_nodes`. This breaks down the moment a node is added or removed: almost every key mapping becomes invalid, forcing a massive data redistribution — unacceptable in a large distributed system.

#### The Token Ring

Consistent hashing solves this by placing both nodes and data keys on a shared **circular hash ring** (the token ring):

- The ring represents the full output space of the hash function
- Each node is assigned one or more **tokens** — specific positions on the ring
- When data is written, its **partition key** is hashed (via **Murmur3**) to a position on the ring
- The data is stored on the first node encountered walking clockwise from that position, plus additional replicas on subsequent nodes (determined by the Replication Factor)

When a node joins or leaves, **only the keys in the range that the new node takes over need to move**. All other nodes' data is unaffected — this is the core advantage of consistent hashing.

#### Virtual Nodes (vNodes)

Early Cassandra assigned each physical node a single token, causing uneven data distribution — especially when node capacities differed or when a node failed.

Modern Cassandra uses **virtual nodes (vNodes)**: each physical node is assigned **256 tokens by default**, scattering it across many small arcs of the ring. This achieves:

- **Uniform data distribution** across nodes
- **Faster rebalancing** when a node is added or removed (many small chunks move instead of one large one)
- **Better fault tolerance** (a failing node's load spreads across all remaining nodes, not just its immediate neighbors)

#### Replication

With a Replication Factor of RF=3, Cassandra hashes the partition key to its primary owner, then scans clockwise to find 2 additional vNodes on **different physical machines** to store replicas. It deliberately skips vNodes on the same physical machine to ensure a single hardware failure cannot take down multiple replicas.

---

## 2. Data Model

Cassandra's data model follows a strict hierarchy. Understanding each level is essential to working with Cassandra correctly.

### 2.1 Hierarchy Overview

```
Cluster
  └── Keyspace         (replication settings)
        └── Table      (schema, one per query pattern)
              └── Partition  (physical unit of storage, lives on one node)
                    └── Row  (identified by clustering columns)
                          └── Column (typed value)
```

### 2.2 Cluster

The **Cluster** is the top-level container — the entire fleet of nodes working together. It can span multiple physical data centers or cloud regions. Nodes communicate their health and state through the Gossip Protocol. You scale a cluster simply by adding more nodes, which automatically increases both storage capacity and throughput.

---

### 2.3 Keyspace

A **Keyspace** is the equivalent of a database or schema. In addition to grouping tables logically, it defines **how data is replicated across the cluster** — a critical responsibility.

**Settings defined at the Keyspace level (inherited by all tables):**

- **Replication Factor (RF)**: How many copies of each piece of data exist. RF=3 means every row lives on three different nodes.
- **Replication Strategy**:
  - `SimpleStrategy`: For single data center deployments
  - `NetworkTopologyStrategy`: For multi-data center deployments (e.g., 3 replicas in `US-East`, 3 in `EU-West`)
- **Durable Writes**: Boolean (default: `true`). When enabled, every write goes through the CommitLog. Disabling it increases speed but risks data loss on power failure.

**Settings that remain table-level (not inherited):**
- Compaction Strategy, Compression, TTL (Time to Live)

---

### 2.4 Table (Column Family)

A **Table** (historically called a Column Family) defines the typed schema for your data. Unlike in relational databases, you do **not** model tables around entities — you model them around the **specific query** they need to serve. This is the central design principle of Cassandra (see Section 3).

Tables support **sparse storage**: rows in the same table can have entirely different sets of populated columns. A column with no value simply does not exist on disk — there is **no null placeholder** wasting space. This is what makes Cassandra a **Wide-Column Store**.
- NOTE: No null placeholder. Even if the driver returns `nulls` when we run a `SELECT *` query, it is purely a driver-side representation, not something stored in cassandra.

---

### 2.5 Partition

The **Partition** is the fundamental unit of data distribution and the "atom" of storage in Cassandra.

- All rows sharing the same **Partition Key** belong to the same partition
- A partition is guaranteed to reside on one node (plus its replicas)
- Queries that stay within a single partition are the fastest because Cassandra only needs to visit one physical location on disk

---

### 2.6 Primary Key, Partition Key & Clustering Columns

The **Primary Key** is composed of two parts:

| Component | Role |
|---|---|
| **Partition Key** (mandatory) | Hashed to determine the physical node that owns the data. All rows with the same partition key are stored together. |
| **Clustering Columns** (optional) | Determine the **physical sort order** of rows inside a partition. Also uniquely identify a row within its partition. |

#### Defining Keys in CQL

```sql
-- Simple primary key
PRIMARY KEY (groupname, username)
-- Partition Key: groupname | Clustering Key: username

-- Composite partition key (both fields hashed together)
PRIMARY KEY ((groupname, email), username)
-- Partition Key: (groupname, email) | Clustering Key: username

-- Multiple clustering keys (creates a sort hierarchy)
PRIMARY KEY (groupname, join_date, username)
-- Partition Key: groupname | Clustering Keys: join_date, then username
```

#### Why Use Multiple Clustering Keys?

1. **Uniqueness**: Using only `join_date` as a clustering key means only one row per date per partition. Adding `username` creates a unique identity for every record.
2. **Efficient Lookups**: The full path `join_date → username` is physically indexed, so Cassandra can jump directly to a specific row without scanning.
3. **Range Queries**: Multiple clustering keys enable powerful range queries like: *"Give me all users who joined 'Admins' between January and March, sorted alphabetically."*

#### Key Rules & Constraints

- **Mandatory in WHERE**: The Partition Key must always appear in a `WHERE` clause to locate the right node. Without it, Cassandra would have to scan the entire cluster.
- **Order matters**: Clustering columns must be queried in the order they are defined. You cannot skip `join_date` to filter directly on `username` without a performance penalty.
- **Sort is baked in**: The physical sort order is set at write time using `WITH CLUSTERING ORDER BY`. You cannot re-sort at runtime; if you need a different sort order, create a new table.

---

### 2.7 Row

A **Row** is the smallest unit of data in a table. It is uniquely identified within its partition by its clustering columns. The partition key determines *which node* the row lives on; the clustering columns determine *where within that partition* the row sits.

Cassandra uses **upsert semantics**: inserting a row with an already-existing Partition Key + Clustering Key combination will not create a duplicate — it will overwrite the existing row.

---

### 2.9 Super Columns (Deprecated)

In early Cassandra (pre-2.0, Thrift API era), the data model included a concept called **Super Columns** — essentially "columns containing columns," a two-level nesting structure where a single column could hold a map of sub-columns. 
* The idea was to model hierarchical or grouped data within a single row.

They were deprecated and eventually removed for a fundamental storage problem: **all sub-columns inside a super column were serialized into a single binary blob on disk**. 
* This meant that reading even a single sub-column required Cassandra to deserialize the *entire* super column — every sub-column — regardless of how many existed. 
* The more data nested inside, the worse the read performance became. 
* Additional problems included expensive compaction merges for partial updates, and the fact that super columns were never accessible via CQL (only through the legacy Thrift API).

The solution was the **composite column model** — what you know today as clustering columns. 
* Instead of nesting data inside a blob, each logical "sub-column" becomes an independent, individually addressable cell on disk. 
* This achieves the same hierarchical data representation, but each value can be read, written, and compacted independently. 
* Modern CQL tables with clustering columns are precisely this model under the hood, making super columns entirely obsolete.

---

### 2.10 Wide-Column Store vs. Relational Schema

| Feature | Document Store (MongoDB) | Wide-Column Store (Cassandra) | Relational DB (PostgreSQL) |
|---|---|---|---|
| **Schema Style** | Schema-on-Read (flexible JSON) | Schema-on-Write (sparse storage) | Strict schema (fixed-width rows) |
| **Enforcement** | Application level | Metadata level | Database level |
| **Storage Logic** | Self-describing per record | Only populated cells stored | Space reserved for every column in every row |
| **Null Cost** | No overhead | Zero bytes on disk | Fixed-width overhead per cell |
| **Flexibility** | Infinite (every document can differ) | High (millions of columns per partition) | Low (schema changes require migrations) |
| **Best Use Case** | Rapid prototyping, nested data | Massive scale, high-velocity writes | ACID transactions, complex relationships |

> **Analogy**: An RDBMS is like a pre-printed tax form — you must fill every box. Cassandra is like a blank notebook — you only write down the headers for the information you actually have.

---

## 3. Query-First Data Modeling

This is the most important design principle in Cassandra: **model your tables around your queries, not your entities**.

### 3.1 Why No Joins?

Cassandra deliberately does **not** support JOIN operations. Because data is partitioned across many nodes, a join would require coordinating across multiple nodes simultaneously — this is expensive, slow, and incompatible with Cassandra's design goals of predictable, low-latency reads.

Instead, Cassandra embraces **denormalization**: the same data is duplicated across multiple query-specific tables. Storage is cheap; CPU cycles and user patience (latency) are expensive.

---

### 3.2 Designing Tables Around Queries

For each query your application needs to serve, you create a dedicated table with a Primary Key optimized for that exact access pattern.

**Example: IoT sensor data**

Suppose you have two queries:
- **Query 1**: Get temperatures for a city on a specific date
- **Query 2**: Get full sensor details (temperature, humidity, weather, coordinates) for a city on a specific date

You create separate tables for each:

```sql
-- Ingestion table (raw writes from sensors)
CREATE TABLE raw_sensor_data (
    sensor_id UUID,
    timestamp TIMESTAMP,
    city TEXT,
    temperature FLOAT,
    humidity FLOAT,
    weather TEXT,
    coords FROZEN<tuple<FLOAT,FLOAT>>,
    PRIMARY KEY ((sensor_id), timestamp)
) WITH CLUSTERING ORDER BY (timestamp DESC);

-- Query 1: weather and temperature by sensors
CREATE TABLE weather_by_sensor (
    sensor_id UUID,
    date DATE,
    city TEXT,
    timestamp TIMESTAMP,
    temperature FLOAT,
    weather TEXT,
    PRIMARY KEY ((sensor_id, date), timestamp)
) WITH CLUSTERING ORDER BY (timestamp DESC);

-- Query 2: full details by city and date
CREATE TABLE details_by_city_date (
    city TEXT,
    date DATE,
    sensor_id UUID,
    timestamp TIMESTAMP,
    temperature FLOAT,
    humidity FLOAT,
    weather TEXT,
    coords FROZEN<tuple<FLOAT,FLOAT>>,
    PRIMARY KEY ((city, date), timestamp)
);
```

```sql
-- Query 1 execution
SELECT temperature, weather FROM weather_by_sensor WHERE sensor_id=? AND date='2025-03-31';
```

---

### 3.3 Handling New Query Requirements

When a new query pattern arises that the existing tables cannot serve efficiently, you have three options:

| Approach | Description | When to Use |
|---|---|---|
| **Client-Side Join** | Run two separate queries, merge results in application code | Small datasets, rare queries |
| **Create a New Table** | Build a table specifically for the new query; backfill with historical data; write to both tables going forward | Production systems — the standard Cassandra approach |
| **Materialized View** | Define a view with a different Primary Key; Cassandra auto-syncs it from the base table | Use sparingly — carries performance overhead and eventual consistency issues; brittle under node failures |

**The standard workflow for a new table:**
1. Create the new table with the appropriate Primary Key
2. Backfill historical data (e.g., using Apache Spark)
3. Update the application to write to **both** the original and new table simultaneously

---

### 3.4 Secondary Indexes — A Performance Warning

Cassandra does support secondary indexes, but applying them to **high-cardinality columns** (like a unique user ID or email) is a **performance trap**. A secondary index query forces Cassandra to check every node in the cluster in a scatter-gather operation, defeating the purpose of the ring architecture.

**Best Practice**: If you need to search by a new column, create a new table where that column is the Partition Key. This trades cheap disk space for fast, predictable reads.

### 3.5 Storage-Attached Index (SAI)

**Storage-Attached Index (SAI)** is a modern secondary indexing mechanism introduced in Cassandra 4.0 (DataStax Astra) and made available in Apache Cassandra 5.0. It was designed to address the performance limitations of traditional secondary indexes (2i) described in section 3.4.

Unlike classic secondary indexes — which are local, node-level structures that force a scatter-gather across the entire cluster — SAI attaches the index **directly to the SSTable files** on each node, using more efficient data structures (based on techniques like tries and segment trees) that make lookups significantly faster and less resource-intensive.

```sql
-- VERBOSE VERSION
-- Creating an SAI index on a non-primary-key column
CREATE CUSTOM INDEX city_index ON details_by_city_date(temperature)
USING 'StorageAttachedIndex';

-- OR BY

-- SHORTHAND VERSION
-- Creating an SAI index on a non-primary-key column
CREATE INDEX ON details_by_city_date(temperature) USING 'sai';


-- Now you can query by temperature without a full cluster scan
-- Querying syntax remain the same, Cassandra will use the indexing column (temperature) 
-- to perform a faster search
SELECT * FROM details_by_city_date WHERE city='Venice' AND date='2025-03-31' AND temperature > 20.0;
```

The key practical difference is that SAI makes it **reasonable** to query on non-primary-key columns in certain scenarios, without the severe performance penalty of classic secondary indexes. 
* However, it is not a silver bullet — queries still work best when the partition key is provided (as in the example above), and SAI is not a replacement for good query-first table design. 
* It is best thought of as a **complement** to the query-first model for cases where creating a new dedicated table would be excessive, and the query volume or cardinality is manageable.

#### Partition Key is still fundamental for performance

While the query looks the same, the performance profile changes drastically. However, there is one crucial rule you must remember to get that "better performance":

* The "Fast" Way: `SELECT * FROM details_by_city_date WHERE city = 'Rome' AND date='2025-03-31' AND temperature > 25;`

    Why: You provided the Partition Key (city, date). Cassandra goes straight to one node, and that node uses the SAI to quickly find the specific temperature. This is highly scalable.

* The "Heavy" Way: `SELECT * FROM details_by_city_date WHERE temperature > 25;`
    
    Why: You did not provide a Partition Key. Even with an SAI, Cassandra must ask every node in the cluster to check its local SAI for temperatures > 25.

---

## 4. LSM-Tree Storage Engine

Cassandra's storage engine is built on a **Log-Structured Merge-Tree (LSM-Tree)** architecture, optimized for high-throughput write workloads. Unlike relational databases that use B-Trees with random disk I/O, Cassandra uses an **append-only model** — writes never modify existing data on disk.

### 4.1 The Write Path

Every write follows this precise sequence on each replica node:

```
Client Write
     │
     ▼
1.1 CommitLog (append-only, on-disk) ──→ durability guaranteed on crash
     │
     ▼
1.2 MemTable (in-memory, sorted by partition key) ──→ immediately queryable
     │
     │ (when MemTable is full or CommitLog approaches max size)
     ▼
2. SSTable (flushed to disk, immutable) ──→ CommitLog segment truncated
```

1. CommitLog and MemTable, write is confirmed after both successful:
    1.1 **CommitLog**: In parallel to MemTable, every write is immediately appended to an on-disk, append-only log, the *CommitLog*. 
    - If the node crashes before anything else happens, the write can be recovered from the CommitLog on restart. 
    - The write is considered durable once it hits the CommitLog.

    1.2 **MemTable**: In parallel to CommitLog, the data is written to an in-memory (RAM) sorted buffer (**one MemTable per table**). 
    - Data here is immediately visible to reads.
    - If crash or power fail occurrs, MemTable is lost but write operations can be recovered through CommitLog.

2. **SSTable Flush**: When the MemTable reaches a size threshold (or the CommitLog nears its max size), the MemTable is flushed to disk as an **SSTable (Sorted String Table)**. 
   - The **MemTable is discarded** and the **CommitLog segment is truncated**.

### 4.2 SSTables

SSTables are **immutable** on-disk files. Once written, they are never modified. This is fundamental:

- **Updates** write a new version of the cell with a newer timestamp
- **Deletes** write a special marker called a **tombstone**
- At read time, Cassandra merges all versions and picks the most recent one

Each SSTable is accompanied by auxiliary structures:

| Structure | Purpose |
|---|---|
| **Index file** | Maps partition keys to their byte offset within the SSTable for fast lookup |
| **Bloom filter** | Probabilistic in-memory structure that answers "is this key in this SSTable?" — eliminates unnecessary disk reads (no false negatives, rare false positives) |
| **Summary / Compression info** | Metadata about block sizes and compression settings |

### 4.3 Compaction

Since SSTables are immutable and accumulate over time, Cassandra periodically runs **compaction**: it merges multiple SSTables into one, discarding outdated cell versions and expired tombstones. Compaction:

- Reduces the number of SSTables a read must consult
- Reclaims disk space from stale data, for the same cell the version with the **highest timestamps wins** (***last-write-wins*** strategy).
- Improves read performance (at the cost of temporary write amplification — rewriting data)

**Compaction Strategies:**

| Strategy | Description | Best For |
|---|---|---|
| **SizeTieredCompactionStrategy (STCS)** | Merges SSTables of similar size | Write-heavy workloads (default) |
| **LeveledCompactionStrategy (LCS)** | Organizes SSTables into levels; better read performance, higher write overhead | Read-heavy workloads |
| **TimeWindowCompactionStrategy (TWCS)** | Groups SSTables by time window | Time-series / IoT data |

### 4.4 Tombstones

Deletes in Cassandra do not remove data immediately. Instead, a **tombstone marker** is written with a timestamp. During compaction, tombstones suppress the deleted data. After the **`gc_grace_seconds`** period (default: 10 days), tombstones are permanently discarded.

This delay is intentional: it prevents "zombie data" from resurrecting on nodes that were temporarily down and missed the original delete. However, a large accumulation of tombstones before compaction can significantly degrade read performance — an important operational concern.

### 4.5 Write Operation Key Properties

- **No random writes**: every disk write is **sequential** — CommitLog appends and SSTable flushes are both linear.
- **No in-place updates**: **updates are new writes** with a newer timestamp; the old value is cleaned up lazily during compaction.
- **No locking**: because nothing is modified in place, **concurrent writes never block each other**.
- **Write cost is constant $O(1)$**: the write path is always the same two operations (CommitLog + MemTable), regardless of how much data already exists in the table — this is why Cassandra sustains 10k–50k writes/sec per node consistently.

---

### 4.6 The core Read Path

A read on a single node proceeds as follows:

- **Read from MemTable** — catches any writes that haven't been flushed to disk yet.
- **Read from SSTable(s)** — the persisted data on disk.
- **Merge** — resolve multiple versions of the same cell using ***last-write-wins*** (highest timestamp), suppress deleted cells via tombstones, return the final result.

### 4.7 Read Optimization

A read on a single node proceeds as follows:

1. Check the **MemTable** (most recent writes are here)
2. Check the **row cache** (if enabled)
3. Check **Bloom filters** for each SSTable on disk to skip irrelevant files
4. Use the **key cache / partition index** to find the exact byte offset
5. Read from the relevant SSTable(s) on disk
6. **Merge** all results from MemTable and SSTables, using timestamps to resolve version conflicts and tombstones to suppress deleted data

Reads are slightly more complex than writes because data for the same partition can be spread across multiple SSTables accumulated over time.

Because reads must potentially consult multiple SSTables, Cassandra maintains several structures to make the read path as fast as possible.

- **Bloom Filter**

    Each SSTable has an associated **Bloom filter** — a small, probabilistic in-memory structure. Before touching disk, Cassandra asks the Bloom filter: *"Does this partition key exist in this SSTable?"*
    - If the answer is **no**, the SSTable is skipped entirely — no disk read needed
    - If the answer is **yes**, the SSTable *probably* contains the key (rare false positives are possible, but false negatives never occur)

    This eliminates the majority of unnecessary disk reads when data is spread across many SSTables.

- **Key Cache / Partition Index**
  
    Once a Bloom filter confirms a key *might* be in a given SSTable, Cassandra needs to find it. 
      - The **partition index** maps each partition key to its exact **byte offset** within the SSTable file. 
      - The **key cache** keeps recently accessed offsets in memory, so Cassandra can jump directly to the right position on disk without scanning the index file again.

- **Row Cache**
  
    An optional, coarser-grained cache that stores **entire deserialized partitions** in memory. When a partition is in the row cache, Cassandra skips the MemTable, Bloom filters, and disk entirely. It is useful for small, frequently-read "hot" partitions but disabled by default because it consumes significant heap memory and can become a bottleneck under write-heavy workloads (every write to a cached partition invalidates its cache entry).

---

## 5. Cassandra vs. Relational Databases

| Aspect | Cassandra | Relational DB (e.g., PostgreSQL) |
|---|---|---|
| **Architecture** | Masterless P2P ring, integrated clustering | Master-slave (single point of failure); clustering is an add-on |
| **Schema** | Flexible, sparse wide-column storage | Fixed, strict, every cell occupies space |
| **Normalization** | Denormalized, data duplicated across tables | Normalized with joins |
| **Query Model** | Partition-key driven, no joins | SQL joins, subqueries, ad-hoc queries |
| **Transactions** | No cross-partition ACID; eventual/tunable consistency | Full ACID guarantees |
| **Scaling** | Horizontal — add nodes linearly | Vertical — larger machines; horizontal sharding is complex |
| **Write Speed** | Extremely high (append-only, no random I/O) | Slower under high write throughput (B-Tree random I/O) |
| **Read Flexibility** | Only pre-modeled queries are fast | Any query can be run (at varying speeds) |
| **Failure Tolerance** | No single point of failure by design | Master failure brings down the cluster |

### Why Cassandra Avoids RDBMS Operations

Cassandra does not support JOINs, foreign keys, or cross-partition transactions because these operations require coordinating across multiple nodes — introducing latency, locking, and failure surface that are incompatible with the goal of linear horizontal scalability and high availability.

The tradeoff is clear: **Cassandra pre-computes query results at write time** (everything we need is already present in the tables through denormalization), so reads are always fast, single-partition operations. Relational databases defer this work to query time, which is flexible but costly at scale.

## 6. CAP Theorem & Cassandra's Position

The **CAP Theorem** states that a distributed system can only **guarantee two out of three** of the following properties simultaneously:

- **Consistency (C)**: Every read receives the most recent write (or an error). All nodes see the same data at the same time.
- **Availability (A)**: Every request receives a response (no errors), even if the data might not be the most recent.
- **Partition Tolerance (P)**: The system continues to operate even when network partitions (communication failures between nodes) occur.

Since **network partitions are unavoidable** in any real distributed system, every distributed database must choose between C and A when a partition happens. Cassandra chooses **AP by default**: it remains available and keeps accepting reads and writes even during a partition, at the potential cost of returning slightly stale data on some nodes.

However, Cassandra's consistency is **tunable** — meaning you can shift its behavior toward CP for specific operations by choosing a stricter Consistency Level, at the cost of some availability and latency.

***

## 7. Tunable Consistency

Cassandra does not apply a fixed consistency model globally. Instead, for **every individual read and write**, you choose a **Consistency Level (CL)** — the number of replica nodes that must acknowledge the operation before the coordinator considers it successful.

### 7.1 Common Consistency Levels

| Consistency Level | Replicas Required | Notes |
|---|---|---|
| `ONE` | 1 | Fastest; least safe — the other replicas will sync eventually |
| `TWO` / `THREE` | 2 or 3 | Fixed number of replicas |
| `QUORUM` | `⌊RF/2⌋ + 1` | Majority of all replicas across all data centers |
| `LOCAL_QUORUM` | Majority within the local DC | Best choice for multi-DC deployments |
| `ALL` | All replicas | Strongest consistency; any single replica failure blocks the operation |

With RF=3, `QUORUM` requires **2 replicas** to respond.

### 7.2 The Strong Consistency Rule

To guarantee that a read **always returns the latest write**, the following condition must hold:

> **Write CL + Read CL > RF**

**Example with RF=3:**
- `QUORUM` write (2 nodes) + `QUORUM` read (2 nodes) = 4 > 3 ✅ — strong consistency guaranteed
- `ONE` write (1 node) + `ONE` read (1 node) = 2 ≤ 3 ❌ — a stale read is possible

The overlap between write and read replicas ensures at least one node always has the latest version of the data.

### 7.3 Eventual Consistency

When you use low consistency levels (e.g., `ONE`), Cassandra operates in **eventual consistency** mode: all replicas will *eventually* converge to the same value, but a read immediately after a write might return a stale result from a replica that hasn't been updated yet. This is the default tradeoff Cassandra makes in favor of availability and low latency.

Conflicts between replicas are resolved using a **last-write-wins** rule: every mutation carries a timestamp, and the version with the highest timestamp always wins.

***

## 8. Hinted Handoff & Read Repair

Even with eventual consistency, Cassandra needs mechanisms to actively recover and synchronize replicas that fall behind. The two main ones are **Hinted Handoff** (write-path repair) and **Read Repair** (read-path repair).

### 8.1 Hinted Handoff

When a replica node is **temporarily down** during a write, the coordinator does not simply drop the write. Instead, it stores a **"hint"** — a local record of the missed write — and replays it to the target node once it comes back online.

- **Purpose**: Ensures that a temporarily unavailable node catches up on writes it missed, without requiring a full manual repair.
- **Limitation**: Hints are only stored for a limited time window (default: 3 hours). If a node is down longer than that, hints are discarded and a manual `nodetool repair` is needed instead.

**Beyond the hint window** — `nodetool repair`: For nodes that are down longer than 3 hours, hints are discarded. The operator must manually run nodetool repair, which uses Merkle Trees to compare data between replicas and sync any diverged partitions. This should be run regularly in production — at minimum once every `gc_grace_seconds` period (10 days by default) to prevent data inconsistencies from becoming permanent.

### 8.2 Read Repair

During a read, the coordinator contacts multiple replicas (depending on the Consistency Level) and **compares their responses via digest hashing**. If it detects that replicas disagree on the value of a row, it:

1. Identifies the most recent version using timestamps (last-write-wins)
2. Writes the correct version back to the stale replica(s)
3. Returns the correct value to the client

This happens **transparently** — the client is unaware of the repair. Read Repair can be configured to happen:
- **Synchronously** (`read_repair_chance = 1.0`): repair happens before the response is returned to the client (adds latency)
- **Asynchronously** (default): repair happens in the background after the response is sent

Read Repair and Hinted Handoff together ensure that **short-term inconsistencies self-heal** without manual intervention, which is a core part of how Cassandra maintains eventual consistency in practice.

---

## 9. Quick Reference: Key Concepts

| Concept | Definition |
|---|---|
| **Masterless P2P** | Every node is equal; any node can coordinate any request |
| **Gossip Protocol** | Decentralized node state propagation — each node gossips with 3 random peers every second |
| **Consistent Hashing** | Maps partition keys to nodes via a token ring; minimizes data movement when nodes are added/removed |
| **vNodes** | Each physical node holds 256 token positions for balanced distribution |
| **Replication Factor (RF)** | Number of copies of each piece of data across the cluster |
| **Partition Key** | Determines which node stores the data (via Murmur3 hash) |
| **Clustering Columns** | Determine sort order and row identity within a partition |
| **Denormalization** | Duplicating data across multiple tables to serve different query patterns |
| **LSM-Tree** | Append-only storage model; writes go to CommitLog → MemTable → SSTable |
| **Tombstone** | A write marker for a delete; physically removed during compaction after gc_grace_seconds |
| **Compaction** | Merges SSTables, removes stale data and tombstones |
| **Bloom Filter** | Probabilistic structure on each SSTable to avoid unnecessary disk reads |
| **Upsert Semantics** | Inserting a row with an existing primary key overwrites it (last-write-wins) |
| **Wide-Column Store** | Rows only store populated columns; null columns consume zero bytes |
| **CAP Theorem** | A distributed system can guarantee only 2 of: Consistency, Availability, Partition Tolerance — Cassandra is AP by default |
| **Tunable Consistency** | Per-operation Consistency Level (CL) controlling how many replicas must acknowledge a read/write |
| **Consistency Level (CL)** | `ONE`, `QUORUM`, `LOCAL_QUORUM`, `ALL` — trades latency for consistency guarantees |
| **Strong Consistency Rule** | Write CL + Read CL > RF guarantees a read always returns the latest write |
| **Eventual Consistency** | With low CLs, replicas converge to the same value over time; conflicts resolved by last-write-wins |
| **Hinted Handoff** | Coordinator stores missed writes for a down replica and replays them when it recovers (up to 3h window) |
| **Read Repair** | During a read, stale replicas are detected via digest comparison and silently updated with the latest version |