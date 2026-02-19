# Data Contracts Implementation: Schema Registry + Avro

## Overview

This document describes the Data Contracts feature introduced to the IoT
streaming pipeline. The change affects the serialization layer between the
producer and the consumer, adding schema enforcement, binary serialization,
and a centralized schema registry.

---

## What is a Data Contract?

A **Data Contract** is a formal agreement between a data producer and a data consumer that defines the structure, format, and quality of the data being exchanged. In traditional pipelines, this agreement is often "implicit" (stored only in the developer's mind or scattered across code snippets), which leads to fragility. By implementing a formal Data Contract, we transform this agreement into an "explicit" and executable part of the architecture.

In this project, the Data Contract is composed of three core pillars:

1. **The Schema (Syntax):** A strictly defined Avro specification (`.avsc`) that dictates exactly which fields are present, their data types (e.g., `float`, `long`, `string`), and whether they are optional or required.
2. **The Registry (Enforcement):** A centralized gatekeeper (Schema Registry) that ensures no data enters the system unless it matches the agreed-upon schema. It acts as the "Single Source of Truth" for the entire pipeline.
3. **The Evolution Policy (Semantics):** A set of rules (BACKWARD compatibility) that defines how the contract can change over time. This ensures that when the producer evolves (e.g., adding a new sensor metric), it does not break existing downstream consumers or analytics dashboards.

By moving to a **Contract-First Architecture**, we shift the responsibility of data validation from "runtime debugging" to "system design," ensuring the pipeline is resilient, self-documenting, and ready for professional production environments.

## What Changed

### Before

The pipeline used plain JSON serialization with no schema enforcement:

- The producer serialized messages with `json.dumps()` and sent raw UTF-8
  strings to Kafka
- The consumer parsed messages with `from_json()` against a `StructType`
  schema hardcoded in Python

    ```python
    event_schema = StructType([
        StructField("device_id",   StringType(), False),
        StructField("device_name", StringType(), True),
        StructField("timestamp",   LongType(),   False),
        StructField("temperature", FloatType(),  False),
        StructField("humidity",    FloatType(),  False),
        StructField("location",    StringType(), True)
    ])
    ```
- No contract existed between producer and consumer — the two schemas were
  defined independently and **could silently diverge**
- Any producer code change (renamed field, changed type, removed field) would
  cause the consumer to **silently produce nulls or fail at runtime** with no
  early warning

### After

The pipeline uses **Apache Avro** binary serialization enforced by a
**Confluent Schema Registry**:

- The Avro schema is defined once in `.avsc` files under `schemas/` and
  registered in the Schema Registry on producer startup
- The producer serializes every message against that registered schema —
  a message that does not conform to the schema is rejected before it
  reaches Kafka
  - Enforcement is **client-side**: ***AvroSerializer(event, ctx)*** calls ***fastavro*** to validate and encode the message before producer.produce() is invoked, a malformed message raises a serialization exception and never enters the Kafka producer buffer. 
  - The Schema Registry is contacted only once at startup to register the schema and obtain its ID; it is not involved in per-message validation.

- The consumer fetches the schema from the Registry at startup and uses
  it to deserialize messages — it is always guaranteed to read what the
  producer wrote
- Schema evolution is governed by a compatibility policy (BACKWARD) enforced
  by the Registry, preventing breaking changes from being deployed silently

### Note on BACKWARD compatibility policy

"***BACKWARD***" is one of several compatibility modes the Schema Registry supports. The name refers to the direction of compatibility: new schema, old consumer. 

Specifically it answers the question: "*if I update the schema and deploy a new producer, can my existing consumer — which has not been updated yet — still read the new messages?*"
- If the answer is **yes**, the schema change is BACKWARD compatible and the Registry accepts it. 
- If the answer is **no**, it is rejected.

#### Why this direction matters in a streaming pipeline:

In a batch system you can coordinate deployments — take everything down, migrate, bring everything back up. In a streaming pipeline you cannot do that cleanly. The producer and consumer are independent processes that run continuously, and you will almost always deploy them at different times. BACKWARD compatibility is the guarantee that you can safely deploy a new producer before updating the consumer, without breaking the live stream.

#### Why "*required field without a default*" is the classic breaking change:

Imagine the current schema has 6 fields and you add a 7th required field battery_level with no default. 
- The new producer starts writing 7-field messages. 
- The old consumer tries to deserialize them expecting 6 fields, encounters the unknown required field, has no default to fall back to, and **crashes** or produces **corrupt data**. 

The Registry catches this at registration time and rejects it — you never get to the point of writing broken messages into Kafka.

If instead you add battery_level as optional with default: null, the old consumer deserializes new messages fine — it simply assigns null to the field it does not know about yet. That is BACKWARD compatible and the Registry accepts it.

In one sentence, BACKWARD compatibility means the consumer can always be one schema version behind the producer — which is exactly the deployment flexibility a live pipeline needs.

---

## New Components

### `schemas/SensorEvent.avsc`
Avro schema for raw sensor readings. 
- Defines the contract for all messages produced to the `sensor-events` Kafka topic. 
- Fields map directly to the `sensor_events` Cassandra table and the original JSON structure.

### `schemas/HourlyAggregate.avsc`
Avro schema for pre-computed hourly aggregates written by Spark to the `hourly_aggregates` Cassandra table.

> **Note:** The Spark consumer does not deserialize messages via this schema —
> aggregates are computed internally by Spark but are never consumed from Kafka, which only consume raw sensor events. \
> The schema exists to document the structure of the aggregated records as a
> contract for any future downstream consumer of the `hourly_aggregates` table.


### Schema Registry (`docker-compose.yml`)
A new `schema-registry` service (*Confluent Platform 7.5.0*) runs alongside Kafka. It stores all registered schemas, assigns each a numeric ID, and enforces compatibility rules on every new schema version submitted.

It communicates with Kafka over the internal Docker network on port `29092` and is reachable from the host at `http://localhost:8081`.

---

## Modified Components

### `producer.py`
- Replaced `kafka-python` with `confluent-kafka`, which has **native** Schema Registry integration.
- On startup, connects to the Schema Registry and registers `SensorEvent.avsc` under subject `sensor-events-value` (*Confluent TopicNameStrategy*).
- Serializes every message as Avro binary using `AvroSerializer`, which prepends a 5-byte Confluent wire-format header (magic byte + schema ID)
  to each message
- All producer settings (throughput, batching, compression, acks) are
  unchanged

### `spark_consumer.py`
- Replaced `from_json()` + hardcoded `StructType` with `from_avro()` +
  schema fetched live from the Schema Registry at startup
- Strips the 5-byte Confluent wire-format header from each Kafka message
  value before passing it to `from_avro()`, which expects raw Avro binary
- Both Cassandra write streams, consistency levels, watermark, checkpoint
  paths, and trigger intervals are unchanged

### `requirements.txt`
Two new dependencies:
- `confluent-kafka==2.3.0` — Kafka producer client with Schema Registry
  and Avro serialization support
- `fastavro==1.9.4` — Avro serialization backend used internally by
  `confluent-kafka`

### `spark-submit` command
Added `org.apache.spark:spark-avro_2.12:3.5.0` to `--packages` to enable
Spark's `from_avro()` function.

---

## Why This Is Better

### 1. Schema enforcement at the boundary
With JSON, a producer bug (typo in a field name, wrong data type, missing
required field) reaches the consumer silently. With Avro + Schema Registry,
the producer's `AvroSerializer` validates every message against the registered
schema before it is sent. Invalid messages raise a serialization error on the
producer side, immediately and explicitly.

### 2. Single source of truth
The schema lives in one place — the Schema Registry — and both the producer
and consumer depend on it. There is no longer a risk of the producer's mental
model of the message and the consumer's `StructType` drifting apart over time
without anyone noticing.

### 3. Binary efficiency
Avro binary encoding is significantly more compact than JSON. The JSON
representation of a sensor event is approximately 160–200 bytes. The Avro
binary representation of the same event is approximately 60–80 bytes —
a reduction of roughly 60%. At 100 messages/second this is modest, but the
principle scales directly with throughput.

### 4. Governed schema evolution
The Schema Registry enforces a **BACKWARD** compatibility policy by default.
This means:

- **ALLOWED**: Adding an optional field with a default value.
- **ALLOWED**: Removing a field with a default value.
- **REJECTED**: Adding a required field without a default.
- **REJECTED**:  Renaming or removing a field that has no default.

This makes schema changes an explicit, reviewed operation rather than an
implicit side effect of a code change.

### 5. Self-documenting messages
Every message in Kafka carries a schema ID in its header. Any consumer,
debugging tool, or audit process can look up the exact schema that was used
to write any given message. With raw JSON, the schema was implicit and
existed only in the producer's source code at the time of writing.

---

## Schema Evolution: How To Add a New Field

The following example shows how to add an optional `battery_level` field to
`SensorEvent.avsc` in a BACKWARD-compatible way.

### Step 1 — Update the schema file

Add the new field with a `null` default to `schemas/SensorEvent.avsc`:

```json
{
  "name": "battery_level",
  "type": ["null", "float"],
  "default": null,
  "doc": "Battery charge level as a percentage (0.0–100.0)"
}
```

The `default: null` is **mandatory**. 
- Without it, the Schema Registry will reject the new version because old consumers reading messages that do not contain the field would have no value to fall back to.

### Step 2 — Register the new version

The producer automatically registers the updated schema on next startup **OR** you can also register it manually:

```bash
curl -X POST http://localhost:8081/subjects/sensor-events-value/versions \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  -d "{\"schema\": $(cat schemas/SensorEvent.avsc | jq -Rs .)}"
```

### Step 3 — Verify compatibility was accepted

```bash
# List all registered versions for this subject
curl http://localhost:8081/subjects/sensor-events-value/versions

# Fetch the new version
curl http://localhost:8081/subjects/sensor-events-value/versions/latest
```

### Step 4 — Update the producer

Add `battery_level` to the event dictionary in `producer.py`:

```python
event = {
    ...
    "battery_level": round(fake.pyfloat(min_value=0.0, max_value=100.0, right_digits=1), 1)
}
```

### What happens to the existing consumer

Because the field has `default: null`, the existing consumer continues to work without any changes. 
- Messages produced before the schema change will have `battery_level` resolved to `null` by the Avro deserializer. 
- The consumer can be updated to use the new field at its own pace.

---

## Demonstration: Rejecting a Breaking Change

To verify that the Registry enforces BACKWARD compatibility, attempt to
register a schema with a new **required** field (no default):

```bash
curl -X POST http://localhost:8081/compatibility/subjects/sensor-events-value/versions/latest \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  -d '{
    "schema": "{\"type\":\"record\",\"name\":\"SensorEvent\",\"namespace\":\"com.iot.pipeline\",\"fields\":[{\"name\":\"device_id\",\"type\":\"string\"},{\"name\":\"device_name\",\"type\":[\"null\",\"string\"],\"default\":null},{\"name\":\"timestamp\",\"type\":\"long\"},{\"name\":\"temperature\",\"type\":\"float\"},{\"name\":\"humidity\",\"type\":\"float\"},{\"name\":\"location\",\"type\":[\"null\",\"string\"],\"default\":null},{\"name\":\"battery_level\",\"type\":\"float\"}]}"
  }'
```

The Registry will return:

```json
{
  "is_compatible": false
}
```

The new version is rejected. The producer cannot be deployed with a breaking
schema change until the consumer is updated first — this is exactly the
guarantee a data contract provides.

---

## Startup Order

```bash
# 1. Bring up infrastructure
docker-compose up -d zookeeper kafka schema-registry

# 2. Verify Schema Registry is ready (~15 seconds)
curl http://localhost:8081/subjects    # returns []

# 3. Bring up Cassandra cluster
docker-compose up -d cassandra-1
# wait for healthy status, then:
docker-compose up -d cassandra-2 cassandra-3

# 4. Start producer (registers schema on first run)
python producer.py

# ⚠️ If you previously ran the JSON-based pipeline, clear old checkpoints first.
# The schema change makes them incompatible with the new Avro stream.
rm -rf /tmp/spark-checkpoint-raw /tmp/spark-checkpoint-agg

# 5. Start consumer (fetches schema from Registry)
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,\
com.datastax.spark:spark-cassandra-connector_2.12:3.5.0,\
org.apache.spark:spark-avro_2.12:3.5.0 \
  --conf spark.cassandra.connection.host=localhost \
  --conf spark.cassandra.connection.port=9042 \
  spark_consumer.py
```

> **Note:** The producer must start before the consumer on the first run.
> The consumer calls the Schema Registry at startup to fetch the schema,
> which is only registered once the producer has run at least once.

---

## Verification

```bash
# Check registered subjects
curl http://localhost:8081/subjects
# Expected: ["sensor-events-value"]

# Inspect the registered schema
curl http://localhost:8081/subjects/sensor-events-value/versions/latest

# Confirm Avro binary in Kafka (messages are NOT human-readable JSON)
docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic sensor-events \
  --max-messages 1

# Confirm Spark reads correct types
# Add df.printSchema() temporarily in spark_consumer.py after from_avro —
# expected output:
# root
#  |-- device_id: string
#  |-- device_name: string (nullable)
#  |-- timestamp: long
#  |-- temperature: float
#  |-- humidity: float
#  |-- location: string (nullable)
#  |-- event_time: timestamp
```
