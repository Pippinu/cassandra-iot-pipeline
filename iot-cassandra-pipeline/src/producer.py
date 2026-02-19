#!/usr/bin/env python3
"""
IoT Sensor Data Producer (Avro + Schema Registry)

Simulates 100 devices sending temperature/humidity readings to Kafka,
serialized as Avro binary with schema enforced via Confluent Schema Registry.
"""

import time
import uuid
import sys
import json

from faker import Faker
from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

# ========================================
# Configuration
# ========================================

KAFKA_BROKER        = "localhost:9092"
KAFKA_TOPIC         = "sensor-events"
SCHEMA_REGISTRY_URL = "http://localhost:8081"
NUM_DEVICES         = 100
EVENTS_PER_SECOND   = 100
SLEEP_INTERVAL      = 1.0
SCHEMA_PATH         = "../schemas/SensorEvent.avsc"

# ========================================
# Load Avro Schema from file
# ========================================

def load_schema(path: str) -> str:
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        print(f"✗ Schema file not found: {path}")
        sys.exit(1)

print(f"Loading Avro schema from {SCHEMA_PATH}...")
schema_str = load_schema(SCHEMA_PATH)
print("✓ Schema loaded\n")

# ========================================
# Connect to Schema Registry
# ========================================
# SchemaRegistryClient registers the schema on first use and caches
# the schema ID for all subsequent serializations — no per-message
# HTTP calls after the first one.
# 
# NOTE: So the guarantee is: "this message conforms to the schema the producer
# was initialized with", not "this message was validated by the Registry in real time". 
# The Registry's role is enforcing compatibility between schema versions, 
# that happens at schema registration time, not at message produce time.

print(f"Connecting to Schema Registry: {SCHEMA_REGISTRY_URL}")

try:
    sr_client = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
    # Probe the registry with a lightweight call to catch connection errors early
    sr_client.get_subjects()
    print("✓ Connected to Schema Registry\n")
except Exception as e:
    print(f"✗ Cannot reach Schema Registry at {SCHEMA_REGISTRY_URL}: {e}")
    print("  Is the schema-registry container running? (docker-compose ps)")
    sys.exit(1)

# ========================================
# Build Avro Serializer
# ========================================
# AvroSerializer registers the schema under subject "sensor-events-value"
# (Confluent TopicNameStrategy) and prepends the 5-byte wire-format
# header (magic byte + schema ID) to every serialized message.

avro_serializer = AvroSerializer(
    schema_registry_client=sr_client,
    schema_str=schema_str
)

# ========================================
# Create Kafka Producer
# ========================================

print(f"Connecting to Kafka broker: {KAFKA_BROKER}")

try:
    producer = Producer({
        "bootstrap.servers":  KAFKA_BROKER,
        "acks":               "1",
        "compression.type":   "snappy",
        "batch.size":         16384,
        "linger.ms":          10
    })
    print(f"✓ Connected to Kafka broker: {KAFKA_BROKER}\n")
except Exception as e:
    print(f"✗ Failed to create Kafka producer: {e}")
    sys.exit(1)

# ========================================
# Delivery callback
# ========================================

def delivery_report(err, msg):
    """Called by producer.poll() for every delivered/failed message."""
    if err is not None:
        print(f"✗ Delivery failed for message: {err}")

# ========================================
# Generate device pool
# ========================================

fake = Faker()
Faker.seed(42)

locations = ["Rome", "Milan", "Naples", "Turin", "Florence", "Venice", "Bologna"]

print(f"Generating {NUM_DEVICES} virtual devices...")
devices = [
    {
        "device_id":   str(uuid.uuid4()),
        "device_name": f"Sensor-{i:03d}",
        "location":    fake.random.choice(locations)
    }
    for i in range(NUM_DEVICES)
]
print(f"✓ {NUM_DEVICES} devices ready\n")

# ========================================
# Serialization context
# ========================================
# SerializationContext tells the serializer which topic and field
# (key vs value) this message belongs to — required by confluent-kafka.

ctx = SerializationContext(KAFKA_TOPIC, MessageField.VALUE)

# ========================================
# Main produce loop
# ========================================

total_sent = 0
start_time = time.time()

print(f"Starting data generation: {EVENTS_PER_SECOND} events/sec")
print(f"Topic  : {KAFKA_TOPIC}")
print(f"Schema : {SCHEMA_REGISTRY_URL}/subjects/sensor-events-value/versions/latest")
print(f"Press Ctrl+C to stop\n")
print("-" * 80)

try:
    while True:
        batch_start = time.time()

        for device in devices:
            event = {
                "device_id":   device["device_id"],
                "device_name": device["device_name"],
                "timestamp":   int(time.time() * 1000),
                "temperature": round(fake.pyfloat(min_value=15.0, max_value=35.0, right_digits=2), 2),
                "humidity":    round(fake.pyfloat(min_value=30.0, max_value=90.0, right_digits=2), 2),
                "location":    device["location"]
            }

            producer.produce(
                topic=KAFKA_TOPIC,
                value=avro_serializer(event, ctx),
                on_delivery=delivery_report
            )

            # poll() serves the delivery callback queue without blocking
            producer.poll(0)

            total_sent += 1

            if total_sent % 100 == 0:
                elapsed = time.time() - start_time
                rate = total_sent / elapsed if elapsed > 0 else 0
                print(
                    f"Sent: {total_sent:6d} events | "
                    f"Rate: {rate:6.1f} events/sec | "
                    f"Last: {device['device_name']} @ {device['location']} "
                    f"- {event['temperature']}°C"
                )

        # Flush once per batch to ensure delivery before sleeping
        producer.flush()

        batch_duration = time.time() - batch_start
        sleep_time = max(0, SLEEP_INTERVAL - batch_duration)
        time.sleep(sleep_time)

except KeyboardInterrupt:
    print("\n" + "-" * 80)
    print("Shutting down producer...")
    producer.flush()
    elapsed = time.time() - start_time
    print(f"\nStatistics:")
    print(f"  Total events sent : {total_sent}")
    print(f"  Duration          : {elapsed:.1f} seconds")
    print(f"  Average rate      : {total_sent / elapsed:.1f} events/sec")
    print("\n✓ Producer stopped cleanly")
