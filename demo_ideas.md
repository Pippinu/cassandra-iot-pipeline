## Show vs. Explain: Full Breakdown

### Ring Architecture & Node Management ✅ SHOW

This is one of the most visually compelling demos you can do:

- **Add a node:** spin up a 4th Docker container using the same image, join the cluster. Run `nodetool status` before and after — you'll see token ranges redistribute in real time.
- **Pause/kill a node:** `docker pause cassandra_node_3` then run `nodetool status` — the node goes `DN` (Down/Normal). Write data to the cluster and show it still works (hinted handoff at work). Then unpause it and run `nodetool repair` to show hints being delivered.
- **VNodes:** run `nodetool ring` to show the many virtual token ranges per physical node — visually shows why vnode distribution is more balanced than the old single-token approach.

> **Just explain:** the internal consistent hashing math itself — showing it is cumbersome and the `nodetool` output already proves the concept.

***

### Sparse Columns / NULL behavior ✅ SHOW (partially)

- **Show:** insert rows with different subsets of columns populated using CQL (`INSERT INTO ... (col_a, col_b) VALUES ...` on some rows, `INSERT INTO ... (col_a, col_c) VALUES ...` on others). `SELECT *` will show `null` for missing columns cleanly.
- **Explain (don't show):** the LSM-tree storage model and why no bytes are wasted for those NULLs. You can support this with a one-slide diagram comparing RDBMS fixed-width row storage vs. Cassandra's cell-based SSTable format. This is an internal implementation detail — no clean CQL command surfaces it.

***

### Partition Keys & Clustering Columns ✅ SHOW

- **Show:** contrasting two tables: one with a bad primary key (just `sensor_id`) that creates a hot partition vs. a well-designed one with `(sensor_type, date)` as partition key and `timestamp DESC` as clustering column. Run `EXPLAIN` equivalent using `TRACING ON` in CQL — you'll see the difference in partition traversals.
- **Show:** `SELECT * FROM table WHERE sensor_type = 'temperature' AND date = '2026-04-14' ORDER BY timestamp DESC LIMIT 10` — the clustering column is doing both sorting AND identification at once.
- **Explain:** the historical context of SuperColumns — why they felt like a good idea (nested maps), why they became a maintenance nightmare (no schema, opaque serialization), and how modern column families replaced them cleanly. No point trying to demo deprecated Thrift-era features.

***

### SSTable Compaction ✅ SHOW

This is actually very easy to trigger in Docker:

```bash
# Force flush memtable to SSTable
nodetool flush keyspace_name table_name

# Then force compaction
nodetool compact keyspace_name table_name
```

Run these in sequence. Before compaction, use `nodetool tablestats` to show multiple SSTables. After, show they've been merged into one. You can also briefly show a **tombstone** by deleting a row and flushing — then explain that compaction is when tombstones are finally garbage collected (after `gc_grace_seconds`).

***

### CAP Theorem & Consistency Levels ✅ SHOW

This is arguably the *easiest* and most impressive live demo:

```sql
-- In CQL terminal, per-operation:
CONSISTENCY ONE;
INSERT INTO sensor_readings ... ;

CONSISTENCY QUORUM;
SELECT * FROM sensor_readings WHERE ... ;

CONSISTENCY ALL;
SELECT * FROM sensor_readings WHERE ... ;
```

Pair this with pausing a node — then show that `CONSISTENCY ONE` still works while `CONSISTENCY ALL` throws `NoHostAvailableException`. This makes CAP **tangible** rather than theoretical: you've just demonstrated AP behavior (availability over consistency) in real time.

***

## What Else Is Worth Adding?

Here are two more topics that complement your list well:

**Write Path w/ Tombstones** — since you're already showing compaction, extend it by demonstrating that a `DELETE` in Cassandra doesn't immediately remove data. Insert a row, delete it, flush, then `SELECT` it — it's "gone" logically but still physically present as a tombstone until compaction passes `gc_grace_seconds`. This surprises people and directly reinforces the LSM-tree write-path theory you studied.

**Replication Factor & Keyspace Design** — when creating your keyspaces, use `NetworkTopologyStrategy` (even in your local Docker cluster with a simulated datacenter) and set `replication_factor: 2`. Then show that with 3 nodes and RF=2, each piece of data lives on 2 nodes. This directly connects to the hinted handoff demo — it *works* because of replication.

***

## Recommended Demo Order for the Presentation

| Order | Topic | Mode |
|-------|-------|------|
| 1 | Keyspace + Column Family design (show all 5 tables) | Show in CQL |
| 2 | Partition key vs. clustering column — live query contrast | Show in CQL |
| 3 | Sparse columns / NULL rows | Show in CQL |
| 4 | CAP + Consistency levels, node pause | Live terminal demo |
| 5 | Hinted handoff (pause node → write → unpause → repair) | Live terminal demo |
| 6 | Add a node, `nodetool ring` / `nodetool status` | Live terminal demo |
| 7 | Flush + Compaction + Tombstones | Script + nodetool |
| 8 | LSM-tree NULL efficiency vs. RDBMS | Explain with diagram slide |
| 9 | SuperColumn history | Explain only |

This order builds naturally: data model first, then operational characteristics, then storage internals. Want me to now look at your files so we can start implementing the revised schema and consumer logic?