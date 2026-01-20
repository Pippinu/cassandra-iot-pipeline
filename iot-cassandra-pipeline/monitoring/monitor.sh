#!/bin/bash
#
# Cassandra Cluster Monitoring Script
# Displays cluster health, compaction stats, and table metrics
#

clear
echo "================================================================================"
echo "           CASSANDRA CLUSTER MONITORING DASHBOARD"
echo "================================================================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ========================================
# 1. CLUSTER STATUS
# ========================================
echo -e "${CYAN}[1] CLUSTER STATUS${NC}"
echo "--------------------------------------------------------------------------------"
docker exec cassandra-1 nodetool status
echo ""

# ========================================
# 2. TOKEN RING OWNERSHIP
# ========================================
echo -e "${CYAN}[2] TOKEN RING OWNERSHIP (iot_analytics keyspace)${NC}"
echo "--------------------------------------------------------------------------------"
docker exec cassandra-1 nodetool status iot_analytics
echo ""

# ========================================
# 3. RING INFORMATION
# ========================================
echo -e "${CYAN}[3] TOKEN RING DISTRIBUTION${NC}"
echo "--------------------------------------------------------------------------------"
docker exec cassandra-1 nodetool ring | grep -A 20 "Address.*Status.*State.*Load"
echo ""

# ========================================
# 4. TABLE STATISTICS
# ========================================
echo -e "${CYAN}[4] TABLE STATISTICS (sensor_events)${NC}"
echo "--------------------------------------------------------------------------------"
docker exec cassandra-1 nodetool tablestats iot_analytics.sensor_events | grep -E "Table:|SSTable count:|Space used|Read Count:|Write Count:|Pending|Compacted|Bloom filter"
echo ""

echo -e "${CYAN}[5] TABLE STATISTICS (hourly_aggregates)${NC}"
echo "--------------------------------------------------------------------------------"
docker exec cassandra-1 nodetool tablestats iot_analytics.hourly_aggregates | grep -E "Table:|SSTable count:|Space used|Read Count:|Write Count:|Pending|Compacted|Bloom filter"
echo ""

# ========================================
# 6. COMPACTION STATISTICS
# ========================================
echo -e "${CYAN}[6] ACTIVE COMPACTIONS${NC}"
echo "--------------------------------------------------------------------------------"
COMPACTION_OUTPUT=$(docker exec cassandra-1 nodetool compactionstats 2>&1)
if echo "$COMPACTION_OUTPUT" | grep -q "pending tasks: 0"; then
    echo -e "${GREEN}✓ No active compactions${NC}"
else
    echo "$COMPACTION_OUTPUT"
fi
echo ""

# ========================================
# 7. THREAD POOL STATS
# ========================================
echo -e "${CYAN}[7] THREAD POOL STATISTICS${NC}"
echo "--------------------------------------------------------------------------------"
docker exec cassandra-1 nodetool tpstats | grep -E "Pool Name|MutationStage|ReadStage|CompactionExecutor"
echo ""

# ========================================
# 8. ROW COUNTS
# ========================================
echo -e "${CYAN}[8] ROW COUNTS${NC}"
echo "--------------------------------------------------------------------------------"
SENSOR_COUNT=$(docker exec cassandra-1 cqlsh -e "USE iot_analytics; SELECT COUNT(*) FROM sensor_events;" | grep -E "^\s*[0-9]+" | tr -d ' ')
AGG_COUNT=$(docker exec cassandra-1 cqlsh -e "USE iot_analytics; SELECT COUNT(*) FROM hourly_aggregates;" | grep -E "^\s*[0-9]+" | tr -d ' ')

echo "sensor_events:       ${GREEN}${SENSOR_COUNT}${NC} rows"
echo "hourly_aggregates:   ${GREEN}${AGG_COUNT}${NC} rows"
echo ""

# ========================================
# 9. DISK USAGE
# ========================================
echo -e "${CYAN}[9] DATA DIRECTORY DISK USAGE${NC}"
echo "--------------------------------------------------------------------------------"
docker exec cassandra-1 du -sh /var/lib/cassandra/data/iot_analytics/
echo ""

# ========================================
# 10. PIPELINE HEALTH
# ========================================
echo -e "${CYAN}[10] PIPELINE HEALTH CHECK${NC}"
echo "--------------------------------------------------------------------------------"

# Check if producer is running
if pgrep -f "producer.py" > /dev/null; then
    echo -e "Producer:       ${GREEN}✓ RUNNING${NC}"
else
    echo -e "Producer:       ${RED}✗ STOPPED${NC}"
fi

# Check if Kafka is healthy
if docker ps | grep -q kafka; then
    echo -e "Kafka:          ${GREEN}✓ RUNNING${NC}"
else
    echo -e "Kafka:          ${RED}✗ STOPPED${NC}"
fi

# Check if Spark consumer is running
if pgrep -f "spark_consumer.py" > /dev/null; then
    echo -e "Spark Consumer: ${GREEN}✓ RUNNING${NC}"
else
    echo -e "Spark Consumer: ${RED}✗ STOPPED${NC}"
fi

# Check Cassandra nodes
CASSANDRA_NODES=$(docker ps | grep cassandra | wc -l)
echo -e "Cassandra:      ${GREEN}✓ ${CASSANDRA_NODES}/3 NODES UP${NC}"

echo ""
echo "================================================================================"
echo "Monitoring complete at $(date)"
echo "================================================================================"
