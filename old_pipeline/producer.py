#!/usr/bin/env python3
"""
IoT Sensor Data Producer
Simulates 100 devices sending temperature/humidity readings to Kafka
"""

from kafka import KafkaProducer
from faker import Faker
import json
import time
import uuid
from datetime import datetime
import sys

# Configuration
KAFKA_BROKER = 'localhost:9092'
KAFKA_TOPIC = 'sensor-events'
NUM_DEVICES = 100
EVENTS_PER_SECOND = 100
SLEEP_INTERVAL = 1.0  # seconds between batches

# Initialize
fake = Faker()
Faker.seed(42)  # Reproducible data

# Create Kafka producer
try:
    producer = KafkaProducer(
        bootstrap_servers=[KAFKA_BROKER],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        acks=1,  # Wait for leader acknowledgment
        compression_type='snappy',  # Compress messages
        batch_size=16384,  # 16KB batches
        linger_ms=10  # Wait 10ms to batch messages
    )
    print(f"✓ Connected to Kafka broker: {KAFKA_BROKER}")
except Exception as e:
    print(f"✗ Failed to connect to Kafka: {e}")
    sys.exit(1)

# Generate device pool
devices = []
locations = ['Rome', 'Milan', 'Naples', 'Turin', 'Florence', 'Venice', 'Bologna']

print(f"Generating {NUM_DEVICES} virtual devices...")
for i in range(NUM_DEVICES):
    devices.append({
        'device_id': str(uuid.uuid4()),
        'device_name': f'Sensor-{i:03d}',
        'location': fake.random.choice(locations)
    })
print(f"✓ {NUM_DEVICES} devices ready\n")

# Statistics
total_sent = 0
start_time = time.time()

print(f"Starting data generation: {EVENTS_PER_SECOND} events/sec")
print(f"Topic: {KAFKA_TOPIC}")
print(f"Press Ctrl+C to stop\n")
print("-" * 80)

try:
    while True:
        batch_start = time.time()
        
        # Send batch of events
        for device in devices:
            event = {
                'device_id': device['device_id'],
                'device_name': device['device_name'],
                'timestamp': int(time.time() * 1000),  # milliseconds
                'temperature': round(fake.pyfloat(min_value=15.0, max_value=35.0, right_digits=2), 2),
                'humidity': round(fake.pyfloat(min_value=30.0, max_value=90.0, right_digits=2), 2),
                'location': device['location']
            }
            
            # Send to Kafka
            producer.send(KAFKA_TOPIC, value=event)
            total_sent += 1
            
            # Print every 100 events
            if total_sent % 100 == 0:
                elapsed = time.time() - start_time
                rate = total_sent / elapsed if elapsed > 0 else 0
                print(f"Sent: {total_sent:6d} events | Rate: {rate:6.1f} events/sec | "
                      f"Last: {device['device_name']} @ {device['location']} - {event['temperature']}°C")
        
        # Flush producer to ensure delivery
        producer.flush()
        
        # Sleep to maintain target rate
        batch_duration = time.time() - batch_start
        sleep_time = max(0, SLEEP_INTERVAL - batch_duration)
        time.sleep(sleep_time)

except KeyboardInterrupt:
    print("\n" + "-" * 80)
    print("Shutting down producer...")
    producer.close()
    
    elapsed = time.time() - start_time
    print(f"\nStatistics:")
    print(f"  Total events sent: {total_sent}")
    print(f"  Duration: {elapsed:.1f} seconds")
    print(f"  Average rate: {total_sent / elapsed:.1f} events/sec")
    print("\n✓ Producer stopped cleanly")
