# Baseline Architecture

## Overview

This document describes the current baseline architecture of the IoT streaming
project. The system simulates heterogeneous sensors, streams data through Kafka,
processes it with Spark Structured Streaming, and persists raw, analytical, and
alert-oriented views in Cassandra.

The updated baseline is no longer a single-topic, single-table pipeline.
Instead, it is organized around three sensor families, three Kafka topics,
three Cassandra keyspaces, and multiple query-oriented tables designed around
the actual access patterns of the project.

---

## End-to-End Flow

```text
90 Simulated Sensors
(3 types × 3 rooms × 10 sensors)
        │
        │ JSON messages (~90 msg/sec total)
        ▼
Apache Kafka
  ├─ sensor_temp_humidity
  ├─ sensor_light
  └─ sensor_power
        ▼
Spark Structured Streaming
  ├─ Raw ingestion tables
  │   ├─ iot_raw.temp_humidity_by_sensor
  │   ├─ iot_raw.light_by_sensor
  │   ├─ iot_raw.power_by_sensor
  │   ├─ iot_raw.readings_by_location
  │   └─ iot_raw.devices_metadata
  │
  ├─ Analytics tables
  │   ├─ iot_analytics.sensor_aggregates_30s
  │   ├─ iot_analytics.aggregates_by_type
  │   └─ iot_analytics.sensor_behavior_profiles
  │
  └─ Alert tables
      ├─ iot_alerts.sensor_alerts
      └─ iot_alerts.alerts_by_location
        ▼
3-Node Cassandra Cluster
(RF=2, NetworkTopologyStrategy, dc1)
```

---

## Infrastructure

### Docker Topology

The baseline environment is containerized with Docker Compose and includes:

- Zookeeper for Kafka coordination.
- One Kafka broker.
- One Kafka initialization container that creates the required topics.
- Three Cassandra nodes in a single datacenter cluster.
- One Cassandra initialization container that applies the schema.
- One Schema Registry container.
- An optional fourth Cassandra node enabled through the `scaleout` profile.

Spark is not containerized in this baseline. It runs externally with
`spark-submit` and connects to Kafka and Cassandra through their exposed ports.

### Kafka Topics

Kafka is configured with auto-topic creation disabled, so the baseline creates
topics explicitly during startup. The three input topics are:

- `sensor_temp_humidity`
- `sensor_light`
- `sensor_power`

Each topic is created with 3 partitions and replication factor 1.

### Cassandra Cluster

The Cassandra cluster runs as a single-datacenter deployment named
`IoT-Cluster` with `dc1` and `rack1`. Node `cassandra-1` acts as the seed node,
while the other nodes join with delayed startup to avoid unstable cluster
formation during bootstrap.

An optional `cassandra-4` service is already defined for later scale-out
experiments, but it is not part of the default baseline.

### Memory Budgeting

The Compose file applies explicit memory limits to the main JVM-based services:

| Component | Memory limit | Notes |
|---|---:|---|
| Zookeeper | 512 MB | Lightweight coordination service |
| Kafka | 1 GB | Broker heap explicitly tuned |
| Cassandra node 1 | 1800 MB | Seed node, slightly larger budget |
| Cassandra node 2 | 1500 MB | Standard data node |
| Cassandra node 3 | 1500 MB | Standard data node |
| Schema Registry | 512 MB | Metadata service |
| Cassandra node 4 (optional) | 1500 MB | Enabled only with `scaleout` profile |

This keeps the baseline predictable on a development machine and avoids the
unbounded JVM memory behavior that commonly appears when Cassandra and Kafka are
started without strict container limits.

---

## Producer

### Sensor Model

The producer simulates **90 sensors** in total:

- 30 `temp_humidity` sensors
- 30 `light` sensors
- 30 `power` sensors

They are distributed across three rooms:

- `room_A`
- `room_B`
- `room_C`

Each sensor type has 10 sensors per room, so the physical layout is regular and
easy to reason about during tests and demos.

### Stable Identity

Sensor IDs are deterministic UUIDv5 values generated from
`(sensor_type, room, index)`. This is an important baseline choice because it
keeps sensor identity stable across restarts, which makes Cassandra partitions,
alerts, and behavior profiles reproducible.

### Anomaly Narrative

The producer is not fully random. It embeds a controlled anomaly model:

- Normal sensors have a spike probability of `0.2%`.
- Abnormal sensors have a spike probability of `8%`.
- Exactly 9 abnormal sensors exist in the baseline.
- All abnormal sensors are clustered in `room_A`.
- There are 3 abnormal sensors per sensor type.

This design supports the main demo story of the project: threshold alerts first
cluster in one room, then analytical and similarity-oriented logic can identify
related abnormal behavior among peer sensors.

### Published Payloads

Each message contains a common base:

- `sensor_id`
- `sensor_type`
- `location_id`
- `description`
- `timestamp`

Then each topic-specific payload adds the relevant measurements:

| Sensor type | Fields |
|---|---|
| `temp_humidity` | `temperature`, `humidity` |
| `light` | `light_level` |
| `power` | `voltage`, `amperage` |

For power sensors, `wattage` is **not** sent by the producer. It is derived
later in Spark as `voltage * amperage`.

### Throughput

The producer sends one reading per sensor every second, so the target baseline
throughput is approximately **90 messages per second**.

---

## Spark Consumer

### Ingestion Model

The Spark application reads from the three Kafka topics independently and parses
each stream with a dedicated schema:

- `SCHEMA_TEMP_HUMIDITY`
- `SCHEMA_LIGHT`
- `SCHEMA_POWER`

After parsing, each stream is enriched with:

- a proper Spark `timestamp` column converted from epoch milliseconds
- a `date` column derived from the event timestamp

For power readings, Spark also adds:

- `wattage = voltage * amperage`

### Streaming Queries

The baseline runs multiple concurrent streaming queries, each mapped to a clear
storage or processing responsibility.

#### Raw ingestion queries

These streams persist normalized raw data into `iot_raw`:

- `temp_humidity_by_sensor`
- `light_by_sensor`
- `power_by_sensor`

They also build a denormalized location-oriented table:

- `readings_by_location`

And they maintain a metadata table:

- `devices_metadata`

#### Analytics queries

These streams generate 30-second windowed summaries into `iot_analytics`:

- `sensor_aggregates_30s`
- `aggregates_by_type`

In addition, a periodic refresh process computes:

- `sensor_behavior_profiles`

#### Alert queries

A dedicated alert path inspects incoming readings against thresholds and writes
to `iot_alerts`:

- `sensor_alerts`
- `alerts_by_location`

### Watermarking and Windows

The analytical aggregations use event-time processing with a **1 minute**
watermark and **30 second tumbling windows**. This keeps the baseline close to
real-time while still allowing small delays in event arrival.

### Profile Refresh Path

Behavior profiles are not built with `applyInPandasWithState`. Instead, the
project uses a `foreachBatch` approach driven by a lightweight `rate` stream
that triggers recomputation every 30 seconds.

This is a deliberate architectural choice. It avoids Arrow-dependent stateful
execution complexity while still producing rolling per-sensor profiles that are
suitable for vector search experiments in Cassandra.

---

## Cassandra Design

### Keyspaces

The schema is split into three keyspaces, each with a different role:

| Keyspace | Purpose |
|---|---|
| `iot_raw` | Raw ingestion and operational lookup tables |
| `iot_alerts` | Threshold-based alert storage |
| `iot_analytics` | Aggregates and behavior profiles |

All three use:

- `NetworkTopologyStrategy`
- datacenter `dc1`
- replication factor `2`

This means each partition is stored on two of the three default nodes, which is
a better fit than `SimpleStrategy` for a topology-aware Cassandra deployment.

---

## Raw Tables

### `devices_metadata`

This table stores reference information for each sensor:

- `sensor_id`
- `sensor_type`
- `location_id`
- `description`

Its primary key is `(sensor_type, sensor_id)`. This groups metadata by sensor
family and supports efficient lookup within a very small and mostly read-heavy
dataset.

### `temp_humidity_by_sensor`

This table stores raw temperature and humidity readings per sensor. The primary
key is `((sensor_id, date), timestamp)` with descending clustering order on
`timestamp`.

The partition key intentionally includes the day. That bounds partition size to
a single sensor-day and avoids unbounded growth in long-running streams.

### `light_by_sensor`

This table mirrors the same design as `temp_humidity_by_sensor`, but for light
measurements. It uses the same daily bucketing strategy and descending
timestamp clustering.

### `power_by_sensor`

This table stores raw voltage and amperage readings plus Spark-derived
`wattage`. It follows the same partitioning model as the other sensor-specific
raw tables.

### `readings_by_location`

This table reorganizes the same events by physical location instead of sensor.
Its primary key is `((location_id, date), timestamp, sensor_id)`.

This is an intentionally sparse table: only the columns relevant to the sensor
type are populated in each row. That is useful in Cassandra because absent
cells do not consume fixed-width row space the way a traditional relational
layout would.

A Storage-Attached Index is also created on `humidity` for this table, enabling
secondary access patterns on raw humidity values.

### Raw-table compaction

The write-heavy raw ingestion tables use
`SizeTieredCompactionStrategy (STCS)`. This is coherent with the baseline
workload because these tables receive continuous append-heavy writes and are not
primarily optimized for complex read-side analytics.

---

## Analytics Tables

### `sensor_aggregates_30s`

This table stores per-sensor, per-window metrics:

- `avg_value`
- `min_value`
- `max_value`
- `reading_count`

Its primary key is `((sensor_id, date), window_start)`, so it mirrors the same
bounded daily partition design used by the raw sensor tables.

### `aggregates_by_type`

This table supports cross-sensor analysis by sensor family. Its primary key is
`((sensor_type, date), window_start, sensor_id)`.

That layout makes it efficient to answer questions like “how are all power
sensors performing today?” without scanning sensor-specific partitions one by
one.

### `sensor_behavior_profiles`

This table stores one rolling behavior profile per sensor and is meant for
similarity search. Each row contains:

- `last_updated_at`
- `profile_size`
- `mean_value`
- `variance_value`
- `spike_count`
- `profile_vector`

The primary key is `((location_id, sensor_type), sensor_id)`. This is a crucial
design choice because it narrows similarity search to peer sensors in the same
room and same sensor family, which matches the project’s anomaly narrative.

The table also defines a vector column:

- `profile_vector VECTOR<FLOAT, 3>`

and a vector index:

- `sensor_behavior_profiles_vector_idx`

This makes the current baseline explicitly ready for Cassandra-native vector
search experiments.

### Profile semantics

The profile vector is built as:

- mean observed value
- variance of the observed value
- spike count above a type-specific threshold

The source metric depends on the sensor family:

| Sensor type | Profile source metric |
|---|---|
| `temp_humidity` | `humidity` |
| `light` | `light_level` |
| `power` | `wattage` |

Only sensors with at least 10 recent readings are materialized into the profile
table, and the computation uses up to the most recent 200 values per sensor.

### Analytics compaction

The analytics tables use `LeveledCompactionStrategy (LCS)`. This is appropriate
because they serve read-oriented workloads where predictable lookup latency is
more important than maximizing raw write throughput.

---

## Alerting

### Threshold logic

The baseline alert path checks readings against explicit thresholds:

| Condition | Threshold |
|---|---:|
| Temperature high | 40.0 |
| Temperature low | 5.0 |
| Humidity high | 85.0 |
| Humidity low | 20.0 |
| Light high | 900.0 |
| Voltage high | 240.0 |
| Amperage high | 10.0 |
| Wattage high | 2000.0 |

In the current code, alerts are emitted for:

- `TEMPERATURE_HIGH`
- `TEMPERATURE_LOW`
- `HUMIDITY_HIGH`
- `LIGHT_HIGH`
- `VOLTAGE_HIGH`
- `AMPERAGE_HIGH`

Each alert is assigned a generated UUID, a severity label, and a human-readable
message.

### Alert Tables

Two query-oriented tables are maintained:

#### `sensor_alerts`

Primary key: `(sensor_id, timestamp, alert_id)`

This supports the access pattern “show recent alerts for a sensor” and uses
`alert_id` to avoid collisions when multiple alerts are generated at the same
timestamp.

#### `alerts_by_location`

Primary key: `((location_id, date), timestamp, sensor_id, alert_id)`

This supports the access pattern “show recent alerts in a room on a given day”.

### Alert-table compaction

The alert tables are configured for read-oriented usage and align with the
overall design choice of keeping operational alert lookups separate from both
raw ingestion and analytics workloads.

---

## Engineering Decisions

| Decision | Current baseline choice | Rationale |
|---|---|---|
| Sensor ingestion split | 3 Kafka topics by sensor family | Simpler schemas, clearer stream ownership, topic-level parallelism |
| Physical sensor layout | 3 rooms × 3 types × 10 sensors | Reproducible demo topology |
| Identity model | Stable UUIDv5 sensor IDs | Consistent partitions and repeatable experiments |
| Anomaly design | 9 abnormal sensors clustered in `room_A` | Makes alert and similarity demos interpretable |
| Raw storage model | Per-sensor tables + per-location table | Supports both sensor-centric and room-centric queries |
| Replication strategy | `NetworkTopologyStrategy`, RF=2 | Topology-aware baseline for 3-node Cassandra |
| Raw compaction | STCS | Better fit for append-heavy ingestion |
| Analytics compaction | LCS | Better fit for read-heavy aggregate queries |
| Profile computation | `foreachBatch` + periodic trigger | Avoids more complex stateful pandas/Arrow path |
| Vector search support | `VECTOR<FLOAT, 3>` + SAI index | Prepares the project for ANN-style similarity search |

---

## Query Patterns Supported

The baseline is designed around the following access patterns:

- Latest raw readings for a sensor on a given day.
- Recent readings for all sensors in a given room.
- Sensor metadata grouped by type.
- Recent 30-second aggregates for a specific sensor.
- Cross-sensor aggregate views by sensor family.
- Recent alerts for a sensor.
- Recent alerts for a room.
- Similarity search among peer sensors in the same room and sensor type.

This is the main architectural improvement over the previous baseline: the
schema is now explicitly shaped around multiple read paths instead of a single
generic event table.

---

## Running the Baseline

### Start infrastructure

```bash
docker compose up -d
```

This starts Zookeeper, Kafka, Kafka topic initialization, Cassandra, schema
initialization, and Schema Registry.

### Start the producer

```bash
python producer.py
```

### Start Spark

```bash
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1,com.datastax.spark:spark-cassandra-connector_2.12:3.5.1 \
  spark_consumer.py
```

Spark connects to Kafka and Cassandra through environment defaults:

- Kafka: `localhost:9092`
- Cassandra: `localhost:9042`
- checkpoints: `/tmp/spark_checkpoints`

---

## Baseline Scope

This baseline already includes more than simple ingestion. It provides:

- topic-level separation by sensor family
- normalized raw storage
- denormalized location views
- rolling analytical aggregates
- rule-based alerts
- behavior profiling for vector search
- schema bootstrap through Docker Compose

In other words, the current “baseline” is the first fully coherent version of
the end-to-end architecture, not just a minimal proof of concept.

---

## Notes

A few details are worth calling out explicitly:

- `wattage` is computed in Spark, not produced directly by the sensors.
- The behavior profile for `temp_humidity` sensors is based on humidity, not temperature.
- The default cluster is 3 Cassandra nodes, but a fourth node is already prepared for future scale-out testing.
- Schema Registry is present in the environment even though the current producer still publishes JSON.
- The current Spark application runs many concurrent streaming queries because each storage path is intentionally materialized separately.

These choices make the repository a stronger systems project: it now shows
stream ingestion, query-driven data modeling, alerting, and vector-ready
analytics in one consistent pipeline.