#!/bin/bash

# Auto-flush memtables + Show SSTable Tier Distribution
# Demonstrates SizeTiered compaction bucketing

# Force C locale for consistent decimal formatting (period as separator)
export LC_NUMERIC=C
export LC_ALL=C

echo "================================================================================"
echo "                    AUTO-FLUSH WITH TIER MONITORING"
echo "================================================================================"
echo ""
echo "Starting auto-flush (every 60s)..."
echo "Press Ctrl+C to stop"
echo ""

PREV_TOTAL=0

while true; do
    echo "[$(date '+%H:%M:%S')] Flushing memtables..."
    
    # Flush memtables
    docker exec cassandra-1 nodetool flush iot_analytics sensor_events 2>/dev/null
    docker exec cassandra-1 nodetool flush iot_analytics hourly_aggregates 2>/dev/null
    
    # Get SSTable file sizes (exclude secondary index files in .idx_location)
    echo "   → Analyzing SSTable distribution..."
    
    # Use docker exec with proper shell escaping
    SSTABLES=$(docker exec cassandra-1 bash -c "find /var/lib/cassandra/data/iot_analytics/sensor_events-*/nb-*-big-Data.db -type f ! -path '*/.idx_location/*' -exec stat -c '%s %n' {} \\; 2>/dev/null | sort -n")
    
    if [ -z "$SSTABLES" ]; then
        echo "   → No SSTables found yet"
    else
        # Count SSTables by tier
        TIER0=0  # 0-5 MB
        TIER1=0  # 5-25 MB
        TIER2=0  # 25-125 MB
        TIER3=0  # 125+ MB
        
        while IFS= read -r line; do
            SIZE=$(echo "$line" | awk '{print $1}')
            
            # Convert to MB using locale-safe awk (C locale enforced above)
            SIZE_MB=$(awk "BEGIN {printf \"%.2f\", $SIZE / 1048576}")
            
            # Tier classification using awk with proper decimal comparison
            if awk "BEGIN {exit !($SIZE_MB < 5.0)}"; then
                ((TIER0++))
            elif awk "BEGIN {exit !($SIZE_MB < 25.0)}"; then
                ((TIER1++))
            elif awk "BEGIN {exit !($SIZE_MB < 125.0)}"; then
                ((TIER2++))
            else
                ((TIER3++))
            fi
        done <<< "$SSTABLES"
        
        TOTAL=$((TIER0 + TIER1 + TIER2 + TIER3))
        
        # Display tier distribution
        echo "   → Total SSTables: ${TOTAL}"
        echo "      ├─ Tier 0 (0-5 MB):     ${TIER0} SSTables"
        echo "      ├─ Tier 1 (5-25 MB):    ${TIER1} SSTables"
        echo "      ├─ Tier 2 (25-125 MB):  ${TIER2} SSTables"
        echo "      └─ Tier 3 (125+ MB):    ${TIER3} SSTables"
        
        # Detect compaction
        if [ "$TOTAL" -lt "$PREV_TOTAL" ] && [ "$PREV_TOTAL" -gt 0 ]; then
            DIFF=$((PREV_TOTAL - TOTAL))
            echo ""
            echo "   ⚡ COMPACTION DETECTED! (${PREV_TOTAL} → ${TOTAL} SSTables, merged ${DIFF})"
            
            # Show last compaction from logs
            LAST_COMPACTION=$(docker exec cassandra-1 tail -n 100 /var/log/cassandra/system.log 2>/dev/null | grep "Compacted.*sensor_events" | tail -n 1)
            
            if [ -n "$LAST_COMPACTION" ]; then
                # Extract key info (streamlined parsing)
                TIME=$(echo "$LAST_COMPACTION" | grep -oP '\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
                SIZE_INFO=$(echo "$LAST_COMPACTION" | grep -oP '\d+(\.\d+)?MiB to \d+(\.\d+)?MiB')
                DURATION=$(echo "$LAST_COMPACTION" | grep -oP 'in \d+ms')
                
                if [ -n "$TIME" ] && [ -n "$SIZE_INFO" ]; then
                    echo "   → Compacted at $TIME: $SIZE_INFO $DURATION"
                fi
            fi
            echo ""
        fi
        
        PREV_TOTAL=$TOTAL
    fi
    
    echo "────────────────────────────────────────────────────────────────────────────────"
    sleep 60
done
