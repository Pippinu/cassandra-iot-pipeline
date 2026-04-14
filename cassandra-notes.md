# Apache Cassandra

## Core Architecture

Cassandra uses a ***masterless***, ***peer-to-peer*** ***ring*** architecture where all nodes are equal and communicate via a ***gossip protocol***; no single point of failure exists. 

### Cluster
The **Cluster** is the highest-level container in Cassandra, representing the full set of nodes that work together to store and manage your data. 
* **Infrastructure:** It can span across multiple physical data centers (or cloud regions).
* **Communication:** Nodes in a cluster use the **Gossip Protocol** to share state information (which nodes are up, down, or joining).
* **Scalability:** You scale a cluster by adding more nodes, which automatically increases both storage capacity and processing power.

Each node in Cassandra system has three main components:
* **Request coordination over a partitioned dataset**: any node can act as a coordinator for any client request, there is no dedicated master or router node (*masterless*). When a client sends a read or write, the node it connects to becomes the coordinator for that operation. The coordinator is responsible for: 
  * Hashing the partition key to find the token on the ring.
  * Identifying the replica nodes responsible for that token range.
  * Routing the request to the correct replicas.
  * Enforcing Consistency Level and manage the Replication Factor.
* **Ring membership and failure detection**: Cassandra must continuously know which nodes are alive and which are down, this is handled by the ***Gossip Protocol***: 
  * It is the heartbeat protocol through which nodes discover and share state about each other. 
  * Every second, each node initiates a gossip round with up to 3 other nodes, exchanging information about itself and about other nodes it knows of. 
  * Over time, information propagates to the entire cluster without any central coordinator.
* **Local persistence** (storage) engine based in *Log Structured Merge Tree* (LSM) (More below).

### Keyspace
***Keyspace*** is the equivalent of a Database or Schema. However, in Cassandra’s distributed architecture, a keyspace does more than just group tables; it defines how your data is replicated across the cluster. 

Its primary roles include:
* **Logical Grouping**: It acts as a namespace for your tables, types, and functions. You group tables that belong to the same "domain" to keep the database organized.
  * `user_data` Keyspace: Contains `users_by_id`, `users_by_email`, and `user_employment_history`.
  * `analytics_logs` Keyspace: Contains `sensor_errors`, `sensor_heartbeats`, and `request_latency`.
* **Inherited Settings**: Every table within a keyspace **must** follow these global rules:
  * **Replication Factor (RF)**: Defines how many copies of your data exist. For example, RF: 3 means every row is stored on three different nodes.
  * **Replication Strategy**: Determines the physical placement of replicas.
      * *SimpleStrategy*: Used for a single data center.
      * *NetworkTopologyStrategy*: Used for multiple data centers (e.g., 3 copies in "US-East" and 3 in "EU-West").
  * **Durable Writes**: A boolean (default: true) that tells Cassandra whether to use the **Commit Log** for all tables in this keyspace. Disabling this can increase speed but risks data loss during a power failure.

> **Note on Inheritance**: While tables inherit the "where" and "how many" from the Keyspace, they maintain their own "local" settings for **Compaction Strategy**, **Compression**, and **TTL (Time to Live)**.

### Table (*Column-Family*)
A **Table** (historically called a Column Family) defines the typed schema for your data.
* **Schema Definition:** Just like in SQL, you define column names and types (e.g., `text`, `int`, `uuid`).
* **Query-First Design:** Unlike SQL, You do not model for entities; you model specifically to satisfy one query.
* **Flexibility:** While the schema is defined, Cassandra is efficient at storing sparse data (columns that might be empty for many rows).

### Partition
The **Partition** is the fundamental unit of storage and the "atom" of distribution in Cassandra.
* **Grouping:** A partition consists of all rows in a table that share the same **Partition Key**.
* **Physical Location:** While a table is spread across many nodes, a single partition is guaranteed to live on one node (and its replicas). 
* It's the mandatory part of primary key, the optional part are the clustering columns.
* **Performance:** Queries that stay within a single partition are the fastest because Cassandra only has to visit one physical location on disk.

### Partitions and Primary Keys

A Primary Key consists of two parts: the **Partition Key** (mandatory) and **Clustering Columns** (optional).

* **Partition Key:** Determines the data's physical location. All rows sharing the same partition key are stored together in one "physical" chunk.
* **Clustering Columns:** Determine the sort order of the data within that partition and identify rows of the partition.

#### Defining Keys in CQL
Cassandra uses parentheses to distinguish how data is distributed versus how it is sorted.

* **Simple Primary Key**
    ```sql
    PRIMARY KEY (groupname, username)
    ```
    * **Partition Key:** `groupname` (The first element).
    * **Clustering Key:** `username` (Everything else).

* **Composite Partition Key**
    Grouping elements in an inner set of parentheses forces Cassandra to hash them together.
    ```sql
    PRIMARY KEY ((groupname, email), username)
    ```
    * **Partition Key:** `(groupname, email)` (Both are required to locate the partition).
    * **Clustering Key:** `username`.

* **Multiple Clustering Keys**
    When you define multiple clustering columns, you are creating a hierarchy for both **uniqueness** and **searchability**.

    ```sql
    PRIMARY KEY (groupname, join_date, username)
    ```

    * **Partition Key:** `groupname` (Determines the node/location).
    * **Clustering Keys:** `join_date` and `username`.
    * **Sorting Logic:** Data is physically stored in a nested sort order: first by `join_date`, then by `username`.

    **Why use multiple clustering keys?**
    1.  **Granular Identification:** If you only used `join_date` as a clustering key, you could only have one user per date (otherwise, new users would "upsert" and overwrite old ones). 
        -  Adding `username` creates a unique identity for every specific user on that date.
    2.  **Efficient Lookups:** 
        * **With Composite Keys:** You can jump directly to a specific user on a specific date because the full path `(join_date -> username)` is indexed by the storage engine.
        * **Without Composite Keys:** If `username` were just a regular column (not part of the key), Cassandra would have to retrieve *all* users for that `join_date` and scan through them manually to find the one you want.
    3.  **Range Queries:** This structure allows you to perform powerful queries like "Give me all users who joined 'Admins' between January and March, sorted alphabetically by name."

#### Key Constraints & Performance
* **The "First Item" Rule:** Without inner parentheses, the first component is automatically the partition key, and all subsequent components become clustering keys.
* **Querying:** To find data efficiently, the Partition Key is **mandatory** in your `WHERE` clause. Queries that stay within a single partition are the fastest because Cassandra only visits one physical location on disk.
* **Order Matters:** Clustering columns must be queried in the order they are defined. You cannot skip `join_date` to filter by `username` without performance penalties.

### Row
The **Row** is the smallest unit of data in a table.

* **Identification:** A row is uniquely identified within its partition by its **Clustering Columns**. 
    * While the **Partition Key** determines the physical location (which node), the **Clustering Columns** act as the specific "ID" that distinguishes one row from another within that shared partition.
* **Dual Role of Clustering Columns:** They serve two purposes simultaneously:
    1.  **Identity:** They define what makes a record unique.
    2.  **Ordering:** They determine the physical sort order of data on the disk.
* **Storage Logic:** 
    * **Partitions** are distributed across the cluster (usually randomly via hashing).
    * **Rows** *inside* a partition are stored in a strict sorted order based on the clustering columns (in the order they were defined in the Primary Key).
* **Upsert Behavior:** Because the clustering columns define the row's identity, inserting a row with an existing Partition Key + Clustering Key combination will not create a duplicate; it will update (overwrite) the existing row.

### Schema Philosophy: Wide-Column vs. Relational

In a traditional **RDBMS**, the schema is a **contract for storage**. The database engine must know the exact byte-offset of every column to navigate a row. This creates "dense" storage where even empty cells occupy space.

In **Cassandra**, the schema is a **contract for the application**. It exists to provide metadata and validation for the CQL engine, but the underlying storage engine treats data far more flexibly.

#### The Wide-Column Advantage
Cassandra is a **Wide-Column Store**. Unlike an RDBMS where every row must have the same "narrow" set of columns, a single Cassandra partition can contain millions of columns.
* **Sparse Storage:** Two rows in the same table can have entirely different sets of populated columns.
* **Zero-Cost Nulls:** Thanks to the **LSM-Tree** storage engine, "null" cells are simply not written to disk. If a column has no value, it consumes **zero bytes**, unlike the fixed-width overhead in traditional databases.

> **Analogy:** An **RDBMS** is like a pre-printed tax form with fixed boxes you *must* fill; **Cassandra** is like a blank notebook where you only write down the headers for the information you actually have.

---

#### Comparison of Schema Enforcement

While often categorized under "NoSQL," the way schemalessness or flexibility is handled varies significantly across database types:

| Feature | **Document Store** (e.g., MongoDB) | **Wide-Column Store** (e.g., Cassandra) | **Relational** (e.g., PostgreSQL) |
| :--- | :--- | :--- | :--- |
| **Schema Style** | **Schema-on-Read**: Data is stored as flexible, self-describing JSON/BSON blobs. | **Schema-on-Write**: A schema is defined, but storage is sparse (nulls are non-existent on disk). | **Strict Schema**: Fixed-width rows; every row must strictly match the table definition. |
| **Enforcement** | **Application Level**: The code manages the structure; the DB accepts almost any key-value pair. | **Metadata Level**: The DB validates against allowed columns, but rows are stored independently. | **Database Level**: Strict constraints, data types, and foreign keys are enforced at the core. |
| **Storage Logic** | **Self-Describing**: Every individual record stores its own field names (e.g., `"name": "Alice"`). | **Cell-Based**: Only populated columns are stored as individual cells (Key:Value:Timestamp). | **Row-Based**: Reserves physical disk space for every column in the schema for every row. |
| **Flexibility** | **Infinite**: Every document in a collection can have completely different fields. | **High**: Tables can support massive numbers of columns; rows only "pay" for what they use. | **Low**: Structural changes (adding columns) often require heavy migrations or table locks. |
| **Best Use Case** | Rapid prototyping and unpredictable, nested data structures. | **Massive scale**, high-velocity writes, and predictable, query-driven access. | Complex relationships, financial integrity (ACID), and ad-hoc analytical reporting. |

---

### The Full Hierarchy: Putting it all together

1.  **Cluster:** The entire fleet of nodes.
2.  **Keyspace:** The "bucket" that defines how many copies of the data exist and which data centers they live in.
3.  **Table:** The structure (schema) of the data.
4.  **Partition:** The group of rows living on a specific node (determined by the **Partition Key**).
5.  **Row:** The individual record.

---

### Key concepts:
* **Masterless, P2P Architecture:**
  * *Masterless*: Every node is a "coordinator" which can process read/write requests.
  * *Fault Tolerance*: No single node controls the others, so the system stays up even if several nodes fail.
* **Ring Architecture & Tokens:**
  * *Tokens*: Every node is assigned a range of tokens (a numerical range).
  * *Hashing*: The Partition Key is hashed into a token to determine which node in the "ring" owns that data.
  * *Virtual Nodes (vNodes)*: A physical node can represent multiple "virtual" nodes to ensure data is spread more evenly.
* **Gossip Protocol:** * The decentralized way nodes "talk" to each other to share health and location info without a central manager.
* **Replication vs. Partitioning:** 
  * *Partitioning* splits the data up (so it fits on many machines).
  * *Replication* copies the data (so it isn't lost if one machine dies).

## Data Model Basics

Data organizes into:
* Keyspaces (like databases, defining replication)
* Tables (wide rows with flexible schemas)
* Partitions (groups of rows sharing a partition key)
* Rows (identified by primary key: partition key + optional clustering keys)
* Columns (typed data). 

Unlike relational models' fixed schemas and normalized tables, Cassandra's wide-column store supports dynamic columns and denormalization for query efficiency. Tables can grow to billions of columns per row with zero-downtime additions.

### *Query-first* Data Modeling

Data in Cassandra is stored in separate tables tailored to each query pattern, with all required columns duplicated (denormalized) in each relevant table to enable fast, join-free reads. 
* For your IoT example—Query 1 (Venice temps on 2025-03-31) and Query 2 (temps + humidity/weather/coords)—you create two tables like sensor_by_city_date and sensor_details_by_city_date, both storing the full sensor data but optimized differently. 
* The original raw data might come from a **single ingestion table**, but gets copied into these query-specific ones at write time.
* Cassandra explicitly chooses **NOT** to implement operations that require **cross-partition coordination** as they are typically slow. 

What happens when the requirements change, so the original table is not enough and a join betweem more tables is required?:

1. Client-Side Joins (The "Brute Force" Way)
    
    If you need data from `sensor_events` and `hourly_aggregates` and they aren't in the same table, your application code performs two separate queries and merges the results in memory.

    * **When to use:** When the dataset is small or the query is rare.
    * **The Downside:** It’s slow. You lose the "distributed" benefit because your application server becomes a bottleneck, waiting for multiple round-trips to the database.

2. Create a New Table (The "Cassandra" Way)
   
   In a professional environment, if a new query becomes a requirement (e.g., "We now need to query by sensor manufacturer"), the standard practice is to **create a new table** specifically for that query.

   * **The Workflow:**
       1.  Create the new table.
       2.  Write a script (or use a tool like Spark) to backfill the new table with historical data.
       3.  Update your application to write incoming data to **both** tables simultaneously.
   * **The Philosophy:** Storage is cheap; CPU cycles and user patience (latency) are expensive.

3. Materialized Views (The "Automated" Way)

    Cassandra has a feature called **Materialized Views (MV)**. You define a "view" based on a base table but with a different Primary Key. Cassandra then handles the job of automatically copying data from the base table to the view.

    * **The Catch:** They come with significant performance overhead and "eventual consistency" issues, they can be "brittle" if a node fails.

#### Example Tables

For ingestion (raw IoT writes), all fields together:

```sql
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
```

For Query 1 (city/date temps):

```sql
CREATE TABLE temps_by_city_date (
    city TEXT,
    date DATE,
    sensor_id UUID,
    timestamp TIMESTAMP,
    temperature FLOAT,  -- Duplicated
    PRIMARY KEY ((city, date), timestamp)
);
```

```sql
SELECT temperature FROM temps_by_city_date WHERE city='Venice' AND date='2025-03-31';
```

For Query 2, Includes everything; data duplicated from ingestion:

```sql
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

Cassandra's denormalization intentionally duplicates data across query-specific tables to **boost write and read throughput**, at the **cost of increased storage usage**. Writes scatter across distributed tables via log-structured appends (CommitLog + MemTables), achieving 10k–50k ops/sec per node without locks or joins, while reads hit optimized, single-partition tables for sub-ms latency.

### Understanding Cassandra’s "Baked-In" Indexing

In Cassandra, indexing isn't an afterthought—it is physically woven into how data is stored. Unlike a traditional Relational Database (RDBMS) where an index is a separate "side-table," Cassandra uses the **Primary Key** to define both the physical location and the sort order of data on the disk.

#### 1. The Primary Key: Partition vs. Clustering
A Primary Key in Cassandra is composed of two distinct parts that dictate the data's lifecycle:

* **Partition Key (The "Where"):** This is the first part of the Primary Key. Cassandra runs this value through a **Murmur3 Hash function** to generate a "Token." This token determines which specific **Node** in the cluster owns the data. 
    * *Concept:* Many different partition keys will hash to the same node, but all rows sharing the exact same partition key are stored together in a single physical "folder" (partition).
* **Clustering Columns (The "How"):** These are the remaining columns in the Primary Key. They determine the **physical sort order** of rows inside a single partition.

#### 2. Physical Column Ordering & Constraints
The sort order in Cassandra is "baked-in" at the moment data is written to the disk. Using the `WITH CLUSTERING ORDER BY` clause during table creation tells the system exactly how to arrange the bytes.

* **Sequential Disk Access:** Because data is physically sorted, Cassandra can perform "range scans" (e.g., getting the last 10 messages) by reading a contiguous chunk of the disk. This avoids the "random seek" penalty that slows down traditional databases.
* **The "Sort" Constraint:** You can only sort by columns defined as Clustering Columns. Because the order is physical, Cassandra cannot efficiently "re-sort" data at runtime. If you need a different sort order, you typically create a second table designed for that specific query.

#### 3. The "Query-First" Rule (Denormalization)
The most important takeaway for Cassandra indexing is that you must **model your tables around your queries**. 
* In SQL, you can "fix" a slow query by adding a Secondary Index later. 
* In Cassandra, Secondary Indexes on high-cardinality data (like a specific User ID or Email) are often a performance trap. Because Cassandra is distributed, a secondary index query might force the system to check every node in the cluster (a "scatter-gather" operation). 
* **Best Practice:** If you need to search by a different column, create a new table where that column is the Partition Key. This "denormalization" trades cheap disk space for lightning-fast read speeds.

### Dataset Partitioning: Consistent Hashing

Cassandra achieves horizontal scalability by **partitioning** all data stored in the system using a hash function. Each partition is replicated to multiple physical nodes, often across failure domains such as racks and even datacenters. As every replica can independently accept mutations to every key that it owns, every key must be versioned. Unlike in the original Dynamo paper where deterministic versions and vector clocks were used to reconcile concurrent updates to a key, Cassandra uses a simpler ***last-write-wins*** model where every mutation is timestamped (including deletes) and then the latest version of data is the "winning" value. 

***Consistent hashing*** is the mechanism Cassandra uses to decide which node(s) in the cluster are responsible for storing a given piece of data, and to do so in a way that minimizes disruption when the cluster grows or shrinks.

#### The Problem with Naive Hashing

In a naive approach, you'd assign data to nodes by computing `hash(key) % number_of_nodes`. 
* This works fine until you add or remove a node: changing the number of nodes invalidates almost every mapping, forcing a massive redistribution of data across the cluster.  For a large distributed system, this is unacceptable. 

#### The Token Ring

Consistent hashing solves this by placing both **nodes** and **data keys** on the same continuous circular hash ring (token ring).  
* The ring represents the full output space of the hash function. Each node is assigned one or more **tokens**—specific positions on this ring. 
* When data is written, its partition key is hashed to a position on the ring, and that data is stored on the **$RF-1$ node encountered walking clockwise** from that position, depending on the replication factor (RF).

#### Adding/Removing Nodes

When a node joins or leaves, **only a small fraction of keys need to move**—specifically, only the keys in the range that the new node takes over.  Every other node's data is unaffected. This is the core advantage over naive hashing.

#### Virtual Nodes (Vnodes)

Early Cassandra assigned each physical node **one token** (one position on the ring), which caused uneven data distribution—especially when nodes had different capacities or when one node failed.  

Modern Cassandra uses **virtual nodes (vnodes)**: each physical node is assigned **many tokens** (256 by default), scattering it across many small arcs of the ring simultaneously.  This achieves:
- More **uniform data distribution** across nodes
- **Faster rebalancing** when a node is added/removed (many small chunks move rather than one large one)
- **Better fault tolerance** (a failing node's load spreads across all remaining nodes, not just its neighbors)

#### Replication

When Cassandra needs to replicate data (e.g., replication factor RF=3), it hashes the key to its primary owner, then **scans clockwise** to find 2 additional vnodes on **different physical nodes** to store replicas.  
* It **deliberately skips vnodes on the same physical machine** so that a single hardware failure doesn't take down multiple replicas.

### Key concepts:
* wide-column database
  * dynamic columns, denormalization for query efficiency
* keyspace
* tables
  * created around anticipated queries to avoid complex joins
  * denormalized data
* rows
* columns

## LSM-tree Cassandra Storage Engine

Cassandra's storage engine is built around a **Log-Structured Merge-Tree (LSM-tree)** architecture, optimized for high-throughput, write-intensive workloads. Unlike relational databases that use B-trees with random disk I/O, Cassandra uses an append-only model that eliminates read lookups from the write path entirely.

### The Write Path

Every write follows a precise sequence of steps on each replica node:

1. **CommitLog** (durability): The write is immediately appended to the CommitLog, an append-only on-disk log. This guarantees that even if the node crashes before anything else happens, the write can be recovered on restart. The node considers the write durable once it hits the CommitLog.

2. **MemTable** (in-memory buffer): Simultaneously, the data is written to the MemTable—an in-memory sorted data structure, one per table. Data here is immediately queryable. Writes in the MemTable are sorted by partition key for efficient merging later.

3. **Flush to SSTable** (disk persistence): When the MemTable reaches a configurable size threshold, or the CommitLog approaches its max size, the MemTable is flushed to disk as an **SSTable** (Sorted String Table). Once flushed, the MemTable is discarded and the corresponding CommitLog segment can be truncated.


### SSTables

SSTables (Sorted String Tables) are **immutable** on-disk files. Once written, they are never modified. This is crucial: updates and deletes are not in-place operations. An update just writes a new version with a newer timestamp; a delete writes a special marker called a **tombstone**. At read time, Cassandra merges versions and picks the most recent one.

Each SSTable on disk is accompanied by several auxiliary structures:
- **Index file**: maps partition keys to their byte offset within the SSTable for fast access
- **Bloom filter**: a probabilistic in-memory structure that answers "is this partition key in this SSTable?" without reading the file—false positives are possible but false negatives are not, so it reliably avoids unnecessary disk reads
- **Summary/Compression info**: metadata about block sizes and compression

### The Read Path

A read on a single node proceeds as follows:

1. Check the **MemTable** (most recent writes are here)
2. Check the **row cache** (if enabled)
3. Check **Bloom filters** for each SSTable on disk to skip irrelevant ones
4. Check the **key cache / partition index** to find exact byte offset
5. Read from the relevant SSTable(s) on disk
6. **Merge** results from MemTable and all relevant SSTables, using timestamps to resolve conflicts and tombstones to suppress deletes

This is why reads in Cassandra are slightly more complex than writes—data for the same partition could be spread across multiple SSTables over time.

### Compaction

Since SSTables accumulate over time (immutable, never updated in-place), Cassandra periodically runs **compaction**: it merges multiple SSTables into one, discarding outdated versions of records and expired tombstones. This:
- Reduces the number of SSTables a read must consult
- Reclaims disk space from stale data
- Improves read performance at the cost of temporary write amplification (rewriting data)

The three main compaction strategies are:
- **SizeTieredCompactionStrategy (STCS)**: default, merges SSTables of similar size—good for write-heavy workloads
- **LeveledCompactionStrategy (LCS)**: organizes SSTables into levels, better read performance, higher write overhead—good for read-heavy workloads
- **TimeWindowCompactionStrategy (TWCS)**: groups SSTables by time window—ideal for time-series/IoT data

### Tombstones

Deletes in Cassandra do not remove data immediately. Instead, a **tombstone** marker is written with a timestamp. During compaction, tombstones suppress the deleted data and are eventually discarded after the **gc_grace_seconds** period (default 10 days). This delay ensures that deleted data doesn't "resurrect" on nodes that were temporarily down and missed the delete. Accumulated tombstones before compaction can degrade read performance—a critical operational concern.

### Key Concepts Summary
- **LSM-tree**: append-only, no random writes, high throughput
- **CommitLog**: write-ahead log for crash recovery
- **MemTable**: in-memory sorted write buffer, one per table
- **SSTable**: immutable sorted on-disk file, result of MemTable flush
- **Bloom filter**: probabilistic structure to avoid unnecessary disk reads
- **Compaction**: merges SSTables, discards stale/deleted data
- **Tombstone**: write marker for deletes, cleaned up during compaction

## Key Differences from RDBMS

Cassandra employs a query-first design: model tables around anticipated queries, not entity relationships, leading to denormalized data duplication. It lacks joins, foreign keys, referential integrity, and cross-partition transactions to ensure high performance and availability. Relational databases normalize data with ACID guarantees and support complex joins, but this hinders scalability for high-throughput apps.

Without joins or transactions, Cassandra avoids RDBMS' costly operations, delivering sub-millisecond reads on denormalized tables even at petabyte scale. RDBMS joins normalize across tables but scale poorly for high-throughput writes/reads; Cassandra's materialization pre-computes query results at write time.

Most relational databases:
* Do not have distributed architechture build in their core architecture. Most of them generally have a separate cluster version and their default versions do not support clustering out of the box.
* Most of them function in ***Master-Slave* configuration** which leads to single point of failure of master OR performance degradation as all writes happens to master nodes and is replicated to slave nodes.
* Additionally there is lot of overhead involved in setting up the clusters, maintaining it and to ensure that there is no single point of failure in such clusters.

| Aspect        | Cassandra                                       | Relational DB (e.g., PostgreSQL)         |
| ------------- | ----------------------------------------------- | ---------------------------------------- |
| Schema        | Flexible, dynamic columns      | Fixed, enforced swiftorial               |
| Normalization | Denormalized, duplicated data  | Normalized with joins             |
| Queries       | Partition-key driven, no joins | SQL joins, transactions |
| Scaling       | Horizontal, add nodes          | Vertical, sharding add-ons      |
| Consistency   | Eventual, tunable              | Strong ACID                 |

### Key concepts:
* query-first design
* no joins, FK, ref. integrity
* eventual and tunable ACID
* master-slave vs P2P, integrated cluster architecture (cassandra)

## TODO

- **Query-First Data Modeling**: How tables are designed around specific queries (not entities), denormalization/duplication, handling new queries (new tables vs. materialized views vs. client joins), IoT examples with partition/clustering keys.
- **Data Model Components**: Keyspaces, tables (wide rows), partitions, rows, primary keys (partition + clustering), dynamic columns, SSTables/MemTables/CommitLog write path.
- **Core Architecture**: Masterless P2P ring, gossip protocol, consistent hashing (tokens, vnodes), linear horizontal scaling vs. RDBMS vertical/master-slave.
- **RDBMS Differences**: No joins/FK/referential integrity, denormalized vs. normalized, eventual/tunable consistency vs. ACID, integrated clustering.
- **Performance Tradeoffs**: High write/read throughput from append-only/log-structured storage, storage overhead from duplication/replication, compaction/compression mitigations.
- **Handling Schema Evolution**: Backfilling for new tables, dual writes, materialized views limitations (overhead, brittleness).