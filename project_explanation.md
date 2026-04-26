# IoT project explanation source for NotebookLM

This note explains the Cassandra-based IoT project used as the case study for the presentation.

It is intended to serve as the **factual project source** for the slide deck.  
The presentation focuses on Cassandra, but the project is the concrete environment that proves the database design choices.

---

## 1. Project objective

The project is an IoT streaming pipeline built to ingest sensor events in real time, process them with Spark Structured Streaming, and persist multiple views of the data in Apache Cassandra.

The project is not just a generic data pipeline.  
It is specifically designed to show how Cassandra can support:

- high-throughput raw ingestion,
- denormalized query-oriented schema design,
- room-based and sensor-based query patterns,
- alert persistence,
- windowed analytics,
- and a Cassandra 5 extension toward vector similarity search.

The overall presentation goal is therefore to use this project as evidence that Cassandra’s architecture and modeling principles are directly applicable to an IoT analytics workload.

---

## 2. High-level architecture

The project is composed of four main layers:

1. **Kafka producer**
2. **Kafka broker**
3. **Spark Structured Streaming consumer**
4. **Cassandra cluster**

The data flow is:

**Producer -> Kafka topics -> Spark Structured Streaming -> Cassandra**

The producer emits sensor events continuously.  
Spark consumes the events from Kafka, parses the JSON payloads, enriches and transforms the data, computes alerts and analytics, and writes the results into Cassandra tables.

---

## 3. Deployment environment

The stack is deployed with Docker Compose.

The main infrastructure components are:

- ZooKeeper
- Kafka
- Kafka topic initialization container
- Cassandra schema initialization container
- Cassandra node 1
- Cassandra node 2
- Cassandra node 3

The Cassandra deployment is a **3-node Cassandra 5 cluster**.  
The cluster uses:
- cluster name `IoT-Cluster`,
- datacenter `dc1`,
- `GossipingPropertyFileSnitch`,
- and Cassandra 5 images for all three nodes.

Kafka topics are created explicitly by the initialization container rather than relying on auto-created topics.

---

## 4. Kafka topics and sensor streams

The producer side of the project generates **three sensor streams**, each represented by a dedicated Kafka topic:

- `sensor_temp_humidity`
- `sensor_light`
- `sensor_power`

These correspond to three sensor families:

1. temperature/humidity sensors,
2. light sensors,
3. power sensors.

The Spark consumer reads these three topics separately and parses them into three structured streams.

---

## 5. Spark consumer role

The Spark application is the central processing layer of the system.

Its responsibilities include:

- reading the three Kafka topics,
- parsing JSON sensor events,
- converting timestamps,
- deriving a `date` column for partition-bounded tables,
- enriching power readings with computed `wattage`,
- writing raw streams into Cassandra,
- building windowed aggregates,
- generating threshold-based alerts,
- and writing simplified behavior profiles for vector search.

In the Cassandra schema, the keyspaces are:

- `iot_raw`
- `iot_analytics`
- `iot_alerts`

For presentation purposes, these should be described as the same three logical areas:
- raw ingestion,
- analytics,
- alerts.

---

## 6. Cassandra cluster and replication design

The Cassandra schema defines three keyspaces:

- `iot_raw`
- `iot_alerts`
- `iot_analytics`

Each keyspace uses:

- `NetworkTopologyStrategy`
- datacenter `dc1`
- replication factor `2`.

This means each partition is replicated on **2 of the 3 Cassandra nodes**, which is a useful concrete example for explaining replication, fault tolerance, and tunable consistency in the presentation.

---

## 7. Raw ingestion data model

The `iot_raw` keyspace stores the operational sensor data and metadata.

### 7.1 `devices_metadata`
This table stores static reference information about sensors:
- sensor_ID,
- sensor_type,
- location_ID,
- and description.

Its purpose is to answer metadata lookups for a sensor.

### 7.2 `temp_humidity_by_sensor`
This table stores raw temperature and humidity events for a single sensor over time.

Its key design uses:
- sensor_ID,
- date bucket,
- timestamp as clustering order.

This supports the query pattern:
- “give me the latest readings for this temperature/humidity sensor on this day.”

### 7.3 `light_by_sensor`
This table stores raw light readings per sensor with the same time-bucket pattern.

### 7.4 `power_by_sensor`
This table stores raw electrical readings per sensor:
- amperage,
- voltage,
- and derived wattage.

`wattage` is not part of the original Kafka message; it is computed inside Spark as:
- voltage × amperage.

These raw tables are write-heavy and use `SizeTieredCompactionStrategy`, which matches their ingestion-oriented workload.

---

## 8. Location-centric wide table

One of the most important raw tables is:

- `readings_by_location`.

This table reorganizes sensor data by:
- location,
- date,
- timestamp,
- sensor ID.

Its purpose is to answer queries such as:
- “show all readings in room X on date D.”

This table is intentionally **sparse**:
- temperature/humidity rows only populate temperature and humidity columns,
- light rows only populate the light column,
- power rows only populate amperage, voltage, and wattage columns.

The Cassandra schema comments explicitly describe this as an intentional demonstration of Cassandra’s storage model: irrelevant columns are absent rather than stored as fixed-width nulls, which makes the table a good example of wide-column and sparse-row design.

This table is very important for the presentation because it shows a specifically Cassandra-oriented way of thinking about data layout.

---

## 9. Metadata and denormalization logic

The project does not try to normalize everything into a small number of generic tables.

Instead, it follows a query-oriented pattern:
- per-sensor raw tables,
- location-centric table,
- metadata table,
- alerts table,
- analytics tables,
- and vector-profile table.

This makes the project a strong example of Cassandra’s query-first modeling philosophy:
the same domain is represented through multiple tables shaped for different access paths.

---

## 10. Alert pipeline

The Spark consumer defines threshold-based alert logic.

Alerts are triggered for conditions such as:
- high temperature,
- low temperature,
- high humidity,
- high light level,
- high voltage,
- high amperage.

Spark generates:
- `alert_id`,
- severity,
- message text,
- and the event timestamp,
then writes alerts into the Cassandra alerts table.

The Cassandra alerts table is:

- `iot_alerts.sensor_alerts`.

Its key design groups alerts by sensor and orders them by timestamp descending, with `alert_id` included to avoid collisions when more than one alert occurs at nearly the same time.

This table is a clean example of a read-oriented Cassandra table designed around the query:
- “show recent alerts for sensor X.”

---

## 11. Analytics tables

The `iot_analytics` keyspace stores derived analytical views.

### 11.1 `sensor_aggregates_30s`
This table contains 30-second window aggregates per sensor:
- average value,
- minimum,
- maximum,
- reading count.

It mirrors the raw-table partitioning pattern by using sensor and date as the partition dimension.

### 11.2 `aggregates_by_type`
This table groups sensor data by sensor type and date, enabling cross-sensor comparisons for the same family of sensors.

This supports queries like:
- “how are all sensors of this type behaving today?”

Together, these analytics tables show how Spark creates derived materialized views tailored to specific read patterns in Cassandra.

---

## 12. Vector-search-oriented table

The Cassandra schema also contains:

- `sensor_behavior_profiles` in `iot_analytics`.

This table is intended for Cassandra 5 vector search.

Its columns include:
- location_ID,
- sensor_type,
- sensor_ID,
- last_update_timestamp,
- profile_size,
- mean_value,
- variance_value,
- spike_count,
- and `profile_vector VECTOR<FLOAT, 3>`.

The table is partitioned by:
- `location_id`,
- `sensor_type`.

This is an important modeling decision because ANN search should compare only **peer sensors**:
- in the same room,
- and of the same sensor family.

The schema also defines an SAI index on the vector column.

This table is central to the advanced Cassandra 5 part of the presentation.

---

## 13. Current implementation status of behavior profiles

The current Spark consumer includes a simplified `foreachBatch` path for populating `sensor_behavior_profiles`.

This is important context for the presentation:
the current stable version avoids the previous stateful Pandas path and instead computes behavior-profile features inside a simpler batch callback.

The features currently written are based on:
- `mean_value`,
- `variance_value`,
- `spike_count`,
which are then assembled into a 3-dimensional vector.

For presentation purposes, this should be described carefully:
the project already demonstrates Cassandra’s ability to store vectors and perform ANN-style lookups, while the logic used to build those vectors can be improved independently of Cassandra itself.

That distinction matters:
- vector search requires stored vectors and ANN querying support,
- not a specific Spark state mechanism.

---

## 14. Why the project is a good Cassandra case study

This project is a good Cassandra case study because it naturally exhibits several Cassandra strengths.

### 14.1 Heavy continuous ingestion
Sensor events arrive continuously, which aligns well with Cassandra’s write-optimized architecture.

### 14.2 Query-oriented denormalization
The same domain is stored in multiple tables, each shaped for a concrete query pattern.

### 14.3 Time-bucketed partitioning
Raw sensor tables partition by sensor and date, which bounds partition size and keeps recency-oriented queries practical.

### 14.4 Room-centric analytics
The location-based table demonstrates how Cassandra can support alternate query dimensions without joins.

### 14.5 Alert persistence
The alert table is a strong example of a narrow, query-specific read path.

### 14.6 Derived analytics
Windowed aggregates show how Spark and Cassandra combine naturally: Spark computes, Cassandra persists denormalized outputs.

### 14.7 Advanced Cassandra 5 feature
The vector-profile table extends the model from classic operational analytics toward similarity search.

---

## 15. Suggested presentation story

The presentation should use the project as evidence, not as a distraction from Cassandra.

A good narrative is:

1. Explain Cassandra fundamentals first.
2. Show how partitioning, denormalization, and write-optimized storage influence schema design.
3. Introduce the IoT pipeline as the practical environment.
4. Use real tables to show query-first modeling.
5. Show how alerts and analytics become natural Cassandra read models.
6. End with Cassandra 5 vector search as a modern extension of the same data model.

The project should therefore appear as:
- a concrete proof of Cassandra concepts,
- not merely as a list of implementation details.

---

## 16. Key project facts to preserve

When generating slides or notes, preserve these facts:

- The project uses **Kafka + Spark Structured Streaming + Cassandra**.
- Kafka contains **three sensor topics**: `sensor_temp_humidity`, `sensor_light`, `sensor_power`.
- Cassandra is deployed as a **3-node Cassandra 5 cluster**.
- The schema defines three keyspaces: `iot_raw`, `iot_alerts`, `iot_analytics`.
- Keyspaces use `NetworkTopologyStrategy` with replication factor 2 in `dc1`.
- Raw tables include `temp_humidity_by_sensor`, `light_by_sensor`, `power_by_sensor`, `readings_by_location`, and `devices_metadata`.
- Alerts are stored in `sensor_alerts`.
- Analytics tables include `sensor_aggregates_30s` and `aggregates_by_type`.
- The vector-search-oriented table is `sensor_behavior_profiles` with `profile_vector VECTOR<FLOAT, 3>` and an SAI index.
- Spark computes `wattage` from voltage and amperage before persisting power readings.

These are the core facts that should remain stable across the deck.

## 17 init.cql

Here is the whole cassandra init.cql file that explains the cassandra schema

```sql
-- ============================================================
-- IoT Sensor Pipeline — Cassandra Schema
-- Cluster:  3 nodes, RF=2, NetworkTopologyStrategy
-- Keyspaces: iot_raw | iot_alerts | iot_analytics
-- ============================================================

-- ============================================================
-- KEYSPACE: iot_raw
-- Stores raw per-sensor readings and device metadata.
-- RF=2: each partition lives on 2 of 3 nodes.
-- NetworkTopologyStrategy: production-grade, datacenter-aware.
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS iot_raw
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 2
};

USE iot_raw;

-- ------------------------------------------------------------
-- TABLE: devices_metadata
-- Purpose: Static sensor reference data (type, location).
-- Query:   "give me metadata for sensor X"
-- Key design: simple partition key only — no clustering columns
--             needed because lookups are by exact sensor_id,
--             with no ordering or range scan within the partition.
-- Compaction: Leveled — reference data is read-heavy, rarely written.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS devices_metadata (
    sensor_id   uuid,
    sensor_type text,
    location_id text,
    description text,
    PRIMARY KEY (sensor_type, sensor_id)
)
WITH compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = 'Static sensor reference data. Partition key is sensor_type (3 partitions) with sensor_id as clustering column. Leveled compaction for read-optimized access.';

-- ------------------------------------------------------------
-- TABLE: temp_humidity_by_sensor
-- Purpose: Raw temperature and humidity readings per sensor.
-- Query:   "latest readings for temp/humidity sensor X on date D"
-- Key design: composite partition key (sensor_id, date) bounds
--             partition size to ~86 400 rows/day per sensor.
--             timestamp DESC clustering returns most recent first.
-- Compaction: SizeTiered — write-heavy continuous ingestion.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS temp_humidity_by_sensor (
    sensor_id   uuid,
    date        date,
    timestamp   timestamp,
    location_id text,
    temperature float,
    humidity    float,
    PRIMARY KEY ((sensor_id, date), timestamp)
)
WITH CLUSTERING ORDER BY (timestamp DESC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'Raw temp/humidity readings. Composite partition key caps partition size to one day per sensor. STCS for write throughput.';

-- ------------------------------------------------------------
-- TABLE: light_by_sensor
-- Purpose: Raw light level readings per sensor.
-- Query:   "latest readings for light sensor X on date D"
-- Key design: same time-bucket strategy as temp_humidity_by_sensor.
-- Compaction: SizeTiered — write-heavy continuous ingestion.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS light_by_sensor (
    sensor_id   uuid,
    date        date,
    timestamp   timestamp,
    location_id text,
    light_level float,
    PRIMARY KEY ((sensor_id, date), timestamp)
)
WITH CLUSTERING ORDER BY (timestamp DESC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'Raw light level readings. Composite partition key caps partition size to one day per sensor. STCS for write throughput.';

-- ------------------------------------------------------------
-- TABLE: power_by_sensor
-- Purpose: Raw amperage and voltage readings per sensor.
-- Query:   "latest readings for power sensor X on date D"
-- Key design: same time-bucket strategy as temp_humidity_by_sensor.
-- Compaction: SizeTiered — write-heavy continuous ingestion.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS power_by_sensor (
    sensor_id   uuid,
    date        date,
    timestamp   timestamp,
    location_id text,
    amperage    float,
    voltage     float,      
    wattage     float,      -- derived by Spark: voltage * amperage
    PRIMARY KEY ((sensor_id, date), timestamp)
)
WITH CLUSTERING ORDER BY (timestamp DESC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'Raw power readings enriched by Spark. wattage is absent from Kafka messages and computed in-flight as voltage * amperage. STCS for write throughput.';

-- ------------------------------------------------------------
-- TABLE: readings_by_location
-- Purpose: All sensor readings grouped by physical location.
-- Query:   "all readings in room X on date D"
-- Key design: partition key is (location_id, date) — all sensors
--             in the same room on the same day share a partition.
--             timestamp DESC + sensor_id as clustering columns
--             provide recency ordering and row uniqueness.
-- Sparseness: INTENTIONALLY SPARSE — each row only populates
--             the columns relevant to its sensor type, leaving
--             the others absent (not null). This demonstrates
--             Cassandra's LSM-tree storage model: absent cells
--             occupy zero bytes on disk, unlike RDBMS fixed-width
--             rows which preallocate space for every column.
-- Compaction: SizeTiered — write-heavy, mirrors ingestion rate.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS readings_by_location (
    location_id text,
    date        date,
    timestamp   timestamp,
    sensor_id   uuid,
    sensor_type text,
    -- temp/humidity sensor columns (absent for light and power rows)
    temperature float,
    humidity    float,
    -- light sensor columns (absent for temp/humidity and power rows)
    light_level float,
    -- power sensor columns (absent for temp/humidity and light rows)
    amperage    float,
    voltage     float,
    wattage     float,    -- derived by Spark: voltage * amperage
    PRIMARY KEY ((location_id, date), timestamp, sensor_id)
)
WITH CLUSTERING ORDER BY (timestamp DESC, sensor_id ASC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'All readings by location. Intentionally sparse: rows omit irrelevant sensor columns — absent cells waste no disk space in the LSM-tree model.';

-- SIA index to query on raw humidity values.
CREATE CUSTOM INDEX IF NOT EXISTS readings_by_location_humidity_sai
ON iot_raw.readings_by_location (humidity)
USING 'StorageAttachedIndex';

-- xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

-- ============================================================
-- KEYSPACE: iot_alerts
-- Stores threshold-based alerts generated by Spark.
-- RF=2, same datacenter topology.
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS iot_alerts
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 2
};

USE iot_alerts;

-- ------------------------------------------------------------
-- TABLE: sensor_alerts
-- Purpose: Alerts fired when sensor readings cross thresholds.
-- Query:   "recent alerts for sensor X"
-- Key design: sensor_id as partition key groups all alerts for
--             a sensor together. timestamp DESC gives recency
--             ordering. alert_id as tertiary clustering column
--             guarantees uniqueness — prevents silent overwrites
--             if two alerts fire within the same millisecond.
-- Compaction: Leveled — alerts are read frequently, written sparsely.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sensor_alerts (
    sensor_id     uuid,
    timestamp     timestamp,
    alert_id      uuid,
    location_id   text,
    alert_type    text,
    alert_message text,
    severity      text,
    PRIMARY KEY (sensor_id, timestamp, alert_id)
)
WITH CLUSTERING ORDER BY (timestamp DESC, alert_id ASC)
AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = 'Threshold alerts from Spark. alert_id prevents millisecond-collision overwrites. LCS for read-optimized alert queries.';

-- SIA index, create it in live:

-- CREATE CUSTOM INDEX IF NOT EXISTS sensor_alerts_location_sai
-- ON iot_alerts.sensor_alerts (location_id)
-- USING 'StorageAttachedIndex';

-- xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

-- ============================================================
-- KEYSPACE: iot_analytics
-- Stores 30-second windowed aggregations computed by Spark.
-- RF=2, same datacenter topology.
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS iot_analytics
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 2
};

USE iot_analytics;

-- ------------------------------------------------------------
-- TABLE: sensor_aggregates_30s
-- Purpose: Per-sensor 30-second windowed statistics.
-- Query:   "30s aggregates for sensor X on date D"
-- Key design: composite partition key (sensor_id, date) mirrors
--             the raw tables — one partition per sensor per day.
--             window_start DESC clustering returns most recent
--             aggregation windows first.
-- Compaction: Leveled — analytics tables are read-heavy.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sensor_aggregates_30s (
    sensor_id     uuid,
    date          date,
    window_start  timestamp,
    sensor_type   text,
    location_id   text,
    avg_value     float,
    min_value     float,
    max_value     float,
    reading_count int,
    PRIMARY KEY ((sensor_id, date), window_start)
)
WITH CLUSTERING ORDER BY (window_start DESC)
AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = '30s windowed aggregates per sensor. Mirrors raw table partition strategy. LCS for predictable analytics read latency.';

-- ------------------------------------------------------------
-- TABLE: aggregates_by_type
-- Purpose: Cross-sensor aggregates grouped by sensor type.
-- Query:   "how are all temperature sensors performing today?"
-- Key design: partition key is (sensor_type, date) — all sensors
--             of the same type on the same day share a partition,
--             enabling efficient cross-sensor comparisons.
--             window_start + sensor_id as clustering columns
--             provide time ordering and row uniqueness.
-- Compaction: Leveled — analytics read-heavy workload.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aggregates_by_type (
    sensor_type  text,
    date         date,
    window_start timestamp,
    sensor_id    uuid,
    location_id  text,
    avg_value    float,
    PRIMARY KEY ((sensor_type, date), window_start, sensor_id)
)
WITH CLUSTERING ORDER BY (window_start DESC, sensor_id ASC)
AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = 'Cross-sensor aggregates by type. Partition key enables efficient type-wide analytics. LCS for read-optimized queries.';

-- ------------------------------------------------------------
-- TABLE: sensor_behavior_profiles
-- Purpose: Latest rolling behavior profile per sensor for ANN.
-- Query:   "within room X and sensor type Y, find sensors with
--          behavior similar to this anomalous profile"
-- Key design: partition key is (location_id, sensor_type) so
--             ANN compares only peer sensors in the same room
--             and same sensor family. sensor_id is clustering
--             key so each sensor has exactly one latest row.
-- Compaction: Leveled — read-oriented analytical lookup table.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sensor_behavior_profiles (
    location_id      text,
    sensor_type      text,
    sensor_id        uuid,
    last_updated_at  timestamp,
    profile_size     int,
    mean_value       float,
    variance_value   float,
    spike_count      int,
    profile_vector   VECTOR<FLOAT, 3>,
    PRIMARY KEY ((location_id, sensor_type), sensor_id)
)
WITH compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = 'Latest rolling behavior profile per sensor. Partition groups peer sensors by room and type for ANN queries.';

CREATE INDEX IF NOT EXISTS sensor_behavior_profiles_vector_idx
ON sensor_behavior_profiles (profile_vector)
USING 'sai';

-- ============================================================
-- Verification: list all tables per keyspace
-- Run after initialization to confirm schema loaded correctly.
-- ============================================================

SELECT keyspace_name, table_name
FROM system_schema.tables
WHERE keyspace_name IN ('iot_raw', 'iot_alerts', 'iot_analytics');
```