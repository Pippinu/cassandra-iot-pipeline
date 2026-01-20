#!/bin/bash
#
# Live Compaction Monitoring
# Shows real-time compaction activity for demo
#

echo "================================================================================"
echo "           LIVE COMPACTION MONITORING"
echo "================================================================================"
echo ""
echo "Watching for compaction events (Ctrl+C to stop)..."
echo ""

while true; do
    clear
    echo "================================================================================"
    echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "================================================================================"
    echo ""
    
    # Compaction stats
    echo "[ACTIVE COMPACTIONS]"
    docker exec cassandra-1 nodetool compactionstats
    echo ""
    
    # SSTable counts per table
    echo "[SSTABLE COUNTS]"
    echo "sensor_events (SizeTiered):"
    docker exec cassandra-1 nodetool tablestats iot_analytics.sensor_events | grep "SSTable count:"
    echo ""
    echo "hourly_aggregates (Leveled):"
    docker exec cassandra-1 nodetool tablestats iot_analytics.hourly_aggregates | grep "SSTable count:"
    echo ""
    
    # Compaction history (last 5)
    echo "[RECENT COMPACTION HISTORY]"
    docker exec cassandra-1 nodetool compactionhistory | head -n 7
    echo ""
    
    sleep 5
done
