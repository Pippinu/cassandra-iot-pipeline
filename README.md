# Apache Cassandra Real-Time IoT Analytics Pipeline

A real-time IoT streaming project that simulates heterogeneous sensors, ingests
their readings through **Kafka**, processes them with **Spark** Structured Streaming,
and stores raw data, alerts, and analytical views in a multi-node **Cassandra**
cluster.

This university project is centered on **Apache Cassandra** and serves as a hands-on distributed systems and data engineering playground. It emphasizes query-first Cassandra data modeling, real-time stream processing, threshold-based alerting, and vector-ready sensor behavior profiling.

---

## Architecture

```text
90 Simulated Sensors
(3 types × 3 rooms × 10 sensors)
        │
        │ JSON messages (~90 msg/sec)
        ▼
Apache Kafka
  ├─ sensor_temp_humidity
  ├─ sensor_light
  └─ sensor_power
        ▼
Spark Structured Streaming
  ├─ iot_raw
  │   ├─ temp_humidity_by_sensor
  │   ├─ light_by_sensor
  │   ├─ power_by_sensor
  │   ├─ readings_by_location
  │   └─ devices_metadata
  │
  ├─ iot_analytics
  │   ├─ sensor_aggregates_30s
  │   ├─ aggregates_by_type
  │   └─ sensor_behavior_profiles
  │
  └─ iot_alerts
      ├─ sensor_alerts
      └─ alerts_by_location
        ▼
3-Node Apache Cassandra Cluster
(RF=2, NetworkTopologyStrategy, dc1)
```

---

## What the project does

- Simulates 90 sensors across 3 sensor families: `temp_humidity`, `light`, and `power`.
- Publishes readings to 3 Kafka topics, one per sensor type.
- Processes the streams with Spark Structured Streaming.
- Writes raw sensor data into query-oriented Cassandra tables.
- Builds 30-second analytical aggregates.
- Detects threshold-based alerts in real time.
- Computes rolling sensor behavior profiles for vector-search experiments.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Simulation | **Python** 3 |
| Messaging | Apache **Kafka**, **Zookeeper** |
| Stream processing | Apache **Spark** 3.5 / **PySpark** |
| Storage | Apache **Cassandra** 5.0 |
| Schema bootstrap | **CQL** (`init.cql`) |
| Container orchestration | **Docker** Compose |
| Metadata service | Confluent Schema Registry |

---

## Current baseline

The current baseline is organized around three logical storage layers in Cassandra:

| Keyspace | Purpose |
|---|---|
| `iot_raw` | Raw sensor readings and metadata |
| `iot_alerts` | Threshold-based alerts |
| `iot_analytics` | Aggregates and behavior profiles |

It also uses query-driven denormalization:

- per-sensor raw tables for efficient recent-history lookup
- per-location raw tables for room-centric queries
- per-sensor and per-type analytical aggregates
- room- and type-scoped behavior profile storage for similarity search

---

## Sensor model

The producer simulates a fixed pool of **90 sensors**:

- 30 temperature/humidity sensors
- 30 light sensors
- 30 power sensors

They are distributed across:

- `room_A`
- `room_B`
- `room_C`

Each room contains 10 sensors of each type.

The simulation also includes an **anomaly narrative** to demonstrate the alerting and profiling capabilities for **Cassandra 5 ANN vector similarity search**:

- 9 abnormal sensors in total
- all abnormal sensors are in `room_A`
- 3 abnormal sensors per sensor type
- abnormal sensors spike more often than healthy ones, creating a distinct behavior profile that can be detected through vector similarity search.

---

## Cassandra schema

### Raw keyspace: `iot_raw`

- Replication Strategy: `NetworkTopologyStrategy`.
- Replication Factor: 2 for `dc1`.
- Compaction Strategy: `SizeTieredCompactionStrategy` for raw tables suitable for **append-heavy** workloads.

Main tables:

- `temp_humidity_by_sensor`
- `light_by_sensor`
- `power_by_sensor`
- `readings_by_location`
- `devices_metadata`

These tables support both sensor-centric and room-centric retrieval patterns.
Raw ingestion tables use `SizeTieredCompactionStrategy` because the workload is
append-heavy.

### Alerts keyspace: `iot_alerts`

- Replication Strategy: `NetworkTopologyStrategy`.
- Replication Factor: 2 for `dc1`.
- Compaction Strategy: `SizeTieredCompactionStrategy` for alert tables, which are also append-heavy but have a lower write volume than raw tables.

Main tables:

- `sensor_alerts`
- `alerts_by_location`

These store threshold breaches detected by Spark and expose both sensor-based
and location-based alert queries.

### Analytics keyspace: `iot_analytics`

- **Replication Strategy**: `NetworkTopologyStrategy`.
- **Replication Factor**: 2 for `dc1`.
- **Compaction Strategy**: `LeveledCompactionStrategy` for analytical tables, to improve read predictability on query-facing datasets.


Main tables:

- `sensor_aggregates_30s`
- `aggregates_by_type`
- `sensor_behavior_profiles`

These tables store 30-second event-time aggregates and rolling behavior
profiles. Analytical tables use `LeveledCompactionStrategy` to favor more
predictable read latency.

### Vector-ready profiles

`sensor_behavior_profiles` stores a 3-dimensional vector per sensor:

- mean value
- variance
- spike count

This vector is indexed in Cassandra and is intended for similarity search among
peer sensors in the same room and sensor family.

---

## Streaming logic

The Spark consumer reads from three Kafka topics:

- `sensor_temp_humidity`
- `sensor_light`
- `sensor_power`

It then runs multiple concurrent streaming queries to:

- persist raw readings
- populate denormalized location views
- maintain device metadata
- compute 30-second aggregates
- generate alerts
- refresh sensor behavior profiles periodically on, at most, latest 200 readings per sensor.

For power sensors, `wattage` is derived inside Spark as:

```text
wattage = voltage × amperage
```

---

## Repository structure

```text
iot-cassandra-pipeline/
├── cassandra/
│   └── init.cql
├── docs/
│   └── baseline-architecture.md
├── src/
│   ├── producer.py
│   └── spark_consumer.py
├── docker-compose.yaml
├── requirements.txt
└── README.md
```

The repository is organized by responsibility. Application code lives in `src/`, Cassandra schema initialization scripts live in `cassandra/`, and architectural/project documentation lives in `docs/`. Infrastructure orchestration is defined in the root-level `docker-compose.yaml`, while Python dependencies are listed in `requirements.txt`.

---

## Prerequisites

- Docker and Docker Compose
- Python 3
- Java 17+
- Apache Spark 3.5.x installed locally
- Enough RAM to run Kafka, Cassandra, and Spark comfortably

A machine with **at least 16 GB RAM** is strongly recommended for the full
local setup.

---

## Getting started

### 1. Start the infrastructure

```bash
docker compose up -d
```

This starts:

- Zookeeper
- Kafka
- Kafka topic initialization
- Cassandra cluster
- Cassandra schema initialization
- Schema Registry

### 2. Verify Cassandra cluster health

```bash
docker exec cassandra-1 nodetool status
```

All default nodes should eventually appear as `UN`.

### 3. Start the producer

```bash
python producer.py
```

The producer sends JSON messages continuously to the three Kafka topics.

### 4. Start the Spark consumer

```bash
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1,com.datastax.spark:spark-cassandra-connector_2.12:3.5.1 \
  spark_consumer.py
```

### 5. Verify that data is flowing

Example checks:

```bash
docker exec -it cassandra-1 cqlsh -e "SELECT * FROM iot_raw.devices_metadata LIMIT 10;"
```

```bash
docker exec -it cassandra-1 cqlsh -e "SELECT * FROM iot_alerts.sensor_alerts LIMIT 10;"
```

```bash
docker exec -it cassandra-1 cqlsh -e "SELECT * FROM iot_analytics.sensor_aggregates_30s LIMIT 10;"
```

---

## Notable design choices

- **Three Kafka topics instead of one**: keeps schemas simpler and stream logic clearer.
- **Three Cassandra keyspaces**: separates raw ingestion, alerts, and analytics.
- **Query-first Cassandra modeling**: tables are shaped around actual reads, not normalization.
- **Daily partition bucketing**: prevents unbounded partition growth in time-series tables.
- **Separate alert tables**: enables both per-sensor and per-location alert inspection.
- **Behavior profiles in Cassandra**: prepares the project for vector similarity search directly in the database.

---

## Documentation

| Document | Description |
|---|---|
| [`baseline-architecture.md`](./iot-cassandra-pipeline/docs/baseline-architecture.md) | Detailed explanation of the current baseline architecture |
| [`init.cql`](./iot-cassandra-pipeline/cassandra/init.cql) | Cassandra schema and table design |
| [`producer.py`](./iot-cassandra-pipeline/src/producer.py) | Sensor simulation and Kafka publishing logic |
| [`spark_consumer.py`](./iot-cassandra-pipeline/src/spark_consumer.py) | Streaming logic, alerting, aggregates, and profile computation |

---

## Notes

A few important details about the current version:

- Producer and Spark Consumer runs outside Docker in the current baseline.
- Cassandra replication is currently **RF=2** with `NetworkTopologyStrategy`.

---

## License

MIT License.