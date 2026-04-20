-- ============================================================
-- IoT Sensor Pipeline — Cassandra Schema
-- Cluster:  3 nodes, RF=2, NetworkTopologyStrategy
-- Keyspaces: iot_raw | iot_alerts | iot_analytics
-- ============================================================

-- ============================================================
-- KEYSPACE: iot_raw
-- Stores raw per-sensor readings and device metadata.
-- RF=2: each partition lives on 2 of 3 nodes.
-- NetworkTopologyStrategy: production-grade, datacenter-aware.
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS iot_raw
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 2
};

USE iot_raw;

-- ------------------------------------------------------------
-- TABLE: devices_metadata
-- Purpose: Static sensor reference data (type, location).
-- Query:   "give me metadata for sensor X"
-- Key design: simple partition key only — no clustering columns
--             needed because lookups are by exact sensor_id,
--             with no ordering or range scan within the partition.
-- Compaction: Leveled — reference data is read-heavy, rarely written.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS devices_metadata (
    sensor_id   uuid,
    sensor_type text,
    location_id text,
    description text,
    PRIMARY KEY (sensor_type, sensor_id)
)
WITH compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = 'Static sensor reference data. Partition key is sensor_type (3 partitions) with sensor_id as clustering column. Leveled compaction for read-optimized access.';

-- ------------------------------------------------------------
-- TABLE: temp_humidity_by_sensor
-- Purpose: Raw temperature and humidity readings per sensor.
-- Query:   "latest readings for temp/humidity sensor X on date D"
-- Key design: composite partition key (sensor_id, date) bounds
--             partition size to ~86 400 rows/day per sensor.
--             timestamp DESC clustering returns most recent first.
-- Compaction: SizeTiered — write-heavy continuous ingestion.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS temp_humidity_by_sensor (
    sensor_id   uuid,
    date        date,
    timestamp   timestamp,
    location_id text,
    temperature float,
    humidity    float,
    PRIMARY KEY ((sensor_id, date), timestamp)
)
WITH CLUSTERING ORDER BY (timestamp DESC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'Raw temp/humidity readings. Composite partition key caps partition size to one day per sensor. STCS for write throughput.';

-- ------------------------------------------------------------
-- TABLE: light_by_sensor
-- Purpose: Raw light level readings per sensor.
-- Query:   "latest readings for light sensor X on date D"
-- Key design: same time-bucket strategy as temp_humidity_by_sensor.
-- Compaction: SizeTiered — write-heavy continuous ingestion.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS light_by_sensor (
    sensor_id   uuid,
    date        date,
    timestamp   timestamp,
    location_id text,
    light_level float,
    PRIMARY KEY ((sensor_id, date), timestamp)
)
WITH CLUSTERING ORDER BY (timestamp DESC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'Raw light level readings. Composite partition key caps partition size to one day per sensor. STCS for write throughput.';

-- ------------------------------------------------------------
-- TABLE: power_by_sensor
-- Purpose: Raw amperage and voltage readings per sensor.
-- Query:   "latest readings for power sensor X on date D"
-- Key design: same time-bucket strategy as temp_humidity_by_sensor.
-- Compaction: SizeTiered — write-heavy continuous ingestion.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS power_by_sensor (
    sensor_id   uuid,
    date        date,
    timestamp   timestamp,
    location_id text,
    amperage    float,
    voltage     float,      
    wattage     float,      -- derived by Spark: voltage * amperage
    PRIMARY KEY ((sensor_id, date), timestamp)
)
WITH CLUSTERING ORDER BY (timestamp DESC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'Raw power readings enriched by Spark. wattage is absent from Kafka messages and computed in-flight as voltage * amperage. STCS for write throughput.';

-- ------------------------------------------------------------
-- TABLE: readings_by_location
-- Purpose: All sensor readings grouped by physical location.
-- Query:   "all readings in room X on date D"
-- Key design: partition key is (location_id, date) — all sensors
--             in the same room on the same day share a partition.
--             timestamp DESC + sensor_id as clustering columns
--             provide recency ordering and row uniqueness.
-- Sparseness: INTENTIONALLY SPARSE — each row only populates
--             the columns relevant to its sensor type, leaving
--             the others absent (not null). This demonstrates
--             Cassandra's LSM-tree storage model: absent cells
--             occupy zero bytes on disk, unlike RDBMS fixed-width
--             rows which preallocate space for every column.
-- Compaction: SizeTiered — write-heavy, mirrors ingestion rate.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS readings_by_location (
    location_id text,
    date        date,
    timestamp   timestamp,
    sensor_id   uuid,
    sensor_type text,
    -- temp/humidity sensor columns (absent for light and power rows)
    temperature float,
    humidity    float,
    -- light sensor columns (absent for temp/humidity and power rows)
    light_level float,
    -- power sensor columns (absent for temp/humidity and light rows)
    amperage    float,
    voltage     float,
    wattage     float,    -- derived by Spark: voltage * amperage
    PRIMARY KEY ((location_id, date), timestamp, sensor_id)
)
WITH CLUSTERING ORDER BY (timestamp DESC, sensor_id ASC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'All readings by location. Intentionally sparse: rows omit irrelevant sensor columns — absent cells waste no disk space in the LSM-tree model.';

-- xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

-- ============================================================
-- KEYSPACE: iot_alerts
-- Stores threshold-based alerts generated by Spark.
-- RF=2, same datacenter topology.
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS iot_alerts
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 2
};

USE iot_alerts;

-- ------------------------------------------------------------
-- TABLE: sensor_alerts
-- Purpose: Alerts fired when sensor readings cross thresholds.
-- Query:   "recent alerts for sensor X"
-- Key design: sensor_id as partition key groups all alerts for
--             a sensor together. timestamp DESC gives recency
--             ordering. alert_id as tertiary clustering column
--             guarantees uniqueness — prevents silent overwrites
--             if two alerts fire within the same millisecond.
-- Compaction: Leveled — alerts are read frequently, written sparsely.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sensor_alerts (
    sensor_id     uuid,
    timestamp     timestamp,
    alert_id      uuid,
    location_id   text,
    alert_type    text,
    alert_message text,
    severity      text,
    PRIMARY KEY (sensor_id, timestamp, alert_id)
)
WITH CLUSTERING ORDER BY (timestamp DESC, alert_id ASC)
AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = 'Threshold alerts from Spark. alert_id prevents millisecond-collision overwrites. LCS for read-optimized alert queries.';

-- xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

-- ============================================================
-- KEYSPACE: iot_analytics
-- Stores 30-second windowed aggregations computed by Spark.
-- RF=2, same datacenter topology.
-- ============================================================

CREATE KEYSPACE IF NOT EXISTS iot_analytics
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 2
};

USE iot_analytics;

-- ------------------------------------------------------------
-- TABLE: sensor_aggregates_30s
-- Purpose: Per-sensor 30-second windowed statistics.
-- Query:   "30s aggregates for sensor X on date D"
-- Key design: composite partition key (sensor_id, date) mirrors
--             the raw tables — one partition per sensor per day.
--             window_start DESC clustering returns most recent
--             aggregation windows first.
-- Compaction: Leveled — analytics tables are read-heavy.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sensor_aggregates_30s (
    sensor_id     uuid,
    date          date,
    window_start  timestamp,
    sensor_type   text,
    location_id   text,
    avg_value     float,
    min_value     float,
    max_value     float,
    reading_count int,
    PRIMARY KEY ((sensor_id, date), window_start)
)
WITH CLUSTERING ORDER BY (window_start DESC)
AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = '30s windowed aggregates per sensor. Mirrors raw table partition strategy. LCS for predictable analytics read latency.';

-- ------------------------------------------------------------
-- TABLE: aggregates_by_type
-- Purpose: Cross-sensor aggregates grouped by sensor type.
-- Query:   "how are all temperature sensors performing today?"
-- Key design: partition key is (sensor_type, date) — all sensors
--             of the same type on the same day share a partition,
--             enabling efficient cross-sensor comparisons.
--             window_start + sensor_id as clustering columns
--             provide time ordering and row uniqueness.
-- Compaction: Leveled — analytics read-heavy workload.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aggregates_by_type (
    sensor_type  text,
    date         date,
    window_start timestamp,
    sensor_id    uuid,
    location_id  text,
    avg_value    float,
    PRIMARY KEY ((sensor_type, date), window_start, sensor_id)
)
WITH CLUSTERING ORDER BY (window_start DESC, sensor_id ASC)
AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = 'Cross-sensor aggregates by type. Partition key enables efficient type-wide analytics. LCS for read-optimized queries.';


-- ============================================================
-- Verification: list all tables per keyspace
-- Run after initialization to confirm schema loaded correctly.
-- ============================================================

SELECT keyspace_name, table_name
FROM system_schema.tables
WHERE keyspace_name IN ('iot_raw', 'iot_alerts', 'iot_analytics');