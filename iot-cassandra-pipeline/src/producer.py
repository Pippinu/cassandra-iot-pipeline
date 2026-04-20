#!/usr/bin/env python3
"""
IoT Sensor Data Producer

Simulates 90 sensors across 3 types and 3 rooms,
publishing JSON messages to 3 Kafka topics at ~90 msg/sec.

Topics:
- sensor_temp_humidity : 30 sensors (10 per room)
- sensor_light         : 30 sensors (10 per room)
- sensor_power         : 30 sensors (10 per room)

Rooms:
- room_A
- room_B
- room_C

Anomaly model:
- Healthy sensors: very low spike probability
- Abnormal sensors: higher spike probability
- 9 abnormal sensors total, all clustered in room_A:
  - 3 temp_humidity
  - 3 light
  - 3 power

This supports the demo narrative:
alerts cluster in one room, then ANN over same-room same-type behavior
profiles identifies other similarly abnormal sensors.
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
# Configuration
# ============================================================

KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
SLEEP_INTERVAL = 1.0  # seconds between batches

TOPICS = {
    "temp_humidity": "sensor_temp_humidity",
    "light": "sensor_light",
    "power": "sensor_power",
}

ROOMS = ["room_A", "room_B", "room_C"]
SENSORS_PER_TYPE_PER_ROOM = 10  # 10 × 3 rooms × 3 types = 90 total sensors

# ============================================================
# Thresholds
# Must stay aligned with spark_consumer.py
# ============================================================

THRESHOLDS = {
    "temperature_high": 40.0,
    "temperature_low": 5.0,
    "humidity_high": 85.0,
    "humidity_low": 20.0,
    "light_high": 900.0,
    "voltage_high": 240.0,
    "amperage_high": 10.0,
    "wattage_high": 2000.0,
}

# ============================================================
# Anomaly configuration
# ============================================================

NORMAL_SPIKE_PROBABILITY = 0.002   # 0.2%
ABNORMAL_SPIKE_PROBABILITY = 0.08  # 8%

ABNORMAL_ROOM = "room_A"
ABNORMAL_SENSOR_INDEXES = {0, 1, 2}  # 3 abnormal sensors per type in room_A

# ============================================================
# Stable sensor IDs
# ============================================================

SENSOR_NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


def stable_sensor_uuid(sensor_type: str, room: str, index: int) -> str:
    sensor_name = f"{sensor_type}:{room}:{index}"
    return str(uuid.uuid5(SENSOR_NAMESPACE, sensor_name))


def is_abnormal_sensor(sensor_type: str, room: str, index: int) -> bool:
    return room == ABNORMAL_ROOM and index in ABNORMAL_SENSOR_INDEXES


# ============================================================
# Value generation helpers
# ============================================================

def should_spike(probability: float) -> bool:
    return random.random() < probability


def generate_temp_humidity(sensor: dict) -> dict:
    """
    Humidifier-malfunction narrative:
    - humidity is the main abnormal signal
    - temperature remains mostly stable
    """
    spike_probability = sensor["spike_probability"]

    # Keep temperature mostly normal so the room story is about humidity.
    temperature = round(random.uniform(18.0, 30.0), 2)

    # Very rare temperature spikes even for abnormal sensors.
    if should_spike(0.001):
        temperature = round(random.uniform(41.0, 46.0), 2)

    humidity = round(random.uniform(30.0, 75.0), 2)
    if should_spike(spike_probability):
        humidity = round(random.uniform(86.0, 95.0), 2)

    return {
        "temperature": temperature,
        "humidity": humidity,
    }


def generate_light(sensor: dict) -> dict:
    spike_probability = sensor["spike_probability"]

    light_level = round(random.uniform(100.0, 700.0), 2)
    if should_spike(spike_probability):
        light_level = round(random.uniform(901.0, 1200.0), 2)

    return {
        "light_level": light_level,
    }


def generate_power(sensor: dict) -> dict:
    """
    For abnormal power sensors, spike both voltage and amperage together
    so:
    - Spark alert logic can fire on voltage/amperage
    - Spark-derived wattage becomes clearly abnormal too
    """
    spike_probability = sensor["spike_probability"]

    if should_spike(spike_probability):
        voltage = round(random.uniform(241.0, 255.0), 2)
        amperage = round(random.uniform(10.5, 14.0), 2)
    else:
        voltage = round(random.uniform(215.0, 235.0), 2)
        amperage = round(random.uniform(0.5, 8.0), 2)

    return {
        "voltage": voltage,
        "amperage": amperage,
    }


# ============================================================
# Build fixed sensor pool
# ============================================================

def build_sensor_pool() -> list:
    sensors = []

    generators = {
        "temp_humidity": generate_temp_humidity,
        "light": generate_light,
        "power": generate_power,
    }

    for sensor_type, generator in generators.items():
        for room in ROOMS:
            for i in range(SENSORS_PER_TYPE_PER_ROOM):
                abnormal = is_abnormal_sensor(sensor_type, room, i)
                spike_probability = (
                    ABNORMAL_SPIKE_PROBABILITY if abnormal else NORMAL_SPIKE_PROBABILITY
                )

                health_label = "abnormal" if abnormal else "normal"

                sensors.append(
                    {
                        "sensor_id": stable_sensor_uuid(sensor_type, room, i),
                        "sensor_type": sensor_type,
                        "location_id": room,
                        "description": f"{sensor_type} sensor {i} in {room} ({health_label})",
                        "topic": TOPICS[sensor_type],
                        "generator": generator,
                        "abnormal": abnormal,
                        "spike_probability": spike_probability,
                        "sensor_index": i,
                    }
                )

    return sensors


# ============================================================
# Kafka producer setup
# ============================================================

def create_kafka_producer(
    broker: str, retries: int = 10, delay: int = 5
) -> KafkaProducer:
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=[broker],
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks=1,
                compression_type="snappy",
                batch_size=16384,
                linger_ms=10,
            )
            print(f"✓ Connected to Kafka broker: {broker}")
            return producer
        except NoBrokersAvailable:
            print(
                f"Attempt {attempt}/{retries} — broker not available yet, retrying in {delay}s..."
            )
            time.sleep(delay)

    print("✗ Could not connect to Kafka after maximum retries. Exiting.")
    sys.exit(1)


# ============================================================
# Utility printing
# ============================================================

def print_sensor_summary(sensors: list) -> None:
    total = len(sensors)
    abnormal = [s for s in sensors if s["abnormal"]]
    normal = [s for s in sensors if not s["abnormal"]]

    print("=" * 72)
    print("IoT Sensor Producer")
    print("=" * 72)
    print(f"Kafka broker            : {KAFKA_BROKER}")
    print(f"Topics                  : {', '.join(TOPICS.values())}")
    print(f"Rooms                   : {', '.join(ROOMS)}")
    print(f"Sensors per type/room   : {SENSORS_PER_TYPE_PER_ROOM}")
    print(f"Total sensors           : {total}")
    print(f"Target rate             : ~{total} msg/sec")
    print(f"Healthy spike prob.     : {NORMAL_SPIKE_PROBABILITY * 100:.1f}%")
    print(f"Abnormal spike prob.    : {ABNORMAL_SPIKE_PROBABILITY * 100:.1f}%")
    print(f"Abnormal room           : {ABNORMAL_ROOM}")
    print(f"Abnormal sensors total  : {len(abnormal)}")
    print(f"Normal sensors total    : {len(normal)}")
    print("=" * 72)

    abnormal_by_type = {
        "temp_humidity": [],
        "light": [],
        "power": [],
    }

    for sensor in abnormal:
        abnormal_by_type[sensor["sensor_type"]].append(sensor)

    print("Abnormal sensor catalog")
    print("-" * 72)
    for sensor_type in ["temp_humidity", "light", "power"]:
        print(f"{sensor_type}:")
        for sensor in abnormal_by_type[sensor_type]:
            print(
                f"  - id={sensor['sensor_id']} | room={sensor['location_id']} | "
                f"index={sensor['sensor_index']} | spike_prob={sensor['spike_probability']:.3f}"
            )
    print("-" * 72)
    print("Starting data stream. Press Ctrl+C to stop.")
    print("-" * 72)


# ============================================================
# Main loop
# ============================================================

def main():
    sensors = build_sensor_pool()
    print_sensor_summary(sensors)

    producer = create_kafka_producer(KAFKA_BROKER)

    total_sent = 0
    start_time = time.time()
    batch_number = 0

    try:
        while True:
            batch_start = time.time()
            batch_number += 1

            for sensor in sensors:
                message = {
                    "sensor_id": sensor["sensor_id"],
                    "sensor_type": sensor["sensor_type"],
                    "location_id": sensor["location_id"],
                    "description": sensor["description"],
                    "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                }

                message.update(sensor["generator"](sensor))

                producer.send(sensor["topic"], value=message)
                total_sent += 1

            producer.flush()

            if batch_number % 10 == 0:
                elapsed = time.time() - start_time
                rate = total_sent / elapsed if elapsed > 0 else 0.0
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"Sent: {total_sent:7,d} messages | "
                    f"Rate: {rate:6.1f} msg/sec | "
                    f"Uptime: {elapsed:6.0f}s | "
                    f"Batches: {batch_number:5d}"
                )

            batch_duration = time.time() - batch_start
            sleep_time = max(0.0, SLEEP_INTERVAL - batch_duration)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n" + "-" * 72)
        print("Shutting down producer...")
        producer.flush()
        producer.close()

        elapsed = time.time() - start_time
        avg_rate = total_sent / elapsed if elapsed > 0 else 0.0

        print("Final statistics:")
        print(f"  Total messages sent : {total_sent:,}")
        print(f"  Total duration      : {elapsed:.1f}s")
        print(f"  Average rate        : {avg_rate:.1f} msg/sec")
        print("✓ Producer stopped cleanly.")


if __name__ == "__main__":
    main()