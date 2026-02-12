#!/bin/bash

# Do NOT use set -e if you want the trap to catch errors during startup
# set -e 

echo "=== Starting IoT Pipeline ==="

# Define the path to your venv
VENV_PATH="/home/alessio/Documents/python_venvs/Big_Data_venv"
PYTHON_VENV="$VENV_PATH/bin/python3"

# 1. Start Infrastructure
if ! docker ps | grep -q kafka; then
    echo "Starting Docker infrastructure..."
    docker compose up -d  # Use space, not hyphen
    echo "Waiting for Cassandra (Healthcheck)..."
    # Better than sleep: wait for the container to be healthy
    until [ "$(docker inspect -f {{.State.Health.Status}} cassandra-1)"=="healthy" ]; do
        sleep 5
    done
fi

# 2. Schema Init
docker exec -i cassandra-1 cqlsh < ../cassandra/init.cql

# 3. Start Producer using venv Python
echo "Starting Kafka producer..."
$PYTHON_VENV ../src/producer.py &
PRODUCER_PID=$!

sleep 5

# 4. Start Spark Consumer using venv environment
echo "Starting Spark consumer..."
# We use PYSPARK_PYTHON to tell Spark which interpreter to use for the workers
export PYSPARK_PYTHON="$PYTHON_VENV"

spark-submit \
  --master local[*] \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,com.datastax.spark:spark-cassandra-connector_2.12:3.5.0 \
  ../src/spark_consumer.py & 
SPARK_PID=$!

# 5. Cleanup Function
cleanup() {
    echo ""
    echo "=== Shutting down processes ==="
    kill $PRODUCER_PID $SPARK_PID 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM EXIT

echo "=== Pipeline Live. Monitoring logs... ==="
# Keep script alive
wait