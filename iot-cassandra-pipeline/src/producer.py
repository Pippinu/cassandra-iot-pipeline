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
KAFKA_BROKER   = os.environ.get("KAFKA_BROKER", "localhost:9092")
SLEEP_INTERVAL = 1.0  # seconds between batches

TOPICS = {
    "temp_humidity": "sensor_temp_humidity",
    "light":         "sensor_light",
    "power":         "sensor_power",
}

ROOMS          = ["room_A", "room_B", "room_C"]
SENSORS_PER_TYPE_PER_ROOM = 10  # 10 × 3 rooms × 3 types = 90 sensors total

# ============================================================
# Alert thresholds — must match Spark consumer alert logic
# ============================================================
THRESHOLDS = {
    "temperature_high": 40.0,
    "temperature_low":   5.0,
    "humidity_high":    85.0,
    "humidity_low":     20.0,
    "light_high":      900.0,
    "voltage_high":    240.0,
    "amperage_high":    10.0,
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
        round(random.uniform(41.0, 50.0), 2),   # above THRESHOLDS["temperature_high"]
    )
    humidity = _spike(
        round(random.uniform(30.0, 75.0), 2),
        round(random.uniform(86.0, 95.0), 2),   # above THRESHOLDS["humidity_high"]
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
        round(random.uniform(10.1, 15.0), 2),    # above THRESHOLDS["amperage_high"]
    )
    return {"voltage": voltage, "amperage": amperage}


# ============================================================
# Build fixed sensor pool at startup
# Each sensor has a stable UUID assigned once and reused
# across all batches, matching devices_metadata in Cassandra.
# ============================================================
def build_sensor_pool() -> list:
    sensors = []
    generators = {
        "temp_humidity": generate_temp_humidity,
        "light":         generate_light,
        "power":         generate_power,
    }
    for sensor_type, generator in generators.items():
        for room in ROOMS:
            for i in range(SENSORS_PER_TYPE_PER_ROOM):
                sensors.append({
                    "sensor_id":   str(uuid.uuid4()),
                    "sensor_type": sensor_type,
                    "location_id": room,
                    "topic":       TOPICS[sensor_type],
                    "generator":   generator,
                })
    return sensors


# ============================================================
# Kafka producer setup with retry loop
# Retries up to 10 times with 5s delay to handle cases where
# the container starts before Kafka is fully ready.
# ============================================================
def create_kafka_producer(broker: str, retries: int = 10, delay: int = 5) -> KafkaProducer:
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=[broker],
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks=1,                # wait for leader acknowledgment only (CL=ONE equivalent)
                compression_type="snappy",
                batch_size=16384,      # 16 KB batch buffer
                linger_ms=10,          # wait up to 10ms to fill a batch
            )
            print(f"✓ Connected to Kafka broker: {broker}")
            return producer
        except NoBrokersAvailable:
            print(f"  Attempt {attempt}/{retries} — broker not available yet, retrying in {delay}s...")
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
    print(f"Sensors/type : {SENSORS_PER_TYPE_PER_ROOM} per room × {len(ROOMS)} rooms = "
          f"{SENSORS_PER_TYPE_PER_ROOM * len(ROOMS)} per type")
    print(f"Total sensors: {SENSORS_PER_TYPE_PER_ROOM * len(ROOMS) * len(TOPICS)}")
    print(f"Target rate  : ~{SENSORS_PER_TYPE_PER_ROOM * len(ROOMS) * len(TOPICS)} msg/sec")
    print(f"Spike prob.  : {SPIKE_PROBABILITY * 100:.0f}% (threshold-crossing readings)")
    print("=" * 60)

    sensors = build_sensor_pool()
    print(f"✓ Sensor pool initialized: {len(sensors)} sensors")

    producer = create_kafka_producer(KAFKA_BROKER)

    total_sent = 0
    start_time = time.time()

    print("Starting data stream. Press Ctrl+C to stop.")
    print("-" * 60)

    try:
        while True:
            batch_start = time.time()

            for sensor in sensors:
                # Build message — only includes fields relevant to this sensor type
                # (no explicit nulls — omitting fields entirely, per Cassandra best practice)
                message = {
                    "sensor_id":   sensor["sensor_id"],
                    "location_id": sensor["location_id"],
                    "timestamp":   datetime.now(timezone.utc).isoformat(),
                }
                message.update(sensor["generator"]())

                producer.send(sensor["topic"], value=message)
                total_sent += 1

            producer.flush()

            # Print statistics every 10 batches (~10 seconds)
            if (total_sent // len(sensors)) % 10 == 0:
                elapsed = time.time() - start_time
                rate    = total_sent / elapsed if elapsed > 0 else 0
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Sent: {total_sent:7,d} messages | "
                      f"Rate: {rate:6.1f} msg/sec | "
                      f"Uptime: {elapsed:6.0f}s")

            # Sleep to maintain ~1 batch/sec target rate
            batch_duration = time.time() - batch_start
            sleep_time = max(0.0, SLEEP_INTERVAL - batch_duration)
            time.sleep(sleep_time)

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
