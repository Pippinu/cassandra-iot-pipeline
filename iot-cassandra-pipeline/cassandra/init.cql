-- ========================================
-- IoT Analytics Keyspace & Schema
-- Replication Factor: 3 (all nodes)
-- ========================================

-- Create keyspace with RF=3 (full replication across 3 nodes)
CREATE KEYSPACE IF NOT EXISTS iot_analytics
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};

USE iot_analytics;

-- ========================================
-- TABLE 1: Raw Sensor Events
-- Purpose: Write-heavy ingestion from Kafka/Spark
-- Compaction: SizeTiered (optimized for writes)
-- Consistency: CL=ONE for writes (fast)
-- ========================================

CREATE TABLE IF NOT EXISTS sensor_events (
    device_id UUID,
    timestamp BIGINT,
    temperature FLOAT,
    humidity FLOAT,
    location TEXT,
    PRIMARY KEY ((device_id), timestamp)
) WITH CLUSTERING ORDER BY (timestamp DESC)
AND compaction = {
    'class': 'SizeTieredCompactionStrategy',
    'min_threshold': 4,
    'max_threshold': 32
}
AND comment = 'Write-heavy: raw sensor data from Kafka/Spark. SizeTiered compaction for maximum write throughput.';

-- ========================================
-- TABLE 2: Hourly Aggregates
-- Purpose: Pre-computed analytics (mixed read/write)
-- Compaction: Leveled (optimized for reads)
-- Consistency: CL=QUORUM (balanced)
-- ========================================

CREATE TABLE IF NOT EXISTS hourly_aggregates (
    device_id UUID,
    hour_bucket BIGINT,
    avg_temperature FLOAT,
    max_temperature FLOAT,
    min_temperature FLOAT,
    event_count INT,
    PRIMARY KEY ((device_id), hour_bucket)
) WITH CLUSTERING ORDER BY (hour_bucket DESC)
AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 160
}
AND comment = 'Aggregates computed by Spark. Leveled compaction for predictable read latency.';

-- ========================================
-- TABLE 3: Device Metadata
-- Purpose: Reference data (rare updates)
-- Compaction: TimeWindow (for time-series with TTL)
-- Consistency: CL=LOCAL_ONE (fast lookups)
-- ========================================

CREATE TABLE IF NOT EXISTS devices (
    device_id UUID PRIMARY KEY,
    device_name TEXT,
    location TEXT,
    created_at TIMESTAMP,
    last_updated TIMESTAMP
) WITH compaction = {
    'class': 'TimeWindowCompactionStrategy',
    'compaction_window_unit': 'DAYS',
    'compaction_window_size': 1
}
AND comment = 'Device reference data. TimeWindow compaction for efficient TTL handling.';

-- ========================================
-- Optional: Create index for location queries
-- (Demonstration of secondary indexes)
-- ========================================

CREATE INDEX IF NOT EXISTS idx_location 
ON sensor_events(location);

-- Verification query
SELECT table_name, compaction 
FROM system_schema.tables 
WHERE keyspace_name = 'iot_analytics';
