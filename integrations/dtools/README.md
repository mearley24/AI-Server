# D-Tools Cloud Bridge

REST bridge that connects Bob (The Conductor) to your D-Tools Cloud account. Bob can read opportunities, projects, clients, and product catalog data — and you can mark items in D-Tools for Bob to pick up.

## Architecture

```
You (D-Tools Cloud UI)  ──→  Mark items / add notes
                                    ↓
Bob (OpenClaw)  ──→  D-Tools Bridge (port 5050)  ──→  D-Tools Cloud API
                                    ↑
@dtools agent   ──→  Reads pipeline, catalog, clients
```

## Quick Start

```bash
cd ~/AI-Server/integrations/dtools
bash setup_dtools_bridge.sh
```

The setup script will:
1. Prompt for your D-Tools Cloud API key (if not set)
2. Build the Docker container
3. Start the bridge service on port 5050
4. Run a health check

## Get Your API Key

1. Log into [D-Tools Cloud](https://dtcloud.d-tools.cloud)
2. Go to **Settings → Integration → Developer → API Keys**
3. Click **Create API Key**
4. Copy the key

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check + connection status |
| GET | `/snapshot` | Quick overview (recent opps, projects, clients) |
| GET | `/opportunities?status=Open` | List opportunities |
| GET | `/projects?status=Active` | List projects |
| GET | `/clients` | List all clients |
| GET | `/catalog?q=sonos` | Search product catalog |
| GET | `/pipeline` | Active pipeline (open opps + active projects) |
| GET | `/client/Smith` | Find client by name + their projects |
| POST | `/opportunity/notes` | Add notes to an opportunity |

## How Bob Uses This

### Daily Digest
Bob's morning Telegram digest includes a D-Tools pipeline summary:
```
/dtools — View active opportunities & projects
```

### Proposal Generation
The @proposals agent calls `/pipeline` and `/catalog` to:
- Pull active opportunity details
- Look up product pricing from the catalog
- Generate accurate proposals with real line items

### Marking Items for Bob
In D-Tools Cloud, add notes to opportunities like:
- `@bob: draft proposal for this by Friday`
- `@bob: check pricing on Lutron alternatives`
- `@bob: follow up with client next week`

Bob scans these notes and creates tasks automatically.

## Manual Testing

```bash
# Quick snapshot
curl http://localhost:5050/snapshot | python3 -m json.tool

# Active pipeline
curl http://localhost:5050/pipeline | python3 -m json.tool

# Search catalog
curl 'http://localhost:5050/catalog?q=control4' | python3 -m json.tool

# Find client
curl http://localhost:5050/client/Johnson | python3 -m json.tool
```

## CLI Mode

You can also use the client directly without the server:

```bash
# Set API key
export DTOOLS_API_KEY=your-key-here

# Run commands
python3 dtools_client.py snapshot
python3 dtools_client.py opportunities --status Open
python3 dtools_client.py projects --status Active
python3 dtools_client.py clients
python3 dtools_client.py catalog --keyword "sonos"
python3 dtools_client.py pipeline
python3 dtools_client.py find-client --client "Smith"
```

## Docker

```bash
# Start
docker-compose -f docker-compose.dtools.yml up -d

# View logs
docker logs -f dtools_bridge

# Restart
docker-compose -f docker-compose.dtools.yml restart

# Stop
docker-compose -f docker-compose.dtools.yml down
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DTOOLS_API_KEY` | Yes | — | Your D-Tools Cloud API key |
| `DTOOLS_BRIDGE_PORT` | No | `5050` | Bridge server port |
| `LOG_LEVEL` | No | `INFO` | Logging level |

## API Authentication

The bridge handles auth automatically. Two headers are sent with every request:
- `Authorization: Basic ...` (fixed D-Tools Cloud header)
- `X-API-Key: <your key>` (your account-specific key)

## Files

```
integrations/dtools/
├── dtools_client.py           # Python API client (standalone + importable)
├── dtools_server.py           # Flask REST bridge server
├── docker-compose.dtools.yml  # Docker config
├── Dockerfile                 # Container build
├── requirements.txt           # Python dependencies
├── setup_dtools_bridge.sh     # One-command setup
├── .env.example               # Environment template
└── README.md                  # This file
```
