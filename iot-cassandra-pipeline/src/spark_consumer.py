#!/usr/bin/env python3
"""
Spark Streaming Consumer: Kafka → Cassandra Pipeline

Reads IoT sensor events from Kafka and writes to Cassandra with dual strategy:
1. Raw events      → sensor_events table      (CL=ONE,    write-optimized)
2. Hourly aggregates → hourly_aggregates table (CL=QUORUM, read-optimized)
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    avg, col, count, from_json, from_unixtime,
    max, min, to_timestamp, unix_timestamp, window
)
from pyspark.sql.types import (
    FloatType, IntegerType, LongType,
    StringType, StructField, StructType
)
import sys

# ========================================
# Configuration
# ========================================

KAFKA_BROKER       = "localhost:9092"
KAFKA_TOPIC        = "sensor-events"
CASSANDRA_HOST     = "localhost"
CASSANDRA_PORT     = "9042"
CASSANDRA_KEYSPACE = "iot_analytics"

# ========================================
# Initialize Spark Session
# ========================================
# JARs are resolved via --packages in the spark-submit command.
# No spark.jars config needed here.

print("Initializing Spark Session...")

try:
    spark = SparkSession.builder \
        .appName("IoT-Cassandra-Pipeline") \
        .config("spark.cassandra.connection.host", CASSANDRA_HOST) \
        .config("spark.cassandra.connection.port", CASSANDRA_PORT) \
        .config("spark.sql.shuffle.partitions", "3") \
        .getOrCreate()

    spark.sparkContext.setLogLevel("WARN")
    print("✓ Spark session created successfully\n")

except Exception as e:
    print(f"✗ Failed to create Spark session: {e}")
    sys.exit(1)

# ========================================
# Define Event Schema
# ========================================

event_schema = StructType([
    StructField("device_id",   StringType(), False),
    StructField("device_name", StringType(), True),
    StructField("timestamp",   LongType(),   False),
    StructField("temperature", FloatType(),  False),
    StructField("humidity",    FloatType(),  False),
    StructField("location",    StringType(), True)
])

# ========================================
# Read from Kafka
# ========================================

print(f"Connecting to Kafka: {KAFKA_BROKER}")
print(f"Subscribing to topic: {KAFKA_TOPIC}\n")

try:
    kafka_df = spark.readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", KAFKA_BROKER) \
        .option("subscribe", KAFKA_TOPIC) \
        .option("startingOffsets", "earliest") \
        .option("failOnDataLoss", "false") \
        .load()

    print("✓ Connected to Kafka stream\n")

except Exception as e:
    print(f"✗ Failed to connect to Kafka: {e}")
    sys.exit(1)

# ========================================
# Parse JSON Events
# ========================================

print("Parsing JSON events...")

events_df = kafka_df \
    .select(from_json(col("value").cast("string"), event_schema).alias("data")) \
    .select("data.*") \
    .withColumn("event_time", to_timestamp(from_unixtime(col("timestamp") / 1000)))

print("✓ JSON parsing configured\n")

# ========================================
# STREAM 1: Raw Events → sensor_events
# Consistency: ONE (fast writes)
# ========================================

print("Setting up raw events stream → sensor_events table...")

def write_to_cassandra_raw(batch_df, batch_id):
    """Write raw events to sensor_events table."""
    if batch_df.count() > 0:
        cassandra_df = batch_df.select(
            "device_id",
            "timestamp",
            "temperature",
            "humidity",
            "location"
        )
        cassandra_df.write \
            .format("org.apache.spark.sql.cassandra") \
            .mode("append") \
            .option("keyspace", CASSANDRA_KEYSPACE) \
            .option("table", "sensor_events") \
            .option("spark.cassandra.output.consistency.level", "ONE") \
            .save()
        print(f"[Batch {batch_id}] Wrote {batch_df.count()} raw events to sensor_events")

raw_events_query = events_df.writeStream \
    .foreachBatch(write_to_cassandra_raw) \
    .outputMode("append") \
    .option("checkpointLocation", "/tmp/spark-checkpoint-raw") \
    .start()

print("✓ Raw events stream started\n")

# ========================================
# STREAM 2: Hourly Aggregates → hourly_aggregates
# Consistency: QUORUM (consistent reads)
# ========================================

print("Setting up aggregation stream → hourly_aggregates table...")

events_with_watermark = events_df \
    .withWatermark("event_time", "1 minute")

hourly_agg_df = events_with_watermark \
    .groupBy(
        col("device_id"),
        window(col("event_time"), "1 hour").alias("hour_window")
    ) \
    .agg(
        avg("temperature").alias("avg_temperature"),
        max("temperature").alias("max_temperature"),
        min("temperature").alias("min_temperature"),
        count("*").alias("event_count")
    ) \
    .select(
        col("device_id"),
        unix_timestamp(col("hour_window.start")).cast(LongType()).alias("hour_bucket"),
        col("avg_temperature"),
        col("max_temperature"),
        col("min_temperature"),
        col("event_count").cast(IntegerType())
    )

def write_to_cassandra_agg(batch_df, batch_id):
    """Write aggregates to hourly_aggregates table."""
    if batch_df.count() > 0:
        batch_df.write \
            .format("org.apache.spark.sql.cassandra") \
            .mode("append") \
            .option("keyspace", CASSANDRA_KEYSPACE) \
            .option("table", "hourly_aggregates") \
            .option("spark.cassandra.output.consistency.level", "QUORUM") \
            .save()
        print(f"[Batch {batch_id}] Wrote {batch_df.count()} aggregates to hourly_aggregates")

agg_query = hourly_agg_df.writeStream \
    .foreachBatch(write_to_cassandra_agg) \
    .outputMode("append") \
    .option("checkpointLocation", "/tmp/spark-checkpoint-agg") \
    .trigger(processingTime="10 seconds") \
    .start()

print("✓ Aggregation stream started\n")

# ========================================
# Monitor Streams
# ========================================

print("=" * 80)
print("Spark Streaming Pipeline Active")
print("=" * 80)
print(f"Kafka Topic  : {KAFKA_TOPIC}")
print(f"Cassandra    : {CASSANDRA_HOST}:{CASSANDRA_PORT}")
print(f"Keyspace     : {CASSANDRA_KEYSPACE}")
print(f"\nStreams:")
print(f"  1. Raw Events → sensor_events      (CL=ONE)")
print(f"  2. Aggregates → hourly_aggregates  (CL=QUORUM)")
print(f"\nPress Ctrl+C to stop\n")
print("=" * 80)

try:
    spark.streams.awaitAnyTermination()
except KeyboardInterrupt:
    print("\n\nStopping streams...")
    raw_events_query.stop()
    agg_query.stop()
    spark.stop()
    print("✓ All streams stopped cleanly")
