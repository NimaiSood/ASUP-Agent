# ASUP Agent — ONTAP Data Plane RCA

Autonomous Level 5 agent for NetApp ONTAP deep data plane diagnostics. Extracts, decrypts, and performs Root Cause Analysis on performance issues from AutoSupport (ASUP) archives, EMS logs, and Harvest telemetry.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Cursor Agent   │────▶│  Harvest MCP     │────▶│ Prometheus /        │
│  (ReAct loop)   │     │  (telemetry)     │     │ VictoriaMetrics     │
└────────┬────────┘     └──────────────────┘     └─────────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│  ONTAP MCP      │────▶│  ONTAP REST API  │
│  (operations)   │     │  EMS / ASUP / Vol│
└────────┬────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐
│  ASUP Parser    │  syslog, wafl.log, statit
└─────────────────┘
```

## RCA Workflow (mandatory sequence)

1. **Telemetry Ingestion** — Query Harvest MCP for KeyPerf/StatPerf metrics around the anomaly window. Identify anomalous SVM and volumes.
2. **Log Extraction** — Query ONTAP MCP for filtered EMS events (WAFL, nblade, stat storms, resource exhaustion).
3. **ASUP Retrieval & Parsing** — If telemetry + EMS are insufficient, pull/parse ASUP via ONTAP MCP and local parser.
4. **Data Correlation** — Build chronological timeline crossing Harvest metrics, EMS, and ASUP artifacts.
5. **Hypothesis Generation** — Produce ≥3 root-cause hypotheses (Nblade latency, Large IO lifecycle, FlexGroup stat storm, etc.).
6. **Validation & Remediation** — Rank hypotheses by evidence; output structured remediation plan.

## Focus Areas

| Mechanism | Signals | Harvest Metrics | EMS Patterns |
|-----------|---------|-----------------|--------------|
| **Nblade latency** | Network processing delays | `node_cpu`, latency histograms, protocol ops | `nblade.*`, `cs.*`, network queue events |
| **Large IO lifecycles** | Fragmentation, WAFL alloc, disk serialization | `volume_read_latency`, `disk_busy`, large IO counters | `wafl.*`, `large_io.*` |
| **FlexGroup stat storms** | Metadata concurrency across constituents | per-constituent stat ops, CPU on nodes | `stat.*`, `flexgroup.*`, CPU starvation |

## MCP Tools

### Harvest MCP (external — NetApp official)

- Container: `ghcr.io/netapp/harvest-mcp:latest`
- Env: `HARVEST_TSDB_URL=http://<prometheus>:9090`
- Use for: PromQL queries, metric discovery, latency/capacity baselines

### ONTAP MCP (this repo — `ontap_mcp/`)

- `get_ems_events` — Filtered EMS log retrieval
- `get_volume_stats` — Volume performance counters
- `list_autosupport_messages` — ASUP message history
- `invoke_autosupport` — Trigger on-demand ASUP (guardrailed)
- `parse_asup_archive` — Decrypt and parse local ASUP package

## Guardrails

- Read-only by default; mutating operations require explicit approval.
- ASUP invoke is rate-limited (max 1 per node per hour).
- Credentials via environment variables only — never commit secrets.

## Invocation

Provide an incident context:

```
Cluster: <name>
Window:  <start> to <end> UTC
Symptom: <latency spike / stat storm / large IO stall>
SVM/Volumes: <optional scope>
ASUP path: <optional local archive path>
```

The agent executes the RCA workflow autonomously and returns a structured report.
