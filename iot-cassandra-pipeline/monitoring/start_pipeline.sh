#!/bin/bash

set -e  # Exit on error

echo "=== Starting IoT Pipeline ==="

# Check if infrastructure is running
if ! docker ps | grep -q kafka; then
    echo "Starting Docker infrastructure..."
    docker-compose up -d
    echo "Waiting 30s for services to initialize..."
    sleep 30
fi

# Verify Cassandra cluster
echo "Checking Cassandra cluster..."
docker exec cassandra-1 nodetool status | grep UN

# Initialize schema (idempotent - safe to run multiple times)
echo "Initializing Cassandra schema..."
docker exec -i cassandra-1 cqlsh < cassandra/init.cql

# Start producer
echo "Starting Kafka producer..."
python3 src/producer.py > logs/producer.log 2>&1 &
PRODUCER_PID=$!
echo "Producer started (PID: $PRODUCER_PID)"

# Wait for topic creation
echo "Waiting 10s for Kafka topic creation..."
sleep 10

# Verify topic exists
docker exec kafka kafka-topics --list --bootstrap-server localhost:9092 | grep sensor-events

# Start Spark consumer
echo "Starting Spark consumer..."
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,com.datastax.spark:spark-cassandra-connector_2.12:3.5.0 \
  --conf spark.cassandra.connection.host=localhost \
  --conf spark.cassandra.connection.port=9042 \
  src/spark_consumer.py

# Cleanup on exit
trap "kill $PRODUCER_PID 2>/dev/null" EXIT
