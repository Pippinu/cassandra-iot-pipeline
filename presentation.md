# Cassandra for IoT Streaming Analytics: Presentation

## Slide 1: Introduction

This project implements an end‑to‑end Kafka–Spark–Cassandra pipeline, but the main focus is on Cassandra’s characteristics rather than on Kafka or Spark. We simulate an IoT scenario with three types of sensors (power, light, and temperature/humidity) deployed in three different rooms identified as room_A, room_B, and room_C.

- A Python script continuously simulates sensor readings and publishes them as JSON messages to Kafka, using three topics, one per sensor type. 
- Spark Structured Streaming reads from these topics, parses the messages, and then plays three roles: 
  - it writes the raw events into Cassandra, 
  - it enriches some streams on the fly with derived values (for example, computing wattage from voltage and amperage), and
  - it periodically computes statistics over time windows while checking for abnormal readings and generating alerts.
- Cassandra acts as the storage layer for all of this, ingesting a continuous stream of events and persisting both raw data and derived tables such as aggregates and alerts. 

In the demo we ingest around 90 messages per second into a three‑node cluster, which is **intentionally small** compared to **Cassandra’s real write capacity**; the goal is to showcase how the data model, the schema, and the newer features (like modern wide‑row modeling and advanced indexing) support IoT streaming analytics rather than to stress‑test throughput.

## Slide 2: Why Cassandra for IoT Streaming Analytics?

Cassandra has several architectural properties that make it a strong fit for this kind of IoT streaming application.

- First, Cassandra uses a fully **distributed peer‑to‑peer architecture**. All nodes are equal: there is no single master, and any node can act as the coordinator for read and write requests. This removes single points of failure and lets the cluster balance load naturally.

- Second, Cassandra is designed for **very high write throughput**. Its log‑structured storage engine and append‑optimized write path make it well suited for continuous streams of sensor data, where new events are constantly being appended rather than updated in place.

- Third, the system is built to **scale horizontally**. When load or data volume grows, we add more nodes to the cluster instead of trying to make a single machine more powerful. Data is automatically partitioned and replicated across nodes, so capacity and throughput can grow roughly linearly with cluster size.

- From a CAP perspective, Cassandra is an **AP‑leaning** system: it is designed to remain available and tolerant to network partitions, even if that sometimes means reads may briefly see slightly stale data. However, it introduces the idea of **tunable consistency**: for each read or write query we can choose the consistency level (for example ONE, QUORUM, or ALL), allowing us to trade off latency and availability against how up‑to‑date we need the data to be. Cassandra was inspired by systems like **Amazon Dynamo** and **Google Bigtable**, combining Dynamo’s AP design with a structured, table‑oriented data model.

- Finally, Cassandra’s **wide‑row, sparse‑column** storage model fits sensor workloads very well. Tables can be highly sparse without wasting disk space, and rows within a partition are physically ordered by clustering keys (for example by timestamp). This means we can store many heterogeneous sensor readings in the same partition and still read ordered time ranges very efficiently, which is ideal for time‑series and IoT analytics.

In the following slides we will dive into each of these properties in more detail and connect them directly to our IoT use case, so that it is clear why Cassandra is a good choice for this scenario.

## Slide 3: Cassandra’s Distributed Architecture

Cassandra clusters use a fully distributed peer‑to‑peer architecture. This has several important consequences for how the system behaves and why it avoids single points of failure.

- Unlike master–slave architectures (such as classic HDFS or systems with a single primary node), Cassandra has **no central master** that owns all write operations while other nodes only store data or serve reads. All nodes share the same responsibilities.

- Any node in the cluster can act as a **coordinator** for a client request. A client can connect to any node; that node will become the coordinator for that query, route writes to the replicas that own the relevant partitions, or gather read results from the replica nodes and merge them before replying to the client.

- Nodes maintain an up‑to‑date view of the cluster using the **gossip protocol**. Each node periodically exchanges small state messages with a subset of other nodes, and this information propagates transitively through the cluster. Over time, every node learns which peers are up, down, or overloaded, enabling robust routing and failure detection without a central metadata service.

- Because of this peer‑to‑peer design, the cluster is **fully decentralized**: there is no single bottleneck or single point of failure at the topology level. If one node crashes or becomes unreachable, other nodes continue serving reads and writes, as long as the replication factor and chosen consistency levels allow it. This is a sharp contrast with master–slave designs (for example, a MongoDB primary in a replica set), where a primary failure temporarily forces a failover procedure and may put the system in read‑only mode during leader election.


### DEMO 1.

At this point in the demo, it is natural to show how this looks in practice. 
1. First, running `nodetool status` on any node demonstrates that each node has the same view of the cluster and there is no special “master” node. 
2. Then, by enabling `TRACING ON` in `cqlsh` and running the same query from different nodes, we can observe that whichever node the client connects to becomes the coordinator for that request, confirming that all nodes are equal peers in the architecture.

## Slide 4: Data Paritioning and Replication, Hash Ring and Virtual Nodes.

For **data partitioning and replication**, Cassandra follows the same core ideas described in the **Amazon Dynamo** paper. 
- The cluster defines a **circular space of hash values**, the ***token ring***, which is split into ranges. Each token range is assigned to a node in the cluster. 
- Each Cassandra table is physically divided into partitions based on the **partition key**: for every distinct partition key value we compute a hash (in modern Cassandra, using the Murmur3 partitioner). 
- This hash maps to a token on the ring; the node that owns the corresponding token range becomes the primary replica, and then, moving clockwise around the ring, additional nodes are chosen as replicas according to the keyspace’s replication factor.

**Demo 2.1**: In our demo cluster we have 3 nodes and a replication factor RF=2 for keyspaces like `iot_raw` and `iot_analytics`, so for each partition key Cassandra stores two copies of the data: one on the node whose token range contains the hash, and the second on the next node clockwise. The important point is that the **ring is global to the cluster**: all keyspaces share the same token ranges and vnode layout. What changes per keyspace is only “how many” replicas we place on those tokens and in which datacenters, not the token ownership itself.

To avoid skew where one physical node would own one large, continuous slice of the ring, Cassandra uses **virtual nodes (vnodes)**. 
- Instead of assigning one big token range per physical node, each node is assigned many small, non-contiguous token ranges spread around the entire ring. 
- This evens out the load and makes it easier to add or remove nodes, because each node holds multiple small slices instead of one huge slice.

**Demo 2.2**: At this point in the demo, we can tie the theory to the live cluster. Running `nodetool ring iot_raw` shows, for each node, which token ranges it owns and what percentage of the token space that represents; the percentages across all nodes sum to roughly 100% for a single replica of the ring. If all non‑system keyspaces share the same replication strategy and replication factor, you will see the same token ownership percentages when running `nodetool ring` for each of them, because the ring itself is a physical property of the cluster, not of a specific keyspace.

If we then change the replication settings for some keyspaces (for example, RF=3 for `iot_alerts` vs RF=2 for `iot_raw` and `iot_analytics`), `nodetool status` no longer shows a single meaningful “Owns” percentage per node. Cassandra prints “?” for ownership and warns that non‑system keyspaces do not share the same replication settings, so a single aggregate ownership value per node would be misleading. In that situation, `nodetool ring` still lists the same tokens per node (the ring layout did not change), but the **effective data placement** per keyspace is different: RF=3 means every partition is stored on all three nodes, whereas RF=2 means each partition is stored on exactly two nodes, even though both keyspaces use the same token map.

## Slide 5: Critical feature: Partition Key.

The partition key is one of the most critical concepts in Cassandra’s data model. Every table’s **PRIMARY KEY** is split into two parts: the **partition key** (mandatory, one or more columns) and the **clustering columns** (optional, one or more columns). The partition key drives several fundamental behaviors:

- **Data placement across nodes.** For each distinct partition key value, Cassandra computes a Murmur3 hash and uses it to find the token range that owns that partition on the ring. This determines which nodes will store the replicas for that partition, based on the keyspace’s replication factor.

- **Physical row grouping.** All rows that share the same partition key are stored together in a single partition on disk. Within a partition, rows are physically ordered by the clustering columns. This means that rows with the same partition key are not just logically grouped; they are literally written contiguously in SSTables, which is ideal for time‑series scans by timestamp.

- **Efficient reads and writes.** Because the partition key routes a query directly to the node(s) that own the data, Cassandra avoids scatter‑gather operations across the whole cluster. Writes are append‑oriented: even an update is written as a new version, with the old data eventually removed during compaction via tombstones. Sequential appends plus localized partition reads make both write throughput and range reads very efficient.

- **Load balancing and partition size.** The partition key also controls how data is distributed and how large each partition becomes. A poor key choice can cause either:
  - **Too many tiny partitions** (for example, partitioning by a highly variable field like temperature or humidity in this project), which increases overhead and can hurt performance, or
  - **Very large “hot” partitions** (for example, using only `date` as partition key in a scenario with hundreds or thousands of writes per second), where a single partition accumulates a huge number of rows and becomes a hotspot.

In our schema, the partition keys are chosen to avoid both extremes. For example, in `temphumiditybysensor` we use `(sensorid, date)` as the partition key, which naturally caps each partition to “one sensor per day” and spreads data evenly across the ring.

In the demo, this can be visualized in two steps. 

- **Demo 2.3**: First, within keyspace `iot_raw`, we inspect partition statistics and observe that the “Compacted partition minimum bytes” and “Compacted partition maximum bytes” are in the same order of magnitude across the tables, indicating that the chosen partition keys produce reasonably balanced partition sizes.
- **Demo 3**: Second, we start a fourth node and watch what happens when the cluster scales out: with RF=2 for `iot_raw` and RF=3 for `iot_alerts`, Cassandra **automatically rebalances** token ranges and moves only a subset of partitions to the new node, while preserving the requested replication factors for each keyspace.

## Slide 6-9 Quick Recap

- Cassandra clusters use a fully distributed peer‑to‑peer architecture with no single master node. Any node can coordinate reads and writes, and all nodes share the same responsibilities. This design eliminates single points of failure and allows for robust load balancing.
- Keyspaces in Cassandra define replication settings, but the underlying token ring and vnode layout are shared across the cluster. This means that all keyspaces use the same physical partitioning of data, even if they have different replication factors.
- Tables in Cassandra are defined with a PRIMARY KEY that includes a partition key and optional clustering columns. The partition key determines data placement across nodes, physical grouping of rows, and read/write efficiency. Choosing the right partition key is critical to avoid hotspots or too many tiny partitions.
- Primary key design is crucial in Cassandra. The partition key controls how data is distributed and accessed, while clustering columns determine the physical order of rows within a partition. Properly designing the primary key based on query patterns and data distribution is essential for achieving good performance in Cassandra.

## Slide 10: Query‑First Modeling in Cassandra

In Cassandra we do not start from an entity‑relationship model and then let a query planner figure out joins at read time. Instead, we start from the **queries we know we must support** and design one table per access pattern so that each query can be served by a single partition scan without joins.

This is very different from a relational mindset. In an RDBMS we usually normalize data into many tables and then reconstruct views using JOINs and ad‑hoc queries; the system does a lot of work at read time to combine data. In Cassandra there are **no JOINs at all**, and data is distributed by partition key across nodes, so a “random” query that touches many partitions would be very expensive. To avoid that, we **pre‑join and pre‑aggregate at write time**, denormalizing the same logical event into multiple tables, each optimized for one specific query shape.

In this project the same sensor reading is intentionally written into several tables: for example, a temperature‑humidity event goes into `temphumiditybysensor` (to read by sensor and date) and into `readingsbylocation` (to read all activity in a room on a given day). These are not redundant copies in the relational sense; they are separate, query‑oriented views of the same event. The cost we pay is extra writes and some duplication, but in return we get extremely fast, predictable reads at large scale, which is exactly what we need for high‑throughput IoT analytics.

## Slide 11: iot_raw Keyspace – Raw Event Tables

The `iot_raw` keyspace contains the raw per‑sensor event tables used as the write‑heavy landing zone for the pipeline. These tables are continuously written by Spark but are rarely updated or read directly by end‑users; they mainly serve as the immutable history from which other views and analytics are derived.

We have three per‑sensor tables, one for each sensor type (`temp_humidity_by_sensor`, `light_by_sensor`, `power_by_sensor`), plus a location‑centric table `readings_by_location` and the `devices_metadata` table for sensor reference data. Almost all columns in these tables come directly from the Python simulator’s JSON messages, with one important exception: `wattage` in `power_by_sensor` and `readings_by_location` is **not** produced by the producer; it is computed on the fly by Spark as `voltage * amperage` before being written. These raw tables are optimized for sustained high‑volume writes, using time‑bucketed partition keys and compaction strategies that favor ingestion throughput over complex reads.

## Slides 12–13: Wide, Sparse Rows and the LSM Storage Engine

The `readings_by_location` table is intentionally modeled as a wide, sparse table. The partition key is `(location_id, date)`, so all sensor readings for a room on a given day live together in one partition, ordered by `timestamp` and `sensor_id`. Within that partition, rows for different sensor types only populate the columns that make sense for that type: temperature/humidity rows fill `temperature` and `humidity`, light rows fill `light_level`, and power rows fill `voltage`, `amperage`, and `wattage`. The other columns are simply absent.

This is where Cassandra’s storage model really differs from a traditional RDBMS. In a row‑oriented relational database, defining a wide table with many columns usually means allocating space for all columns in every row, even when many cells are NULL. In Cassandra, thanks to its log‑structured merge‑tree (LSM) storage engine, only the columns that actually have values are written to disk. “Null” in this context usually means “no cell at all”: the column is not stored, so it consumes zero disk space. That is what makes wide, sparse tables like `readings_by_location` practical and efficient for mixed‑type IoT workloads.

**Slide 13** goes one level deeper and explains how the LSM engine makes high‑volume writes efficient. Every write first appends to the **commit log** for durability and then goes into an in‑memory **memtable**, where rows are kept in sorted order by partition key and clustering columns. When a memtable fills up, it is flushed to disk as an immutable **SSTable**. Over time, background **compaction** merges multiple SSTables, discards obsolete versions and tombstoned data, and keeps the on‑disk structure optimized. This design turns random updates into sequential writes and works very well with sparse, wide partitions: the engine only stores the columns that are present and can handle a constant stream of appends without fragmenting the storage.

## Slide 14: Metadata and Operational Alerts

This slide shows that Cassandra in the project is not only a sink for raw events, but also a store for reference data and live operational signals.

The `devices_metadata` table holds slowly changing reference information for each sensor (its type, which room it belongs to, and a human‑readable description). This gives context to raw readings and can be joined in the application layer or notebook to label graphs and alerts with meaningful names instead of just UUIDs. Because this data is read much more often than it is written, the table is modeled and tuned as a read‑optimized lookup.

The `sensor_alerts` and `alerts_by_location` tables are the outputs of the streaming analytics and alerting logic. Spark examines raw readings, detects threshold violations (for example, very high humidity or wattage), and writes structured alert rows into Cassandra. `sensor_alerts` is keyed by `sensor_id` and `timestamp`, which is ideal for “show me recent alerts for this sensor”, while `alerts_by_location` groups alerts by `(location_id, date)` so we can efficiently answer questions like “which alerts fired in room_A today?”. Together, these tables make Cassandra a single place where both the raw signals and the alert decisions are persisted for real‑time monitoring.

## Slide 15: Analytics Tables – Precomputed Aggregates

The `iot_analytics` keyspace contains tables that store precomputed aggregates produced by Spark, bridging raw event data and fast analytical queries. Instead of running expensive aggregations at query time, Spark continuously reads raw streams from Kafka/Cassandra, computes statistics over fixed windows, and writes the results into denormalized tables. In this project, `sensor_aggregates_30s` stores 30‑second window statistics per sensor (average, min, max, count), while `aggregatesbytype` stores 30‑second averages grouped by sensor type and location. This design follows the query‑first modeling idea: each table is built to answer a specific analytical question directly (“trend for sensor X over time” vs “how are all humidity sensors behaving today?”) with a single efficient partition scan.

---

## Slide 16: From Legacy Indexes to SAI

Older Cassandra versions offered **global secondary indexes**, which were often **problematic** in distributed environments: index data was **scattered** across the cluster, high‑cardinality or wide‑range queries could trigger cluster‑wide lookups, and maintaining index consistency added significant **write overhead**. 

Cassandra 5 introduces ***Storage‑Attached Indexes*** (**SAI**), which are local to each node and tightly integrated with the LSM storage engine. 
- With SAI, index data lives alongside the SSTables it indexes, so queries on non‑primary‑key columns can be resolved locally on each replica without extra cluster fan‑out provided that the partition key is included in the query. 
- This enables efficient equality and range filtering on columns like `humidity` in `readings_by_location` or `location_id` in alerts tables, dramatically expanding the practical query patterns without abandoning Cassandra’s write‑optimized nature.

---

## Slides 17–19: Vector Search and Behavior Profiles

Cassandra 5 goes beyond scalar indexes and adds native support for vector types and ***approximate nearest neighbor*** (**ANN**) ***search***, which is particularly relevant in the current AI era. 
- In the project, sensor behavior is summarized over a recent time window into a small 3‑dimensional vector (`mean_value`, `variance_value`, `spike_count`) for each sensor, and stored in the `sensor_behavior_profiles` table, keyed by (`location_id`, `sensor_type`, `sensor_id`). 
- This table groups “peer sensors” (same room, same sensor type) in the same partition and attaches a behavior vector to each one.

On top of this, Cassandra can run vector similarity queries like “in room_A, among power sensors, find the k sensors whose behavior vector is closest to this anomalous profile.” In low‑dimensional cases like this demo, the similarity is easy to understand; Cassandra’s ANN support becomes critical when vectors become high‑dimensional embeddings. The key point is that vector search follows the same modeling principles: the partition key still scopes similarity to the right peer group, and vector indexing/search is layered on top without changing the core distributed architecture.

---

## Slide 21: Where Cassandra Fits Among Databases

This slide compares Cassandra to other common database families to highlight its niche. Compared to relational databases like PostgreSQL, Cassandra trades complex joins and ACID transactions for linear scale‑out, AP‑leaning availability, and very high write throughput, making it better suited for time‑series and IoT event streams than for ad‑hoc OLTP queries. Compared to document stores like MongoDB, Cassandra uses a stricter, query‑driven table model with predictable performance at massive scale and multi‑datacenter, active‑active deployments, but is less convenient for deeply nested, frequently changing document structures. Against key‑value stores like DynamoDB, Cassandra offers similar scalability and low‑latency access, but as an open‑source, self‑managed option suitable for multi‑cloud or on‑prem environments where avoiding vendor lock‑in and tuning internals is important. The project sits exactly in Cassandra’s sweet spot: high‑volume IoT streams, predictable write performance, and denormalized tables built around known access patterns.

---

## Slide 22: CAP Theorem and Tunable Consistency

Cassandra is designed as an AP‑leaning system under the CAP theorem: it prioritizes Availability and Partition Tolerance so that the cluster can keep accepting reads and writes even during network partitions or node failures. The trade‑off is that strictly linearizable consistency is not guaranteed at low consistency levels; a client may temporarily read slightly stale data. However, Cassandra introduces **tunable consistency**: for each read and write, the application chooses a consistency level (for example ONE, QUORUM, ALL), which controls how many replicas must acknowledge the operation. With replication factor RF=2 in this project, using QUORUM for both reads and writes already gives strong, up‑to‑date results for most workloads while still tolerating single‑node failures. This per‑query choice lets the application dial in the right balance between latency, availability, and freshness based on the specific use case.