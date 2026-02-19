# Real-Time IoT Analytics Pipeline

A production-like **real-time IoT pipeline** that ingests sensor data via 
**Kafka**, processes it with **Spark Structured Streaming**, and stores it 
in a **3-node Apache Cassandra cluster** — built to demonstrate distributed 
systems concepts including tunable consistency, schema enforcement, and 
compaction strategies.

> Built as a learning project. Every architectural decision is documented
> in [`/docs`](./docs).

---

## Architecture

```text
100 IoT Sensors (Python + Faker)
        │   ~100 events/sec · Avro binary
        ▼
Confluent Schema Registry ◄──── schema enforcement
        │
        ▼
Apache Kafka (sensor-events topic)
        ▼
Spark Structured Streaming
   ├─ Raw events  → Cassandra.sensor_events      (CL=ONE,    SizeTiered)
   └─ Hourly aggs → Cassandra.hourly_aggregates  (CL=QUORUM, Leveled)
        ▼
3-Node Cassandra Cluster (RF=3, 16 vnodes)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Simulation | Python 3.10, Faker |
| Serialization | Apache Avro, Confluent Schema Registry |
| Streaming | Apache Kafka (Confluent 7.5.0) |
| Processing | Apache Spark 3.5 (PySpark) |
| Storage | Apache Cassandra 4.1 |
| Orchestration | Docker + docker-compose 1.29 |

---

## Repository Structure

```text
.
├── docker-compose.yml
├── cassandra/
│   └── init.cql
├── schemas/
│   ├── SensorEvent.avsc
│   └── HourlyAggregate.avsc
├── src/
│   ├── producer.py
│   └── spark_consumer.py
├── monitoring/
│   ├── monitor.sh
│   ├── cassandra_auto_flush.sh
│   └── compaction_monitor.sh
├── docs/
│   ├── data-contracts.md
│   └── ...
└── README.md
```

---

## Prerequisites

- Docker 24.x + docker-compose 1.29.x
- Python 3.10+
- Apache Spark 3.5.x (local install)
- Java 17+
- **16 GB RAM minimum** — the pipeline runs multiple JVM-based services
  concurrently (Cassandra × 3, Kafka, Spark)

---

## Getting Started

**1. Start infrastructure**
```bash
docker-compose up -d
# Wait ~2 minutes for Cassandra cluster to form
docker exec cassandra-1 nodetool status   # all nodes should show UN
```

**2. Create schema**
```bash
docker cp cassandra/init.cql cassandra-1:/init.cql
docker exec cassandra-1 cqlsh -f /init.cql
```

**3. Start the producer** (registers Avro schema + sends events)
```bash
cd src && python3 producer.py
```

**4. Start the consumer** (in a new terminal)
```bash
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,\
com.datastax.spark:spark-cassandra-connector_2.12:3.5.0,\
org.apache.spark:spark-avro_2.12:3.5.0 \
  --conf spark.cassandra.connection.host=localhost \
  --conf spark.cassandra.connection.port=9042 \
  src/spark_consumer.py
```

**5. Verify data is flowing**
```bash
docker exec cassandra-1 cqlsh -e \
  "SELECT COUNT(*) FROM iot_analytics.sensor_events;"
```

---

## Documentation

| Document | Description |
|---|---|
| [`docs/data-contracts.md`](./iot-cassandra-pipeline/docs/data-contracts.md) | Avro + Schema Registry implementation, schema evolution, BACKWARD compatibility |

---

## License

MIT License — feel free to use this as a reference or starting point.
