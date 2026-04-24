# NotebookLM instruction prompt for a visual-first Cassandra slide deck

You are generating a **visual-first academic slide deck** about **Apache Cassandra in an IoT streaming project**.

This presentation must teach Cassandra clearly, but it must do so in a **highly visual way**:
- diagrams first,
- structure second,
- minimal text third.

Do **not** generate a discursive or paragraph-heavy deck.  
Do **not** turn slides into textbook pages.  
Do **not** overload single slides with too many concepts.

The accompanying **project notes file** is the factual truth source for the project architecture, keyspaces, schema, tables, and implementation details.  
This prompt defines the **instruction set for deck structure, pacing, visual style, and teaching priorities**.

---

## Core presentation goal

The goal of the deck is to explain:

1. what Cassandra is,
2. why it is suitable for distributed write-heavy systems,
3. how its data model and storage engine work,
4. how those ideas are visible in a real IoT pipeline,
5. and how advanced Cassandra 5 features such as **SAI** and **vector search** extend that model.

The audience should finish the presentation thinking:

> “I understand Cassandra better, and I can see how its architecture and schema design directly shaped this IoT project.”

---

## Absolute style rules

These rules are mandatory.

### 1. Visual-first slides
Each slide must have **one dominant visual idea**:
- a diagram,
- a flow,
- a ring illustration,
- a schema-key breakdown,
- a table-to-query mapping,
- a write-path graphic,
- an index comparison visual,
- or a vector-search concept visual.

Text should support the visual, not replace it.

### 2. Minimal on-slide text
Default target per slide:
- title,
- subtitle or one short takeaway,
- 2–4 very short bullets **maximum** if needed.

Avoid long paragraphs.  
Avoid full-sentence narration unless absolutely necessary.  
Prefer labels, callouts, captions, and short contrastive phrases.

### 3. One concept per slide
If a concept is dense, **split it into multiple slides** instead of compressing it.  
Do not merge multiple large Cassandra concepts into one crowded slide.

### 4. Use generated visuals aggressively
For concept-heavy topics, prefer:
- AI-generated hash ring diagrams,
- token / vnode partition illustrations,
- replication overlays,
- partition-key routing graphics,
- storage-engine pipelines,
- SSTable compaction diagrams,
- SAI vs classic indexing comparison visuals,
- vector-search concept diagrams,
- and architecture diagrams for the project.

### 5. Do not make it read like a chapter
The speaker will explain the content verbally.  
Slides should act as:
- structure,
- memory anchors,
- and visual evidence.

The deck must therefore be **slide-native**, not note-native.

---

## Recommended deck size

There is **no hard slide limit**.  
Prefer a deck in the **20–24 slide range** if that produces cleaner visual separation of concepts.

It is better to have:
- more slides,
- cleaner visuals,
- and simpler slide messages,

than fewer slides overloaded with dense Cassandra theory.

---

## Narrative arc

The deck should still follow a clear intellectual progression:

### Part 1 — Cassandra as a distributed system
Explain what Cassandra is, why it exists, and how its masterless peer-to-peer architecture works.

### Part 2 — Distribution and partitioning
Explain the ring, token distribution, vNodes, replication, and why the partition key is central.

### Part 3 — Data model and query-first design
Explain keyspace/table/partition ideas, then primary key anatomy, then query-first modeling and denormalization.

### Part 4 — Project evidence
Show how the IoT pipeline and its Cassandra schema embody those principles.

### Part 5 — Storage engine and indexing
Explain the LSM write path, immutable SSTables, compaction, and then move into SAI.

### Part 6 — Cassandra 5 advanced feature
Present vector search as a natural extension of the project’s analytics model.

### Part 7 — Positioning and bridge to demo
End with Cassandra vs other systems, CAP/tunable consistency, and the live demo bridge.

---

## Expanded slide structure

Use the following slide sequence as the preferred structure.

---

### Slide 1 — Title / thesis
Visual goal:
- strong title slide,
- Cassandra as the main subject,
- IoT pipeline as the case-study environment.

Visual idea:
- abstract distributed-systems visual.

Text should establish:
- this is a Cassandra-centered project presentation,
- not just a generic pipeline overview.

---

### Slide 2 — Why Cassandra
Visual goal:
- show Cassandra’s problem space.

Visual idea:
- comparison-style visual: centralized DB vs distributed always-on write-heavy system.

Minimal content:
- high availability,
- horizontal scalability,
- high write throughput,
- good fit for streaming / IoT workloads.

---

### Slide 3 — Peer-to-peer architecture
Visual goal:
- show that Cassandra is masterless.

Visual idea:
- cluster of equal nodes, no central master, any node can coordinate.

Minimal content:
- all nodes are peers,
- no permanent leader,
- decentralized request coordination.

---

### Slide 4 — Gossip and cluster membership
Visual goal:
- explain how the cluster knows itself.

Visual idea:
- node-to-node membership/status exchange diagram.

Minimal content:
- gossip at high level,
- node awareness,
- decentralized topology knowledge.

Do not go too deep; keep it conceptual.

---

### Slide 5 — Hash ring overview
Visual goal:
- explain consistent hashing visually.

Visual idea:
- a clear ring diagram with token space and node ownership.

Minimal content:
- partition key is hashed,
- token determines placement,
- ring organizes ownership.

This slide should be mostly diagram.

---

### Slide 6 — vNodes
Visual goal:
- explain why each physical node owns many token ranges.

Visual idea:
- same ring, but broken into multiple colored vnode ranges per physical node.

Minimal content:
- better balance,
- easier scaling,
- smoother rebalancing.

This should be a separate slide from the hash ring.

---

### Slide 7 — Replication factor on the ring
Visual goal:
- show replicas across the ring.

Visual idea:
- one partition highlighted, then replicas shown on multiple nodes.

Use the project context:
- 3 Cassandra nodes,
- RF=2.

This slide should connect abstract replication to the actual project deployment.

---

### Slide 8 — Why partition key matters
Visual goal:
- show that the partition key controls both placement and grouping.

Visual idea:
- one side: good partitioning,
- other side: bad partitioning / overloaded partition.

Minimal content:
- determines placement,
- groups related rows,
- defines efficient query scope.

This is one of the most important slides.

---

### Slide 9 — Cassandra data hierarchy
Visual goal:
- simplify the model hierarchy.

Visual idea:
- cluster -> keyspace -> table -> partition -> row -> column.

Do not include every key detail here.  
This is just the structural hierarchy slide.

---

### Slide 10 — Primary key anatomy
Visual goal:
- explain primary key, partition key, and clustering columns.

Visual idea:
- annotated table key example showing:
  - partition key,
  - clustering columns,
  - ordering inside a partition.

This slide should be separate from the previous one.

---

### Slide 11 — Super columns, briefly
Visual goal:
- provide historical context.

Visual idea:
- small “old model vs modern CQL model” comparison.

Content:
- what super columns were at a high level,
- why clustering-column-based tables are cleaner.

This slide must be short.

---

### Slide 12 — Query-first modeling
Visual goal:
- show how Cassandra schema starts from access patterns.

Visual idea:
- “query -> table design” flow,
- or one question mapping to one table.

Minimal content:
- tables are built around queries,
- denormalization is expected,
- joins are not the center.

This is a key slide.

---

### Slide 13 — Project architecture
Visual goal:
- introduce the real pipeline.

Visual idea:
- producer -> Kafka topics -> Spark Structured Streaming -> Cassandra keyspaces.

Use actual project components from the notes source.

This is the first slide where the project becomes the main concrete evidence.

---

### Slide 14 — Raw ingestion tables
Visual goal:
- show query-first modeling in the raw layer.

Visual idea:
- table cards or a schema map for:
  - `temp_humidity_by_sensor`,
  - `light_by_sensor`,
  - `power_by_sensor`,
  - `devices_metadata`.

Explain briefly what each table is for and what query it supports.

---

### Slide 15 — Location-centric table and sparse rows
Visual goal:
- highlight `readings_by_location`.

Visual idea:
- one example row shape showing some columns present and others absent.

This slide should visually explain:
- wide-column thinking,
- sparse storage,
- and why absent cells fit Cassandra well.

This is one of the strongest Cassandra-specific project slides.

---

### Slide 16 — Alerts and analytics tables
Visual goal:
- show the analytical extension of the model.

Visual idea:
- small grouped table family for:
  - `sensor_alerts`,
  - `sensor_aggregates_30s`,
  - `aggregates_by_type`.

Explain these as read-optimized derived views, not as raw ingestion.

---

### Slide 17 — Write path overview
Visual goal:
- explain the LSM write path.

Visual idea:
- linear write flow:
  CommitLog -> MemTable -> SSTable.

Minimal content:
- append-first,
- fast writes,
- immutable SSTables.

This slide should not also include compaction and the full read path in detail.

---

### Slide 18 — SSTables and compaction
Visual goal:
- explain immutable files and compaction separately.

Visual idea:
- several SSTables merged into fewer optimized SSTables.

Minimal content:
- immutable storage files,
- background merge,
- better long-term read organization.

This deserves its own slide.

---

### Slide 19 — Read path at a high level
Visual goal:
- give a conceptual read-path explanation.

Visual idea:
- query arrives -> partition lookup -> SSTable-level search -> result merge.

Keep this conceptual and lightweight.

---

### Slide 20 — Traditional indexes vs SAI
Visual goal:
- show why SAI matters.

Visual idea:
- side-by-side comparison:
  classic index limitations vs SAI as modern storage-attached indexing.

Minimal content:
- classic distributed indexing is tricky,
- SAI integrates better with Cassandra’s storage model,
- richer query support becomes practical.

This is one of the anchor slides.

---

### Slide 21 — Cassandra 5 vector search
Visual goal:
- show vector storage and ANN conceptually.

Visual idea:
- sensor behavior -> vector embedding -> similarity search.

Minimal content:
- `VECTOR<FLOAT, n>`,
- ANN search,
- similarity over recent behavior.

Keep it grounded and technical, not hype-driven.

---

### Slide 22 — Vector search in this project
Visual goal:
- connect vector search to the actual table design.

Visual idea:
- room/type partition -> sensor profiles -> nearest neighbors.

Use the real project logic:
- `sensor_behavior_profiles`,
- partitioning by room and sensor type,
- similarity among peer sensors.

This is where the Cassandra 5 feature becomes concrete.

---

### Slide 23 — Cassandra vs other databases
Visual goal:
- position Cassandra clearly.

Visual idea:
- comparison matrix or workload-space diagram.

Compare conceptually with:
- relational systems,
- document systems,
- Dynamo-like key-value systems.

Do not make this slide too text heavy.

---

### Slide 24 — CAP, tunable consistency, and demo bridge
Visual goal:
- end with distributed tradeoffs and prepare the live demo.

Visual idea:
- small CAP/tunable consistency visual plus final project architecture recap.

Use this slide to bridge into the notebook/demo:
- schema design,
- analytics queries,
- SAI,
- vector similarity search.

This should close the deck cleanly.

---

## Content priorities

The most important slides in the deck are:

- partition key,
- query-first modeling,
- project architecture,
- raw / location-centric schema evidence,
- write path,
- SAI,
- vector search in the project.

These slides should receive the most visual care.

---

## Visual recommendations by topic

Use these visual directions where appropriate:

- Hash ring: clean circular ownership diagram.
- vNodes: ring split into multiple small token ranges per node.
- Replication: one partition copied across multiple ring positions.
- Partition key: routing + grouping visual.
- Data hierarchy: nested container diagram.
- Primary key anatomy: annotated schema snippet.
- Query-first modeling: query → dedicated table mapping.
- Project architecture: end-to-end streaming diagram.
- Sparse rows: highlighted present vs absent columns.
- Write path: linear storage-engine pipeline.
- Compaction: many SSTables merging into fewer SSTables.
- SAI: classic index vs storage-attached index contrast.
- Vector search: behavior vectors clustered by similarity.

---

## Tone requirements

The tone must remain:
- academic,
- technically serious,
- concise,
- and visually explainable.

Avoid:
- startup pitch language,
- exaggerated AI language,
- long slide narration,
- and generic database hype.

When discussing vector search, describe it as:
- an advanced Cassandra 5 capability,
- useful because vectors are stored inside the same operational analytics model,
- not as a flashy AI gimmick.

---

## Truth-source rule

The accompanying project notes file is the factual authority for:
- architecture,
- table names,
- keyspaces,
- replication settings,
- stream structure,
- and project design details.

If there is any conflict:
- the project notes file wins for facts,
- this prompt wins for structure and visual philosophy.

Do not invent tables, components, or implementation choices not supported by the notes.

---

## Final output expectation

Generate a deck that is:
- highly visual,
- academically structured,
- conceptually clean,
- based on many small clear slides instead of a few overloaded ones,
- and strongly grounded in the real project.

The deck must feel like:
- Cassandra explained properly,
- then Cassandra demonstrated concretely,
- then Cassandra extended with SAI and vector search.