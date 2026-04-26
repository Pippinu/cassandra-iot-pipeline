#!/usr/bin/env python3
"""
Spark Structured Streaming consumer for IoT sensor data.

Reads JSON messages from three Kafka topics, parses and validates them,
writes raw readings to per-type Cassandra tables, and computes hourly
windowed aggregations per room stored in a separate stats table.

Run with:
    spark-submit \
      --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1,\
com.datastax.spark:spark-cassandra-connector_2.12:3.5.0 \
      spark_consumer.py
"""

import os
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    from_json,
    col,
    from_unixtime,
    window,
    avg,
    min,
    max,
    count,
)
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    FloatType,
    TimestampType,
    LongType,
)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "localhost")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "iot_sensors")
CHECKPOINT_DIR = os.getenv("CHECKPOINT_DIR", "/tmp/spark_checkpoints")

TOPICS = {
    "temp_humidity": "sensor_temp_humidity",
    "light": "sensor_light",
    "power": "sensor_power",
}

# ──────────────────────────────────────────────────────────────────────────────
# JSON Schemas
# Each schema mirrors exactly what produce.py puts into Kafka messages.
# BASE_FIELDS are shared across all sensor types.
# ──────────────────────────────────────────────────────────────────────────────

BASE_FIELDS = [
    StructField("sensor_id", StringType(), False),
    StructField("sensor_type", StringType(), False),
    StructField("location_id", StringType(), False),
    StructField("timestamp", LongType(), False),  # Unix epoch in ms
]

SCHEMA_TEMP_HUMIDITY = StructType(
    BASE_FIELDS
    + [
        StructField("temperature", FloatType(), True),
        StructField("humidity", FloatType(), True),
    ]
)

SCHEMA_LIGHT = StructType(
    BASE_FIELDS
    + [
        StructField("light_level", FloatType(), True),
    ]
)

SCHEMA_POWER = StructType(
    BASE_FIELDS
    + [
        StructField("voltage", FloatType(), True),
        StructField("amperage", FloatType(), True),
    ]
)

# ──────────────────────────────────────────────────────────────────────────────
# SparkSession
# Cassandra connection details are injected as Spark config so that both the
# streaming sink and any future batch reads share the same settings.
# ──────────────────────────────────────────────────────────────────────────────

spark = (
    SparkSession.builder.appName("IoT-Sensor-Consumer")
    .config("spark.cassandra.connection.host", CASSANDRA_HOST)
    .config("spark.cassandra.connection.port", str(CASSANDRA_PORT))
    .config("spark.sql.streaming.checkpointLocation", CHECKPOINT_DIR)
    .config("spark.streaming.stopGracefullyOnShutdown", "true")
    .getOrCreate()
)

spark.sparkContext.setLogLevel("WARN")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def read_topic(topic: str):
    """
    Open a Kafka topic as a Structured Streaming source.
    startingOffsets=latest means we only process messages that arrive
    after the consumer starts; historical messages are ignored.
    failOnDataLoss=false prevents the job from crashing if Kafka
    compacts old offsets before Spark catches up (safe for demos).
    """
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BROKER)
        .option("subscribe", topic)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
        .selectExpr("CAST(value AS STRING) AS json_str")
    )


def write_to_cassandra(df, table: str, checkpoint_suffix: str):
    """
    Append-mode sink to a Cassandra table.
    Each call starts an independent streaming query with its own
    checkpoint directory so queries can fail and restart independently.
    The DataFrame column names must match the Cassandra table columns exactly.
    """
    return (
        df.writeStream.format("org.apache.spark.sql.cassandra")
        .options(table=table, keyspace=KEYSPACE)
        .option("checkpointLocation", f"{CHECKPOINT_DIR}/{checkpoint_suffix}")
        .outputMode("append")
        .start()
    )


def parse_timestamp(df):
    """
    Convert the Unix-millisecond timestamp from the producer into a proper
    TimestampType column that Spark and Cassandra both understand natively.
    Division by 1000 converts ms → seconds before from_unixtime.
    """
    return df.withColumn(
        "timestamp", from_unixtime(col("timestamp") / 1000).cast(TimestampType())
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stream 1 — Temperature & Humidity
# Table: readings_temp_humidity
#   PRIMARY KEY ((sensor_id), timestamp)
#   WITH CLUSTERING ORDER BY (timestamp DESC)
# ──────────────────────────────────────────────────────────────────────────────


raw_th = (
    read_topic(TOPICS["temp_humidity"])
    .select(from_json(col("json_str"), SCHEMA_TEMP_HUMIDITY).alias("d"))
    .select(
        col("d.sensor_id"),
        col("d.sensor_type"),
        col("d.location_id"),
        col("d.timestamp"),
        col("d.temperature"),
        col("d.humidity"),
    )
    .transform(parse_timestamp)
)

q1 = write_to_cassandra(raw_th, "readings_temp_humidity", "th_raw")

# ──────────────────────────────────────────────────────────────────────────────
# Stream 2 — Light
# Table: readings_light
#   PRIMARY KEY ((sensor_id), timestamp)
#   WITH CLUSTERING ORDER BY (timestamp DESC)
# ──────────────────────────────────────────────────────────────────────────────

raw_light = (
    read_topic(TOPICS["light"])
    .select(from_json(col("json_str"), SCHEMA_LIGHT).alias("d"))
    .select(
        col("d.sensor_id"),
        col("d.sensor_type"),
        col("d.location_id"),
        col("d.timestamp"),
        col("d.light_level"),
    )
    .transform(parse_timestamp)
)

q2 = write_to_cassandra(raw_light, "readings_light", "light_raw")

# ──────────────────────────────────────────────────────────────────────────────
# Stream 3 — Power
# A computed column (wattage = voltage × amperage) is derived here rather
# than in the producer to keep producer logic simple and to show that Spark
# can enrich data in-flight before landing it in Cassandra.
#
# Table: readings_power
#   PRIMARY KEY ((sensor_id), timestamp)
#   WITH CLUSTERING ORDER BY (timestamp DESC)
# ──────────────────────────────────────────────────────────────────────────────

raw_power = (
    read_topic(TOPICS["power"])
    .select(from_json(col("json_str"), SCHEMA_POWER).alias("d"))
    .select(
        col("d.sensor_id"),
        col("d.sensor_type"),
        col("d.location_id"),
        col("d.timestamp"),
        col("d.voltage"),
        col("d.amperage"),
        (col("d.voltage") * col("d.amperage")).alias("wattage"),
    )
    .transform(parse_timestamp)
)

q3 = write_to_cassandra(raw_power, "readings_power", "power_raw")

# ──────────────────────────────────────────────────────────────────────────────
# Stream 4 — Windowed Hourly Aggregation (Temperature & Humidity by Room)
#
# withWatermark tells Spark how late data can arrive before the window is
# considered complete and its results emitted. With a 10-minute watermark,
# Spark waits up to 10 extra minutes after the window closes before writing.
#
# groupBy(window(...), location_id) groups messages into tumbling 1-hour
# buckets per room, then computes descriptive statistics.
#
# outputMode("append") means Spark only writes a window row once it is
# finalized (after watermark passes), avoiding duplicates in Cassandra.
#
# Table: hourly_stats_by_room
#   PRIMARY KEY ((location_id), window_start)
#   WITH CLUSTERING ORDER BY (window_start DESC)
# ──────────────────────────────────────────────────────────────────────────────

th_with_watermark = raw_th.withWatermark("timestamp", "10 minutes")

hourly_stats = (
    th_with_watermark.groupBy(
        window(col("timestamp"), "1 hour"),
        col("location_id"),
    )
    .agg(
        avg("temperature").alias("avg_temperature"),
        min("temperature").alias("min_temperature"),
        max("temperature").alias("max_temperature"),
        avg("humidity").alias("avg_humidity"),
        count("*").alias("reading_count"),
    )
    .select(
        col("location_id"),
        col("window.start").alias("window_start"),
        col("window.end").alias("window_end"),
        col("avg_temperature"),
        col("min_temperature"),
        col("max_temperature"),
        col("avg_humidity"),
        col("reading_count"),
    )
)

q4 = (
    hourly_stats.writeStream.format("org.apache.spark.sql.cassandra")
    .options(table="hourly_stats_by_room", keyspace=KEYSPACE)
    .option("checkpointLocation", f"{CHECKPOINT_DIR}/hourly_stats")
    .outputMode("append")
    .start()
)

# ──────────────────────────────────────────────────────────────────────────────
# Keep-alive
# awaitAnyTermination() blocks the driver until one query fails or is stopped
# manually (Ctrl+C). On SIGINT, stopGracefullyOnShutdown ensures in-flight
# micro-batches finish before the process exits.
# ──────────────────────────────────────────────────────────────────────────────

active = [q.name or f"query-{i}" for i, q in enumerate(spark.streams.active)]
print(
    f"\n[Spark] Consumer started. Keyspace: '{KEYSPACE}' on {CASSANDRA_HOST}:{CASSANDRA_PORT}"
)
print(f"[Spark] Active streaming queries: {len(active)}")
for name in active:
    print(f"         • {name}")
print("[Spark] Press Ctrl+C to stop gracefully.\n")

spark.streams.awaitAnyTermination()
