# Docker Compose Explained — IoT Sensor Pipeline

This document explains every service, environment variable, and healthcheck in the `docker-compose.yml` for the IoT sensor pipeline project.

---

## Architecture Overview

The compose file defines **8 services** that start in a strict dependency order:

```
zookeeper → kafka → kafka-init → producer
                              → cassandra-1 → cassandra-2
                                           → cassandra-3
                                           → spark-consumer
```

All services communicate on an isolated bridge network named `iot-network`, using container names as hostnames (e.g., `kafka:29092`, `cassandra-1:9042`).

---

## Service: `zookeeper`

Zookeeper is a distributed coordination service required by Kafka to manage broker metadata, leader election, and topic configuration. In Kafka versions prior to KRaft mode, Zookeeper is mandatory.

### Environment Variables

| Key | Value | Explanation |
|-----|-------|-------------|
| `ZOOKEEPER_CLIENT_PORT` | `2181` | The TCP port on which Zookeeper listens for client connections. Kafka connects to this port to register itself and store broker metadata. |
| `ZOOKEEPER_TICK_TIME` | `2000` | The basic time unit in milliseconds used by Zookeeper for heartbeats and session timeouts. A tick of 2000ms means session timeouts are measured in multiples of 2 seconds. |

### Healthcheck

```yaml
test: ["CMD-SHELL", "echo ruok | nc localhost 2181 | grep imok"]
```

Sends the Zookeeper four-letter command `ruok` ("are you ok?") via netcat to port 2181. A healthy Zookeeper responds with `imok`. If the response is anything else or the connection fails, the healthcheck fails. Kafka's `depends_on` waits for this check to pass before starting.

---

## Service: `kafka`

The Kafka broker is the central message bus. It receives messages from the producer on 3 topics and delivers them to the Spark consumer. The Confluent Platform image is used (`confluentinc/cp-kafka:7.5.0`) as it includes all necessary scripts like `kafka-topics.sh`.

### Environment Variables

| Key | Value | Explanation |
|-----|-------|-------------|
| `KAFKA_BROKER_ID` | `1` | Unique integer identifier for this broker within the cluster. Since this is a single-broker setup, it is set to `1`. In a multi-broker cluster each broker would have a distinct ID. |
| `KAFKA_ZOOKEEPER_CONNECT` | `zookeeper:2181` | Address of the Zookeeper instance Kafka registers with. Uses the container name `zookeeper` as hostname (resolved via `iot-network`) and port `2181`. |
| `KAFKA_ADVERTISED_LISTENERS` | `PLAINTEXT://kafka:29092, PLAINTEXT_HOST://localhost:9092` | Defines two listener addresses Kafka advertises to clients. `PLAINTEXT://kafka:29092` is used by internal Docker services (producer, Spark) that communicate via the `iot-network`. `PLAINTEXT_HOST://localhost:9092` is exposed on the host machine for external tools (e.g., `kafka-console-consumer` run directly on the host). |
| `KAFKA_LISTENER_SECURITY_PROTOCOL_MAP` | `PLAINTEXT:PLAINTEXT, PLAINTEXT_HOST:PLAINTEXT` | Maps each named listener to a security protocol. Both use `PLAINTEXT` (no TLS/SASL), which is appropriate for a local development and demonstration environment. |
| `KAFKA_INTER_BROKER_LISTENER_NAME` | `PLAINTEXT` | Specifies which listener brokers use to communicate with each other. In a multi-broker cluster this matters for replication traffic; here it just designates the internal listener. |
| `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR` | `1` | Kafka internally stores consumer group offsets in a special topic (`__consumer_offsets`). This sets its replication factor to `1`. Since there is only one broker, a higher value would be invalid. |
| `KAFKA_AUTO_CREATE_TOPICS_ENABLE` | `"false"` | Disables automatic topic creation when a producer or consumer references a topic that does not exist. Topics are instead created explicitly by the `kafka-init` service with controlled partition counts. This prevents accidental topic creation with wrong configurations. |
| `KAFKA_HEAP_OPTS` | `"-Xmx512M -Xms256M"` | Sets the JVM heap size for the Kafka broker process. `Xms256M` is the initial allocation, `Xmx512M` is the maximum. Keeps memory usage predictable on a laptop running the full pipeline. |

### Healthcheck

```yaml
test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list"]
```

Runs `kafka-topics.sh` against the broker and lists all topics. This command succeeds only if the broker is fully started and accepting connections. It is stricter than just checking if the port is open — it verifies the broker is actually functional. All services that depend on Kafka (`kafka-init`, `producer`, `spark-consumer`) wait for this check to pass.

---

## Service: `kafka-init`

A one-shot service that creates the three sensor topics with explicit partition counts, then exits. It uses `restart: "no"` so it never restarts after completing.

**Why explicit topic creation?** With `AUTO_CREATE_TOPICS_ENABLE: false`, topics must be pre-created. Doing it in a dedicated init service guarantees topics exist with 3 partitions each before the producer or Spark consumer start — 3 partitions allows Spark to parallelize consumption across 3 executors, one per partition.

The service uses `condition: service_completed_successfully` in the `depends_on` blocks of `producer` and `spark-consumer`, meaning those services wait not just for `kafka-init` to start, but for it to **finish and exit with code 0**.

---

## Service: `cassandra-1`

The seed node of the Cassandra cluster. A seed node is the well-known entry point that new nodes contact when joining the ring. `cassandra-1` is the only node that exposes port `9042` to the host, allowing direct `cqlsh` access from the terminal.

The `init.cql` file is mounted at `/docker-entrypoint-initdb.d/init.cql`. The official Cassandra Docker image automatically executes any `.cql` files found in that directory on first startup, creating all keyspaces and tables.

### Environment Variables

| Key | Value | Explanation |
|-----|-------|-------------|
| `CASSANDRA_CLUSTER_NAME` | `IoT-Cluster` | Logical name of the Cassandra cluster. All nodes in the same cluster must share this name — nodes with a different cluster name will refuse to join. |
| `CASSANDRA_DC` | `dc1` | The datacenter name for this node, used by `GossipingPropertyFileSnitch` and `NetworkTopologyStrategy`. The keyspaces use `'dc1': 2` in their replication settings, so this value must match exactly. |
| `CASSANDRA_RACK` | `rack1` | The rack name within the datacenter. Used for rack-aware replica placement. All three nodes are on `rack1` since this is a single-machine simulation — in production, nodes would be spread across physical racks. |
| `CASSANDRA_ENDPOINT_SNITCH` | `GossipingPropertyFileSnitch` | Determines how Cassandra discovers datacenter and rack topology. `GossipingPropertyFileSnitch` is the recommended production snitch — it reads topology from a local file and propagates it via gossip. Required for `NetworkTopologyStrategy` to work correctly. `SimpleSnitch` (the default) does not support datacenter-aware replication. |
| `CASSANDRA_SEEDS` | `cassandra-1` | Comma-separated list of seed node hostnames. Seed nodes are the bootstrap contact points for new nodes joining the ring. Only `cassandra-1` is the seed; nodes 2 and 3 contact it to discover the ring topology. A node should not list itself as a seed unless it is the only seed (as here). |
| `MAX_HEAP_SIZE` | `512M` | Maximum JVM heap for the Cassandra process. 512MB is the minimum viable value for a demo; production nodes typically use 8–16GB. |
| `HEAP_NEWSIZE` | `200M` | Size of the JVM young generation (Eden + Survivor spaces). Cassandra recommends setting this to roughly 1/4 of `MAX_HEAP_SIZE`. A larger young generation reduces minor GC frequency, which matters for write-heavy workloads. |

### Healthcheck

```yaml
test: ["CMD-SHELL", "nodetool status | grep -E '^UN\\s+' | grep -v grep"]
```

Runs `nodetool status` and searches for lines starting with `UN` — meaning **U**p and **N**ormal. A node in any other state (e.g., `DN` = Down/Normal, `UJ` = Up/Joining) will not match and the check will fail. The `-v grep` removes any false matches from the grep process itself. This is a stricter check than just verifying the port is open — it confirms the node has fully joined the ring and is operational.

---

## Services: `cassandra-2` and `cassandra-3`

Both are non-seed nodes with identical environment variables to `cassandra-1` (same cluster, DC, rack, and seed address). They differ only in startup timing.

### Startup Delay Command

```yaml
# cassandra-2
command: /bin/bash -c "sleep 30 && /usr/local/bin/docker-entrypoint.sh cassandra -f"

# cassandra-3
command: /bin/bash -c "sleep 60 && /usr/local/bin/docker-entrypoint.sh cassandra -f"
```

The sleep delays are critical. When multiple Cassandra nodes attempt to join a ring simultaneously, they can race to claim the same token ranges, corrupting ring state. The delays stagger the joins:

- `cassandra-2` waits 30 seconds after `cassandra-1` is healthy before starting
- `cassandra-3` waits 60 seconds, giving `cassandra-2` time to complete its own join before the third node arrives

Both nodes depend on `cassandra-1: condition: service_healthy`, so the clock on their sleep starts only after node 1 is fully up.

### Healthchecks (nodes 2 and 3)

```yaml
test: ["CMD-SHELL", "nodetool status | grep -E '^UN\\s+' | wc -l | grep -qv '^0'"]
```

This is slightly different from node 1's check. It counts the number of `UN` lines in `nodetool status` and verifies the count is not zero. This confirms the node can see at least one healthy member in the cluster (including itself), proving it has successfully joined the ring.

---

## Service: `producer`

The Python sensor simulator. It generates readings for 90 sensors across 3 types and 3 rooms, publishing JSON messages to 3 Kafka topics at approximately 90 messages/second.

Built from `Dockerfile.producer` — a lightweight Python image with only `kafka-python` as a dependency.

### Environment Variables

| Key | Value | Explanation |
|-----|-------|-------------|
| `KAFKA_BROKER` | `kafka:29092` | Address of the Kafka broker as seen from inside the `iot-network`. Uses the internal `PLAINTEXT` listener on port `29092`, not the host-facing `9092`. The producer reads this at startup instead of having `localhost:9092` hardcoded. |

### Dependency Logic

```yaml
depends_on:
  kafka:
    condition: service_healthy
  kafka-init:
    condition: service_completed_successfully
```

Two conditions must be met: the broker must be healthy **and** the topic initialization job must have completed successfully. This guarantees the three sensor topics exist before the producer attempts to publish.

---

## Service: `spark-consumer`

The PySpark streaming application. It consumes from all 3 Kafka topics simultaneously, fans out into 5 processing streams, and writes to 7 Cassandra tables across 3 keyspaces.

Built from `Dockerfile.spark` — a heavier image containing PySpark, the Spark-Cassandra connector JARs, and the Kafka Spark connector JARs.

### Environment Variables

| Key | Value | Explanation |
|-----|-------|-------------|
| `KAFKA_BROKER` | `kafka:29092` | Internal Kafka broker address, identical to the producer. Spark reads from the same internal listener. |
| `CASSANDRA_HOST` | `cassandra-1` | Hostname of the Cassandra contact point. Spark uses this as the initial connection node — once connected, the Cassandra driver discovers all other nodes via gossip automatically. Only node 1 needs to be specified. |
| `CASSANDRA_PORT` | `"9042"` | Standard CQL native transport port. Quoted as a string because Docker Compose environment values are strings. The Spark-Cassandra connector accepts it as a string configuration value. |

### Checkpoint Volume

```yaml
volumes:
  - spark-checkpoints:/tmp/spark-checkpoints
```

Spark Structured Streaming requires a checkpoint directory for each stateful stream. Checkpoints store Kafka offset progress and window aggregation state. Mounting this as a named Docker volume ensures checkpoint state survives container restarts — without it, Spark would reprocess all Kafka messages from the beginning on every restart.

### Dependency Logic

```yaml
depends_on:
  kafka:
    condition: service_healthy
  kafka-init:
    condition: service_completed_successfully
  cassandra-1:
    condition: service_healthy
```

Three conditions: Kafka healthy, topics created, and Cassandra node 1 healthy. The Spark consumer connects to both systems at startup, so both must be ready. Note that nodes 2 and 3 are not in the dependency list — the Cassandra driver discovers them automatically after connecting to node 1. Starting the consumer before all 3 nodes are up is acceptable; the driver will simply not route traffic to nodes still joining.

---

## Volumes

| Volume | Used By | Purpose |
|--------|---------|---------|
| `cassandra-data-1` | `cassandra-1` | Persists Cassandra data, commitlog, and schema for node 1. Without this, all data is lost on container restart. |
| `cassandra-data-2` | `cassandra-2` | Same for node 2. Each node must have its own volume — sharing a volume between nodes would corrupt both. |
| `cassandra-data-3` | `cassandra-3` | Same for node 3. |
| `spark-checkpoints` | `spark-consumer` | Persists Spark streaming checkpoint state across restarts. |

---

## Network: `iot-network`

All services share a single bridge network. Docker's embedded DNS resolves container names to their internal IPs, which is why services can reach each other by name (`kafka`, `cassandra-1`, `zookeeper`) without any manual IP configuration. No service is accessible from outside the host machine except via explicitly mapped ports (`9092` for Kafka and `9042` for Cassandra node 1).

