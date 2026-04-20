#!/usr/bin/env python3
"""
IoT Sensor Data Producer
Simulates 90 sensors across 3 types and 3 rooms,
publishing JSON messages to 3 Kafka topics at ~90 msg/sec.

Topics:
  sensor_temp_humidity  — 30 sensors (10 per room)
  sensor_light          — 30 sensors (10 per room)
  sensor_power          — 30 sensors (10 per room)

Rooms: room_A, room_B, room_C
"""

import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

# ============================================================
# Configuration — read from environment for Docker compatibility
# ============================================================
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
SLEEP_INTERVAL = 1.0  # seconds between batches

# Code-internal names for sensor types and their corresponding Kafka topics
# You want code-internal names to be concise and consistent, so they can be used as dict keys and in function names.
# You want Kafka topic names to be descriptive and follow a clear naming convention, so they are self-explanatory when viewed in monitoring tools or logs.
TOPICS = {
    "temp_humidity": "sensor_temp_humidity",
    "light": "sensor_light",
    "power": "sensor_power",
}

ROOMS = ["room_A", "room_B", "room_C"]
SENSORS_PER_TYPE_PER_ROOM = 10  # 10 × 3 rooms × 3 types = 90 sensors total

# ============================================================
# Alert thresholds — must match Spark consumer alert logic
# ============================================================
THRESHOLDS = {
    "temperature_high": 40.0,
    "temperature_low": 5.0,
    "humidity_high": 85.0,
    "humidity_low": 20.0,
    "light_high": 900.0,
    "voltage_high": 240.0,
    "amperage_high": 10.0,
}

# ============================================================
# Sensor value generators
# Normal ranges keep values well within thresholds.
# A 3% spike probability occasionally breaches thresholds
# so Spark alert detection fires during the demo.
# ============================================================
SPIKE_PROBABILITY = 0.03  # 3% chance of a threshold-crossing reading


def _spike(normal_val: float, spike_val: float) -> float:
    """Return spike_val with SPIKE_PROBABILITY, otherwise normal_val."""
    return spike_val if random.random() < SPIKE_PROBABILITY else normal_val


def generate_temp_humidity() -> dict:
    temperature = _spike(
        round(random.uniform(18.0, 30.0), 2),
        round(random.uniform(41.0, 50.0), 2),  # above THRESHOLDS["temperature_high"]
    )
    humidity = _spike(
        round(random.uniform(30.0, 75.0), 2),
        round(random.uniform(86.0, 95.0), 2),  # above THRESHOLDS["humidity_high"]
    )
    return {"temperature": temperature, "humidity": humidity}


def generate_light() -> dict:
    light_level = _spike(
        round(random.uniform(100.0, 700.0), 2),
        round(random.uniform(901.0, 1200.0), 2),  # above THRESHOLDS["light_high"]
    )
    return {"light_level": light_level}


def generate_power() -> dict:
    voltage = _spike(
        round(random.uniform(215.0, 235.0), 2),
        round(random.uniform(241.0, 260.0), 2),  # above THRESHOLDS["voltage_high"]
    )
    amperage = _spike(
        round(random.uniform(0.5, 8.0), 2),
        round(random.uniform(10.1, 15.0), 2),  # above THRESHOLDS["amperage_high"]
    )
    return {"voltage": voltage, "amperage": amperage}


# ============================================================
# Build fixed sensor pool at startup
# Each sensor has a stable UUID assigned once and reused
# across all batches, matching devices_metadata in Cassandra.
# ============================================================

# Using uuid5 with a fixed namespace and a name derived from sensor attributes 
# (type, room, index) ensures that each sensor gets a unique but stable UUID that will be the
# same across multiple runs of the producer. 
SENSOR_NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

def stable_sensor_uuid(sensor_type: str, room: str, index: int) -> str:
    sensor_name = f"{sensor_type}:{room}:{index}"
    return str(uuid.uuid5(SENSOR_NAMESPACE, sensor_name))

def build_sensor_pool() -> list:
    sensors = []
    # Each sensor in the pool gets a "generator" key that holds a callable — a function it can invoke later on demand.
    # This allows us to keep the logic for how each sensor type generates its readings encapsulated in one place,
    # and simply call the appropriate generator for each sensor when producing messages.
    generators = {
        "temp_humidity": generate_temp_humidity,
        "light": generate_light,
        "power": generate_power,
    }
    for sensor_type, generator in generators.items():
        for room in ROOMS:
            for i in range(SENSORS_PER_TYPE_PER_ROOM):
                sensors.append(
                    {
                        "sensor_id": stable_sensor_uuid(sensor_type, room, i),
                        "sensor_type": sensor_type,
                        "location_id": room,
                        "description": f"{sensor_type} sensor {i} in {room}",
                        "topic": TOPICS[sensor_type],
                        "generator": generator,
                    }
                )
    return sensors


# ============================================================
# Kafka producer setup with retry loop
# Retries up to 10 times with 5s delay to handle cases where
# the container starts before Kafka is fully ready.
# ============================================================
def create_kafka_producer(
    broker: str, retries: int = 10, delay: int = 5
) -> KafkaProducer:
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                # KafkaProducer expects a list of brokers, even if it's just one
                bootstrap_servers=[broker],
                # The value_serializer converts our Python dict messages to JSON-encoded bytes, which is the format Kafka expects.
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks=1,  # wait for leader acknowledgment only (CL=ONE equivalent)
                # The following settings optimize for high throughput while maintaining reasonable durability guarantees:
                # compression_type="snappy" reduces message size and network overhead, allowing for faster transmission.
                # batch_size=16384 (16 KB) allows the producer to batch multiple messages together before sending, improving throughput.
                # linger_ms=10 allows the producer to wait up to 10 milliseconds to fill a batch before sending,
                # which can further increase batch sizes and throughput without introducing significant latency for our use case.
                compression_type="snappy",
                batch_size=16384,  # 16 KB batch buffer
                linger_ms=10,  # wait up to 10ms to fill a batch
            )
            print(f"✓ Connected to Kafka broker: {broker}")
            return producer
        except NoBrokersAvailable:
            print(
                f"  Attempt {attempt}/{retries} — broker not available yet, retrying in {delay}s..."
            )
            time.sleep(delay)
    print("✗ Could not connect to Kafka after maximum retries. Exiting.")
    sys.exit(1)


# ============================================================
# Main loop
# ============================================================
def main():
    print("=" * 60)
    print("IoT Sensor Producer")
    print("=" * 60)
    print(f"Kafka broker : {KAFKA_BROKER}")
    print(f"Topics       : {', '.join(TOPICS.values())}")
    print(f"Rooms        : {', '.join(ROOMS)}")
    print(
        f"Sensors/type : {SENSORS_PER_TYPE_PER_ROOM} per room × {len(ROOMS)} rooms = "
        f"{SENSORS_PER_TYPE_PER_ROOM * len(ROOMS)} per type"
    )
    print(f"Total sensors: {SENSORS_PER_TYPE_PER_ROOM * len(ROOMS) * len(TOPICS)}")
    print(
        f"Target rate  : ~{SENSORS_PER_TYPE_PER_ROOM * len(ROOMS) * len(TOPICS)} msg/sec"
    )
    print(
        f"Spike prob.  : {SPIKE_PROBABILITY * 100:.0f}% (threshold-crossing readings)"
    )
    print("=" * 60)

    # Build a fixed pool of sensors with stable UUIDs and associated generator functions.
    sensors = build_sensor_pool()
    print(f"✓ Sensor pool initialized: {len(sensors)} sensors")

    # Create Kafka producer with retry logic to handle broker startup timing.
    producer = create_kafka_producer(KAFKA_BROKER)

    total_sent = 0
    start_time = time.time()

    print("Starting data stream. Press Ctrl+C to stop.")
    print("-" * 60)

    # The main loop runs indefinitely, generating and sending messages for all sensors in the pool at a target rate of ~1 batch per second.
    try:
        while True:
            batch_start = time.time()

            for sensor in sensors:
                # Build message — only includes fields relevant to this sensor type
                # (no explicit nulls — omitting fields entirely, per Cassandra best practice for sparse data)
                # "generator"
                message = {
                    "sensor_id": sensor["sensor_id"],
                    "sensor_type": sensor["sensor_type"],
                    "location_id": sensor["location_id"],
                    "description": sensor["description"],
                    "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                }
                # Using update we address the fact that base fields are common across all sensor types, while the specific reading fields vary.
                # Each sensor's "generator" function produces a dict of the appropriate reading fields for that
                # sensor type, which we then merge into the base message dict before sending to Kafka.
                message.update(sensor["generator"]())

                # Send message to Kafka topic corresponding to the sensor type.
                producer.send(sensor["topic"], value=message)
                total_sent += 1

            producer.flush()

            # Print statistics every 10 batches (~10 seconds)
            if (total_sent // len(sensors)) % 10 == 0:
                elapsed = time.time() - start_time
                rate = total_sent / elapsed if elapsed > 0 else 0
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"Sent: {total_sent:7,d} messages | "
                    f"Rate: {rate:6.1f} msg/sec | "
                    f"Uptime: {elapsed:6.0f}s"
                )

            # Sleep to maintain ~1 batch/sec target rate
            batch_duration = time.time() - batch_start
            sleep_time = max(0.0, SLEEP_INTERVAL - batch_duration)
            time.sleep(sleep_time)

    # Graceful shutdown on Ctrl+C, with final statistics summary.
    except KeyboardInterrupt:
        print("" + "-" * 60)
        print("Shutting down producer...")
        producer.flush()
        producer.close()
        elapsed = time.time() - start_time
        print(f"final statistics:")
        print(f"  Total messages sent : {total_sent:,}")
        print(f"  Total duration      : {elapsed:.1f}s")
        print(f"  Average rate        : {total_sent / elapsed:.1f} msg/sec")
        print("✓ Producer stopped cleanly.")


if __name__ == "__main__":
    main()
