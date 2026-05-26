# ASUP Agent

Autonomous NetApp ONTAP data-plane RCA agent. Correlates Harvest telemetry, EMS logs, and AutoSupport archives to isolate Nblade latency, Large IO lifecycle, and FlexGroup stat-storm bottlenecks.

## Quick Start

### 1. Install dependencies

```bash
cd ontap_mcp && pip install -e .
cd ../asup_agent && pip install -e .
```

### 2. Run the agent (interactive)

By default the agent prompts for ONTAP credentials on the command line:

```bash
python3 -m asup_agent.agent
```

```
--- ONTAP Cluster Connection ---

Cluster management IP or hostname: 192.168.1.50
Username: admin
Password: 
Verify TLS certificate? [Y/n]: y
```

You can also pass credentials as flags (password still prompts if omitted):

```bash
python3 -m asup_agent.agent --cluster-ip 192.168.1.50 --username admin
```

Or via environment variables:

```bash
export ONTAP_MGMT_HOST=https://cluster-mgmt.example.com
export ONTAP_USERNAME=admin
export ONTAP_PASSWORD=<password>
python3 -m asup_agent.agent
```

Demo mode (no cluster connection):

```bash
python3 -m asup_agent.agent --demo
```

### 3. Configure MCP servers in Cursor

Copy `config/mcp.json.example` to `~/.cursor/mcp.json` (merge with existing entries) and set your endpoints:

- **harvest-mcp** — points at your Prometheus/VictoriaMetrics with Harvest data
- **ontap-mcp** — runs the local ONTAP MCP server from this repo

Restart Cursor after updating MCP config.

### 4. Run an RCA in Cursor

In Cursor Agent chat, provide incident context:

```
Cluster: prod-cluster-01
Window: 2026-05-20T14:00:00Z to 2026-05-20T15:30:00Z
Symptom: NFS read latency spike on flexgroup vol_fg01
```

The agent follows the workflow in [AGENTS.md](AGENTS.md).

## Project Layout

```
ASUP Agent/
├── AGENTS.md              # Agent operational spec
├── config/
│   └── mcp.json.example   # MCP server configuration template
├── ontap_mcp/             # ONTAP MCP server (EMS, volumes, ASUP)
├── asup_agent/            # ASUP parser + RCA workflow engine
├── prompts/
│   └── rca_system.md      # System prompt for RCA sessions
└── .cursor/rules/         # Persistent Cursor agent rules
```

## ONTAP MCP Server (standalone)

```bash
cd ontap_mcp
pip install -e .
ontap-mcp
```

## ASUP Archive Parsing (CLI)

```bash
asup-parse /path/to/autosupport.7z --output /tmp/asup_out
```

Supports `.7z`, `.tar.gz`, and extracted directories. Encrypted archives require `ASUP_DECRYPT_KEY` or a sidecar `.key` file.

## Harvest MCP (external)

Deploy NetApp's official Harvest MCP server:

```bash
docker run -d \
  --name harvest-mcp-server \
  -p 8082:8082 \
  -e HARVEST_TSDB_URL=http://your-prometheus:9090 \
  ghcr.io/netapp/harvest-mcp:latest \
  start --http --port 8082 --host 0.0.0.0
```

See [Harvest MCP docs](https://netapp.github.io/harvest/nightly/mcp/installation/).

## License

Internal use — NetApp ONTAP diagnostics tooling.
