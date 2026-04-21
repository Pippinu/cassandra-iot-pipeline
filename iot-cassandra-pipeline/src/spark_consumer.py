#!/usr/bin/env python3
"""
Spark Structured Streaming Consumer — IoT Sensor Pipeline

Reads from 3 Kafka topics, writes to 3 Cassandra keyspaces:

iot_raw       -> temp_humidity_by_sensor, light_by_sensor, power_by_sensor,
                 readings_by_location, devices_metadata
iot_analytics -> sensor_aggregates_30s, aggregates_by_type,
                 sensor_behavior_profiles
iot_alerts    -> sensor_alerts

Path A:
- No applyInPandasWithState
- No Arrow-dependent stateful pandas runner
- sensor_behavior_profiles computed with foreachBatch from each micro-batch

Run with:
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1,\
com.datastax.spark:spark-cassandra-connector_2.12:3.5.1 \
  spark_consumer.py
"""

import os
import uuid as uuid_lib

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql.functions import (
    avg,
    col,
    concat_ws,
    count,
    current_date,
    date_sub,
    desc,
    from_json,
    from_unixtime,
    lit,
    max,
    min,
    row_number,
    sqrt,
    sum as spark_sum,
    to_date,
    udf,
    when,
    window,
)
from pyspark.sql.types import (
    FloatType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "localhost")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CHECKPOINT_DIR = os.getenv("CHECKPOINT_DIR", "/tmp/spark_checkpoints")

KS_RAW = "iot_raw"
KS_ANALYTICS = "iot_analytics"
KS_ALERTS = "iot_alerts"

TOPICS = {
    "temp_humidity": "sensor_temp_humidity",
    "light": "sensor_light",
    "power": "sensor_power",
}

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

PROFILE_SPIKE_THRESHOLDS = {
    "temp_humidity": THRESHOLDS["humidity_high"],
    "light": THRESHOLDS["light_high"],
    "power": THRESHOLDS["wattage_high"],
}

# ──────────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────────

BASE_FIELDS = [
    StructField("sensor_id", StringType(), False),
    StructField("sensor_type", StringType(), False),
    StructField("location_id", StringType(), False),
    StructField("description", StringType(), False),
    StructField("timestamp", LongType(), False),
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
# ──────────────────────────────────────────────────────────────────────────────

spark = (
    SparkSession.builder.appName("IoT-Sensor-Consumer")
    .config("spark.cassandra.connection.host", CASSANDRA_HOST)
    .config("spark.cassandra.connection.port", str(CASSANDRA_PORT))
    .config("spark.sql.streaming.checkpointLocation", CHECKPOINT_DIR)
    .config("spark.streaming.stopGracefullyOnShutdown", "true")
    .getOrCreate()
)

spark.sparkContext.setLogLevel("ERROR")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def read_topic(topic: str) -> DataFrame:
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BROKER)
        .option("subscribe", topic)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
        .selectExpr("CAST(value AS STRING) AS json_str")
    )


def add_time_columns(df: DataFrame) -> DataFrame:
    return df.withColumn(
        "timestamp",
        from_unixtime(col("timestamp") / 1000).cast(TimestampType()),
    ).withColumn("date", to_date(col("timestamp")))


def cassandra_sink(df: DataFrame, keyspace: str, table: str, suffix: str):
    return (
        df.writeStream.format("org.apache.spark.sql.cassandra")
        .options(table=table, keyspace=keyspace)
        .option("checkpointLocation", f"{CHECKPOINT_DIR}/{suffix}")
        .outputMode("append")
        .start()
    )


gen_uuid = udf(lambda: str(uuid_lib.uuid4()), StringType())

vector_udf = udf(
    lambda mean_value, variance_value, spike_count: [
        float(mean_value if mean_value is not None else 0.0),
        float(variance_value if variance_value is not None else 0.0),
        float(spike_count if spike_count is not None else 0.0),
    ],
    "array<float>",
)

# ──────────────────────────────────────────────────────────────────────────────
# Parse Kafka topics
# ──────────────────────────────────────────────────────────────────────────────

raw_power = (
    read_topic(TOPICS["power"])
    .select(from_json(col("json_str"), SCHEMA_POWER).alias("d"))
    .select("d.*")
    .transform(add_time_columns)
)

raw_th = (
    read_topic(TOPICS["temp_humidity"])
    .select(from_json(col("json_str"), SCHEMA_TEMP_HUMIDITY).alias("d"))
    .select("d.*")
    .transform(add_time_columns)
)

raw_light = (
    read_topic(TOPICS["light"])
    .select(from_json(col("json_str"), SCHEMA_LIGHT).alias("d"))
    .select("d.*")
    .transform(add_time_columns)
)

raw_power_enriched = raw_power.withColumn("wattage", col("voltage") * col("amperage"))

# ──────────────────────────────────────────────────────────────────────────────
# iot_raw — typed raw tables
# ──────────────────────────────────────────────────────────────────────────────

q1 = cassandra_sink(
    raw_th.select(
        "sensor_id", "date", "timestamp", "location_id", "temperature", "humidity"
    ),
    KS_RAW,
    "temp_humidity_by_sensor",
    "th_raw",
)

q2 = cassandra_sink(
    raw_light.select("sensor_id", "date", "timestamp", "location_id", "light_level"),
    KS_RAW,
    "light_by_sensor",
    "light_raw",
)

q3 = cassandra_sink(
    raw_power_enriched.select(
        "sensor_id",
        "date",
        "timestamp",
        "location_id",
        "voltage",
        "amperage",
        "wattage",
    ),
    KS_RAW,
    "power_by_sensor",
    "power_raw",
)

# ──────────────────────────────────────────────────────────────────────────────
# iot_raw — readings_by_location
# ──────────────────────────────────────────────────────────────────────────────

q4a = cassandra_sink(
    raw_th.select(
        "location_id",
        "date",
        "timestamp",
        "sensor_id",
        "sensor_type",
        "temperature",
        "humidity",
    ),
    KS_RAW,
    "readings_by_location",
    "loc_th",
)

q4b = cassandra_sink(
    raw_light.select(
        "location_id", "date", "timestamp", "sensor_id", "sensor_type", "light_level"
    ),
    KS_RAW,
    "readings_by_location",
    "loc_light",
)

q4c = cassandra_sink(
    raw_power_enriched.select(
        "location_id",
        "date",
        "timestamp",
        "sensor_id",
        "sensor_type",
        "voltage",
        "amperage",
        "wattage",
    ),
    KS_RAW,
    "readings_by_location",
    "loc_power",
)

# ──────────────────────────────────────────────────────────────────────────────
# iot_raw — devices_metadata
# ──────────────────────────────────────────────────────────────────────────────

metadata_stream = (
    raw_th.select("sensor_id", "sensor_type", "location_id", "description")
    .unionByName(
        raw_light.select("sensor_id", "sensor_type", "location_id", "description")
    )
    .unionByName(
        raw_power_enriched.select(
            "sensor_id", "sensor_type", "location_id", "description"
        )
    )
)


def write_metadata_batch(batch_df, batch_id):
    if batch_df.isEmpty():
        return

    metadata_df = batch_df.select(
        "sensor_id", "sensor_type", "location_id", "description"
    ).dropDuplicates(["sensor_id"])

    metadata_df.write.format("org.apache.spark.sql.cassandra").options(
        table="devices_metadata", keyspace=KS_RAW
    ).mode("append").save()


q5 = (
    metadata_stream.writeStream.foreachBatch(write_metadata_batch)
    .option("checkpointLocation", f"{CHECKPOINT_DIR}/devices_metadata")
    .outputMode("append")
    .start()
)

# ──────────────────────────────────────────────────────────────────────────────
# iot_analytics — sensor_aggregates_30s
# ──────────────────────────────────────────────────────────────────────────────


def build_sensor_aggregates(df: DataFrame, metric_col: str) -> DataFrame:
    return (
        df.withWatermark("timestamp", "1 minute")
        .groupBy(
            window(col("timestamp"), "30 seconds"),
            col("sensor_id"),
            col("sensor_type"),
            col("location_id"),
        )
        .agg(
            avg(metric_col).alias("avg_value"),
            min(metric_col).alias("min_value"),
            max(metric_col).alias("max_value"),
            count("*").cast("int").alias("reading_count"),
        )
        .select(
            col("sensor_id"),
            to_date(col("window.start")).alias("date"),
            col("window.start").alias("window_start"),
            col("sensor_type"),
            col("location_id"),
            col("avg_value"),
            col("min_value"),
            col("max_value"),
            col("reading_count"),
        )
    )


q6 = cassandra_sink(
    build_sensor_aggregates(raw_th, "temperature"),
    KS_ANALYTICS,
    "sensor_aggregates_30s",
    "agg_th",
)

q7 = cassandra_sink(
    build_sensor_aggregates(raw_light, "light_level"),
    KS_ANALYTICS,
    "sensor_aggregates_30s",
    "agg_light",
)

q8 = cassandra_sink(
    build_sensor_aggregates(raw_power_enriched, "wattage"),
    KS_ANALYTICS,
    "sensor_aggregates_30s",
    "agg_power",
)

# ──────────────────────────────────────────────────────────────────────────────
# iot_analytics — aggregates_by_type
# ──────────────────────────────────────────────────────────────────────────────


def build_type_aggregates(df: DataFrame, metric_col: str) -> DataFrame:
    return (
        df.withWatermark("timestamp", "1 minute")
        .groupBy(
            window(col("timestamp"), "30 seconds"),
            col("sensor_type"),
            col("sensor_id"),
            col("location_id"),
        )
        .agg(avg(metric_col).alias("avg_value"))
        .select(
            col("sensor_type"),
            to_date(col("window.start")).alias("date"),
            col("window.start").alias("window_start"),
            col("sensor_id"),
            col("location_id"),
            col("avg_value"),
        )
    )


q9 = cassandra_sink(
    build_type_aggregates(raw_th, "temperature"),
    KS_ANALYTICS,
    "aggregates_by_type",
    "aggtype_th",
)

q10 = cassandra_sink(
    build_type_aggregates(raw_light, "light_level"),
    KS_ANALYTICS,
    "aggregates_by_type",
    "aggtype_light",
)

q11 = cassandra_sink(
    build_type_aggregates(raw_power_enriched, "wattage"),
    KS_ANALYTICS,
    "aggregates_by_type",
    "aggtype_power",
)

# ──────────────────────────────────────────────────────────────────────────────
# iot_alerts — sensor_alerts
# ──────────────────────────────────────────────────────────────────────────────

UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

def detect_alerts(df: DataFrame) -> DataFrame:
    return (
        df.withColumn(
            "alert_type",
            when(
                (col("sensor_type") == "temp_humidity")
                & (col("temperature") > THRESHOLDS["temperature_high"]),
                lit("TEMPERATURE_HIGH"),
            )
            .when(
                (col("sensor_type") == "temp_humidity")
                & (col("temperature") < THRESHOLDS["temperature_low"]),
                lit("TEMPERATURE_LOW"),
            )
            .when(
                (col("sensor_type") == "temp_humidity")
                & (col("humidity") > THRESHOLDS["humidity_high"]),
                lit("HUMIDITY_HIGH"),
            )
            .when(
                (col("sensor_type") == "light")
                & (col("light_level") > THRESHOLDS["light_high"]),
                lit("LIGHT_HIGH"),
            )
            .when(
                (col("sensor_type") == "power")
                & (col("voltage") > THRESHOLDS["voltage_high"]),
                lit("VOLTAGE_HIGH"),
            )
            .when(
                (col("sensor_type") == "power")
                & (col("amperage") > THRESHOLDS["amperage_high"]),
                lit("AMPERAGE_HIGH"),
            )
            .otherwise(None),
        )
        .filter(col("alert_type").isNotNull())
        .withColumn("alert_id", gen_uuid())
        .withColumn(
            "severity",
            when(
                col("alert_type").isin(
                    "TEMPERATURE_HIGH", "VOLTAGE_HIGH", "AMPERAGE_HIGH"
                ),
                lit("HIGH"),
            ).otherwise(lit("MEDIUM")),
        )
        .withColumn(
            "alert_message",
            concat_ws(
                " ",
                lit("Threshold breached:"),
                col("alert_type"),
                lit("— sensor"),
                col("sensor_id"),
            ),
        )
        .select(
            col("sensor_id"),
            col("timestamp"),
            col("alert_id"),
            col("location_id"),
            col("alert_type"),
            col("alert_message"),
            col("severity"),
        )
    )


def gen_uuid_str():
    return str(uuid_lib.uuid4())

gen_uuid = udf(gen_uuid_str, StringType())

def write_alerts_batch(batchdf, batchid):
    if batchdf.isEmpty():
        return

    alerts = detect_alerts(batchdf).filter(col("alert_id").rlike(UUID_RE))
    if alerts.isEmpty():
        return

    alerts.write.format("org.apache.spark.sql.cassandra") \
        .options(table="sensor_alerts", keyspace=KS_ALERTS) \
        .mode("append") \
        .save()


th_for_alerts = (
    raw_th.withColumn("light_level", lit(None).cast(FloatType()))
    .withColumn("voltage", lit(None).cast(FloatType()))
    .withColumn("amperage", lit(None).cast(FloatType()))
    .select(
        "sensor_id",
        "sensor_type",
        "location_id",
        "timestamp",
        "temperature",
        "humidity",
        "light_level",
        "voltage",
        "amperage",
    )
)

light_for_alerts = (
    raw_light.withColumn("temperature", lit(None).cast(FloatType()))
    .withColumn("humidity", lit(None).cast(FloatType()))
    .withColumn("voltage", lit(None).cast(FloatType()))
    .withColumn("amperage", lit(None).cast(FloatType()))
    .select(
        "sensor_id",
        "sensor_type",
        "location_id",
        "timestamp",
        "temperature",
        "humidity",
        "light_level",
        "voltage",
        "amperage",
    )
)

power_for_alerts = (
    raw_power_enriched.withColumn("temperature", lit(None).cast(FloatType()))
    .withColumn("humidity", lit(None).cast(FloatType()))
    .withColumn("light_level", lit(None).cast(FloatType()))
    .select(
        "sensor_id",
        "sensor_type",
        "location_id",
        "timestamp",
        "temperature",
        "humidity",
        "light_level",
        "voltage",
        "amperage",
    )
)

q12 = (
    th_for_alerts.unionByName(light_for_alerts)
    .unionByName(power_for_alerts)
    .writeStream.foreachBatch(write_alerts_batch)
    .option("checkpointLocation", f"{CHECKPOINT_DIR}/alerts")
    .outputMode("append")
    .start()
)

# ──────────────────────────────────────────────────────────────────────────────
# iot_analytics — sensor_behavior_profiles
# Safer Path A: compute one profile per sensor from each micro-batch
# temp_humidity -> humidity
# light         -> light_level
# power         -> wattage
# profile_vector = [mean_value, variance_value, spike_count]
# ──────────────────────────────────────────────────────────────────────────────

# profile_th = raw_th.select(
#     "sensor_id",
#     "sensor_type",
#     "location_id",
#     "timestamp",
#     col("humidity").alias("profile_value"),
#     lit(float(PROFILE_SPIKE_THRESHOLDS["temp_humidity"])).alias("spike_threshold"),
# )

# profile_light = raw_light.select(
#     "sensor_id",
#     "sensor_type",
#     "location_id",
#     "timestamp",
#     col("light_level").alias("profile_value"),
#     lit(float(PROFILE_SPIKE_THRESHOLDS["light"])).alias("spike_threshold"),
# )

# profile_power = raw_power_enriched.select(
#     "sensor_id",
#     "sensor_type",
#     "location_id",
#     "timestamp",
#     col("wattage").alias("profile_value"),
#     lit(float(PROFILE_SPIKE_THRESHOLDS["power"])).alias("spike_threshold"),
# )

# profile_stream = (
#     profile_th
#     .unionByName(profile_light)
#     .unionByName(profile_power)
# )

# def write_behavior_profiles_batch(batch_df, batch_id):
#     if batch_df.isEmpty():
#         return

#     profiles = (
#         batch_df.filter(col("profile_value").isNotNull())
#         .groupBy("location_id", "sensor_type", "sensor_id")
#         .agg(
#             max("timestamp").alias("last_updated_at"),
#             count("*").cast("int").alias("profile_size"),
#             avg("profile_value").alias("mean_value"),
#             avg(col("profile_value") * col("profile_value")).alias("mean_square"),
#             spark_sum(
#                 when(col("profile_value") > col("spike_threshold"), lit(1)).otherwise(lit(0))
#             ).cast("int").alias("spike_count"),
#         )
#         .withColumn(
#             "variance_value",
#             when(
#                 col("mean_square") - col("mean_value") * col("mean_value") < 0,
#                 lit(0.0),
#             ).otherwise(col("mean_square") - col("mean_value") * col("mean_value")),
#         )
#         .withColumn(
#             "profile_vector",
#             vector_udf(col("mean_value"), col("variance_value"), col("spike_count"))
#         )
#         .select(
#             "location_id",
#             "sensor_type",
#             "sensor_id",
#             "last_updated_at",
#             "profile_size",
#             col("mean_value").cast("float").alias("mean_value"),
#             col("variance_value").cast("float").alias("variance_value"),
#             "spike_count",
#             "profile_vector",
#         )
#     )

#     if profiles.isEmpty():
#         return

#     profiles.write.format("org.apache.spark.sql.cassandra") \
#         .options(table="sensor_behavior_profiles", keyspace=KS_ANALYTICS) \
#         .mode("append") \
#         .save()

# q13 = (
#     profile_stream.writeStream.foreachBatch(write_behavior_profiles_batch)
#     .option("checkpointLocation", f"{CHECKPOINT_DIR}/behavior_profiles")
#     .outputMode("append")
#     .start()
# )

# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────

PROFILE_SIZE = 200
PROFILE_LOOKBACK_DAYS = 1  # include today + possible rollover from yesterday

def recent_profile_source() -> DataFrame:
    th = (
        spark.read.format("org.apache.spark.sql.cassandra")
        .options(table="temp_humidity_by_sensor", keyspace=KS_RAW)
        .load()
        .filter(col("date") >= date_sub(current_date(), PROFILE_LOOKBACK_DAYS))
        .select(
            col("sensor_id"),
            lit("temp_humidity").alias("sensor_type"),
            col("location_id"),
            col("timestamp"),
            col("humidity").alias("profile_value"),
            lit(float(PROFILE_SPIKE_THRESHOLDS["temp_humidity"])).alias("spike_threshold"),
        )
    )

    light = (
        spark.read.format("org.apache.spark.sql.cassandra")
        .options(table="light_by_sensor", keyspace=KS_RAW)
        .load()
        .filter(col("date") >= date_sub(current_date(), PROFILE_LOOKBACK_DAYS))
        .select(
            col("sensor_id"),
            lit("light").alias("sensor_type"),
            col("location_id"),
            col("timestamp"),
            col("light_level").alias("profile_value"),
            lit(float(PROFILE_SPIKE_THRESHOLDS["light"])).alias("spike_threshold"),
        )
    )

    power = (
        spark.read.format("org.apache.spark.sql.cassandra")
        .options(table="power_by_sensor", keyspace=KS_RAW)
        .load()
        .filter(col("date") >= date_sub(current_date(), PROFILE_LOOKBACK_DAYS))
        .select(
            col("sensor_id"),
            lit("power").alias("sensor_type"),
            col("location_id"),
            col("timestamp"),
            col("wattage").alias("profile_value"),
            lit(float(PROFILE_SPIKE_THRESHOLDS["power"])).alias("spike_threshold"),
        )
    )

    return (
        th.unionByName(light)
        .unionByName(power)
        .filter(col("profile_value").isNotNull())
    )

def refresh_behavior_profiles(batch_df: DataFrame, batch_id: int) -> None:
    source = recent_profile_source()

    rank_window = Window.partitionBy(
        "location_id", "sensor_type", "sensor_id"
    ).orderBy(desc("timestamp"))

    recent_n = (
        source.withColumn("rn", row_number().over(rank_window))
        .filter(col("rn") <= PROFILE_SIZE)
        .drop("rn")
    )

    profiles = (
        recent_n.groupBy("location_id", "sensor_type", "sensor_id")
        .agg(
            max("timestamp").alias("last_updated_at"),
            count("*").cast("int").alias("profile_size"),
            avg("profile_value").alias("mean_value"),
            avg(col("profile_value") * col("profile_value")).alias("mean_square"),
            spark_sum(
                when(col("profile_value") > col("spike_threshold"), lit(1)).otherwise(lit(0))
            ).cast("int").alias("spike_count"),
        )
        .withColumn(
            "variance_value",
            when(
                col("mean_square") - col("mean_value") * col("mean_value") < 0,
                lit(0.0),
            ).otherwise(col("mean_square") - col("mean_value") * col("mean_value")),
        )
        .filter(col("profile_size") >= 10)
        .withColumn(
            "profile_vector",
            vector_udf(
                col("mean_value"),
                col("variance_value"),
                col("spike_count"),
            ),
        )
        .select(
            "location_id",
            "sensor_type",
            "sensor_id",
            "last_updated_at",
            "profile_size",
            col("mean_value").cast("float").alias("mean_value"),
            col("variance_value").cast("float").alias("variance_value"),
            "spike_count",
            "profile_vector",
        )
    )

    if profiles.isEmpty():
        return

    profiles.write.format("org.apache.spark.sql.cassandra") \
        .options(table="sensor_behavior_profiles", keyspace=KS_ANALYTICS) \
        .mode("append") \
        .save()

# lightweight trigger stream: recompute profiles every 30s from Cassandra history
profile_tick = spark.readStream.format("rate").option("rowsPerSecond", 1).load()

q13 = (
    profile_tick.writeStream.foreachBatch(refresh_behavior_profiles)
    .trigger(processingTime="30 seconds")
    .option("checkpointLocation", f"{CHECKPOINT_DIR}/behavior_profiles_refresh")
    .outputMode("append")
    .start()
)

# ──────────────────────────────────────────────────────────────────────────────
# Keep alive
# ──────────────────────────────────────────────────────────────────────────────

active_count = len(spark.streams.active)
print(f"\n[Spark] IoT Consumer started — {active_count} active streaming queries")
print(f"[Spark] Kafka      : {KAFKA_BROKER}")
print(f"[Spark] Cassandra  : {CASSANDRA_HOST}:{CASSANDRA_PORT}")
print(f"[Spark] Keyspaces  : {KS_RAW} | {KS_ANALYTICS} | {KS_ALERTS}")
print("[Spark] Profile    : foreachBatch micro-batch profiles for vector search")
print("[Spark] Press Ctrl+C to stop gracefully.\n")

spark.streams.awaitAnyTermination()
