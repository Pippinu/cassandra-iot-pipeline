# Cassandra Exam Presentation Guide
## Real-Time IoT Analytics Pipeline

**Date**: March 27, 2026  
**Duration**: 10-15 minutes  
**Author**: Alessio Iacono

---

## 📋 Presentation Overview

Your exam presentation should follow this structure:

### **Part 1: Pipeline Overview (2-3 minutes)**
- Show the Kafka → Spark → Cassandra data flow
- Explain why each component is needed
- *Demo*: Start the infrastructure and verify all services are running

### **Part 2: Big Data Challenges (1 minute)**
- Present the 4 Vs (Volume, Velocity, Variety, Veracity)
- Show why traditional databases fail
- Transition to NoSQL as the solution

### **Part 3: Cassandra Deep Dive (8-10 minutes)** ⭐ **MAIN FOCUS**
This is where you demonstrate Cassandra's characteristics:

1. **Masterless Architecture**
   - Contrast with Master-Slave databases
   - Explain gossip protocol for peer discovery
   - Show no single point of failure

2. **CAP Theorem**
   - Explain C, A, P
   - Show why Cassandra chooses A + P
   - Discuss trade-offs for distributed systems

3. **Main Characteristics** (From your notes):
   - **NoSQL/Column-Family**: Two-level aggregate (partition key → columns)
   - **Distributed Hash Ring**: Token assignment, vnodes, replica placement
   - **Tunable Consistency**: ONE, QUORUM, ALL with code examples
   - **Eventual Consistency**: Background repair mechanisms
   - **Scale-Out Architecture**: Shared-nothing model
   - **Compaction Strategies**: SizeTiered, Leveled, TimeWindow

### **Part 4: Live Demonstrations (3-5 minutes)**
- Run prepared shell scripts to show:
  1. Cluster health (nodetool status)
  2. Consistency level differences
  3. Dynamic node addition and rebalancing
  4. Compaction monitoring
  5. Sample data visualization

### **Part 5: Key Takeaways (1 minute)**
- Summarize why Cassandra tackles Big Data challenges
- Discuss trade-offs
- When to use Cassandra vs alternatives

---

## 🔧 Suggested Additional Code Demonstrations

### Demo Code 1: Show Load Balancing with Token Ring

```python
# After adding 4th node, calculate token distribution
cat <<'EOF' | docker exec -i cassandra-1 cqlsh

-- Before scaling
SELECT COUNT(*) FROM iot_analytics.sensor_events;
-- Expected: ~20,000 events distributed across 3 nodes

-- After scaling (add cassandra-4)
-- Run nodetool ring to see new token ranges
-- Expected: 4 nodes with 25% fewer tokens each
EOF
```

**What it shows**: Linear scalability - adding a node automatically redistributes data

---

### Demo Code 2: Consistency Levels with Real Latency Impact

```bash
#!/bin/bash
# Measure read latency at different consistency levels

echo "Testing read latency at different CL values..."

cat <<'EOF' | docker exec -i cassandra-1 cqlsh

USE iot_analytics;

-- CL=ONE: Single replica (fastest)
CONSISTENCY ONE;
SELECT COUNT(*) as event_count FROM sensor_events;

-- CL=QUORUM: Wait for 2/3 replicas
CONSISTENCY QUORUM;
SELECT COUNT(*) as event_count FROM sensor_events;

-- CL=ALL: Wait for all 3 replicas (slowest)
CONSISTENCY ALL;
SELECT COUNT(*) as event_count FROM sensor_events;

EOF

echo "Observations:"
echo "• CL=ONE returns immediately (single node)"
echo "• CL=QUORUM may contact different nodes (balanced)"
echo "• CL=ALL waits for slowest replica (p99 latency)"
```

---

### Demo Code 3: Show Compaction Statistics

```bash
#!/bin/bash
# Compare compaction stats across tables

echo "=== COMPACTION STATISTICS ==="
echo ""

# Show which table has which compaction strategy
cat <<'EOF' | docker exec -i cassandra-1 cqlsh
USE iot_analytics;

DESCRIBE TABLE sensor_events;      -- SizeTiered
DESCRIBE TABLE hourly_aggregates;  -- Leveled
EOF

echo ""
echo "Real-time compaction activity:"
docker exec cassandra-1 nodetool compactionstats

echo ""
echo "Interpretation:"
echo "• SizeTiered: Groups similar-sized SSTables"
echo "• Leveled: Maintains non-overlapping levels"
echo "• Write amplification vs Read amplification tradeoff"
```

---

### Demo Code 4: Replication & Consistency Verification

```bash
#!/bin/bash
# Verify data is replicated across nodes

echo "=== REPLICATION VERIFICATION ==="
echo ""

# Get RF and replication settings
cat <<'EOF' | docker exec -i cassandra-1 cqlsh
USE iot_analytics;

-- Shows replication factor
DESCRIBE KEYSPACE iot_analytics;

-- Shows replication on each node
SELECT * FROM system.peers;

-- Count replicas for a specific partition key
SELECT COUNT(*) FROM sensor_events 
WHERE device_id = <specific_uuid> ALLOW FILTERING;

EOF

echo ""
echo "Key point:"
echo "• RF=3: Each partition stored on exactly 3 nodes"
echo "• Network topology strategy ensures replicas on different racks"
echo "• Failure of 1 node doesn't lose data (2 replicas remain)"
```

---

### Demo Code 5: Schema Flexibility (NoSQL)

```bash
#!/bin/bash
# Show that Cassandra is schema-flexible

cat <<'EOF' | docker exec -i cassandra-1 cqlsh

USE iot_analytics;

-- Try adding a new column dynamically (no migration!)
ALTER TABLE sensor_events ADD battery_level FLOAT;

-- Insert with new column
INSERT INTO sensor_events 
(device_id, timestamp, temperature, humidity, location, battery_level)
VALUES (uuid(), now(), 22.5, 45, 'kitchen', 87.5);

-- Some rows have the new column, some don't
-- This is the "schema flexibility" of NoSQL

SELECT * FROM sensor_events LIMIT 10;

EOF

echo ""
echo "Schema Flexibility:"
echo "• Add columns without migration"
echo "• Rows can have different columns (sparse)"
echo "• No rigid schema enforcement"
echo "• Handles variety challenge!"
```

---

## 🎯 How to Present Each Section

### Section 1: Pipeline (Show Architecture Diagram)
```
"Our pipeline simulates an IoT system with 100 temperature sensors 
producing 100 events per second. Kafka acts as a buffer, Spark aggregates 
the data, and Cassandra stores both raw and aggregated data for analysis."
```

### Section 2: Big Data Challenges (Reference Your Notes)
- **Volume**: 100 events/sec × 86,400 sec/day = 8.6M events/day
- **Velocity**: Real-time streaming requires sub-millisecond ingestion
- **Variety**: Sensors report different attributes (temp, humidity, location)
- **Veracity**: Handle sensor faults, duplicate readings, missing data

→ *"Traditional SQL databases can't handle this. Cassandra is designed for it."*

### Section 3: Cassandra Characteristics (This is Your Main Content)
Use the notebook to walk through each characteristic with its visualization.

**For each characteristic, explain:**
1. **What it is**: The feature/design
2. **Why it matters**: How it solves Big Data problems
3. **Trade-off**: What you give up to get it

Example for Tunable Consistency:
- **What**: CL=ONE (1 replica), CL=QUORUM (majority), CL=ALL (all replicas)
- **Why**: Allows speed-vs-correctness tradeoff per operation
- **Trade-off**: CL=ONE might return stale data temporarily

### Section 4: Live Demonstrations (Run Code!)
- **Demo 1**: "nodetool status shows 3 healthy nodes with 16 tokens each"
- **Demo 2**: "Read at QUORUM ensures 2 replicas agree on value"
- **Demo 3**: "Adding node 4 redistributes 25% of tokens automatically"
- **Demo 4**: "SizeTiered compaction optimizes for writes, Leveled for reads"
- **Demo 5**: "Sample data shows partition keys distribute evenly"

---

## ⏱️ Time Management

| Section | Time | Pacing |
|---------|------|--------|
| Part 1: Pipeline Overview | 2-3 min | Fast, visual |
| Part 2: Big Data Challenges | 1 min | Quick facts |
| Part 3: Cassandra Characteristics | 8-10 min | Detailed, slow |
| Part 4: Live Demos | 3-5 min | Show output |
| Part 5: Key Takeaways | 1 min | Conclusion |
| **Total** | **10-15 min** | |

**If running short**: Skip Demo 3 (add 4th node) - it's nice but not essential.
**If running long**: Trim Part 3 - focus on 3-4 characteristics instead of 8.

---

## 🚀 Pre-Presentation Checklist

- [ ] Docker infrastructure is running (all 3 nodes healthy)
- [ ] Kafka topic "sensor-events" has data
- [ ] Cassandra tables are populated
- [ ] Test all demo scripts work without errors
- [ ] Have backup: If a demo fails, you can still explain the concept
- [ ] Screen resolution is large enough to see nodetool output
- [ ] Network is stable (demos run shell commands)

---

## 💡 Key Points to Emphasize

1. **Masterless = No SPOF**: Unlike traditional databases with a master node, any Cassandra node can serve requests. This is huge for availability.

2. **Tunable Consistency = Flexibility**: You choose consistency level per operation. Fast writes (ONE) + verified reads (QUORUM) is a sweet spot.

3. **Eventual Consistency = Reality**: Network partitions happen. Cassandra accepts temporary inconsistency and repairs automatically.

4. **Linear Scaling = Growth Without Limit**: Add a node → system rebalances → +1x capacity. No resharding, no downtime.

5. **Compaction Strategies = Workload Optimization**: Different tables need different strategies. No "one size fits all".

---

## 📚 Links to Your Files

- **Report**: `report_clean.md` - Long-form explanation, use for reference
- **Notes on Big Data**: `1_bigdata_intro.md` - 4 Vs challenges
- **Notes on Storage**: `3_big_data_storage.md` - Scale-out, shared-nothing, DFS
- **Notes on NoSQL**: `4_no_sql.md` - Characteristics, aggregates, CAP theorem
- **Demo Notebook**: `demo.ipynb` - Original demos (expand with this guide)

---

## 🎓 Expected Exam Questions

**Q: Why Cassandra over MongoDB?**
A: Cassandra is masterless (true distributed), MongoDB has a master-replica setup. Cassandra handles writes better at scale.

**Q: How do you ensure data consistency if CL=ONE?**
A: By reading at CL=QUORUM, which requires 2 replicas agree. If one replica is stale, the newer value is returned.

**Q: What happens if all 3 nodes fail?**
A: Data loss. This is why RF=3 isn't enough - you need geographic replication (multi-DC).

**Q: Can Cassandra do transactions like SQL?**
A: Single-row transactions only (ACID within one partition). No multi-row transactions. This is the trade-off for scalability.

**Q: Why append-only architecture?**
A: No read-before-write (RBW). Traditional databases read old value, modify, write back = slow. Cassandra just appends = fast.

---

## 🌟 Pro Tips

1. **Use analogies**: "Cassandra is like a P2P network (BitTorrent) for databases, not client-server (traditional DB)"

2. **Show real numbers**: "100K writes/sec per node vs. 10K for traditional databases"

3. **Emphasize Big Data connection**: "HDFS stores files, Cassandra stores structured data at massive scale"

4. **Mention your exam context**: "In this IoT project, we need Cassandra because sensors produce 100 events/sec"

5. **Address the struggle**: "Yes, Cassandra is complex. But the trade-offs are worth it for Big Data"

---

## Good luck with your exam! 🍀

Remember:
- **Part 1-2**: Quick context setting (4 min total)
- **Part 3**: This is where you show deep understanding (8-10 min)
- **Part 4**: Concrete proof your system works (3-5 min)
- **Part 5**: Wrap up and show you understand when to use it (1 min)

The examiners are looking for:
✅ Understanding of Cassandra's architecture  
✅ Connection to Big Data challenges (Volume, Velocity, Variety, Veracity)  
✅ Practical knowledge (tunable consistency, replication, scaling)  
✅ Trade-offs (you can't have everything in distributed systems)  

Good luck! 🚀