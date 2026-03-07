# Symphony iOS Apps

Native iOS apps for work operations and trading operations.

## Apps

- **SymphonyOps** (work-only): proposals, services, automation, Cortex work facts
- **SymphonyTrading** (trading-only): portfolio, scan/research, trading memory scope

## Requirements

- iOS 16.0+
- Xcode 15.0+
- API server running (`api/mobile_api.py`)

## Setup

### 1. Start the API Server

```bash
cd ~/AI-Server
pip install fastapi uvicorn
python3 api/mobile_api.py
```

API runs at `http://localhost:8420`

### 2. Open in Xcode

```bash
open ios-app/SymphonyOps/SymphonyOps.xcodeproj
open ios-app/SymphonyTrading/SymphonyTrading.xcodeproj
```

### 3. Build & Run

- Select your iPhone or Simulator
- Press Cmd+R to build and run

### 3b. CLI build helper (simulator)

If your shell is using CommandLineTools and `xcodebuild` fails, use:

```bash
bash ios-app/build_simulator.sh
```

Optional overrides:

```bash
SCHEME=SymphonyOps CONFIGURATION=Debug SDK=iphonesimulator bash ios-app/build_simulator.sh
```

Trading app helper:

```bash
bash ios-app/build_trading_simulator.sh
```

### 4. Configure Connection

In the app Settings tab:
- **Local**: Use `http://localhost:8420` (Simulator only)
- **Tailscale**: Use your Mac's Tailscale hostname like `http://bob-mac-mini:8420`

## Remote Access via Tailscale

To control Bob from anywhere:

1. Install Tailscale on your Mac and iPhone
2. Start the API server on your Mac
3. In iOS app, set URL to your Mac's Tailscale name

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/dashboard` | GET | Full dashboard data |
| `/services` | GET | Service status list |
| `/bids` | GET | Check BuildingConnected bids |
| `/proposals` | GET | List all proposals |
| `/research` | POST | Search knowledge base |
| `/website/status` | GET | Website health check |
| `/subscriptions` | GET | List subscriptions |
| `/morning` | GET | Run morning checklist |

## Architecture

```
┌──────────────┐     HTTP/JSON     ┌──────────────┐
│   iOS App    │ ←───────────────→ │  Mobile API  │
│ (SwiftUI)    │                   │  (FastAPI)   │
└──────────────┘                   └──────┬───────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  Bob Tools   │
                                   │  & Scripts   │
                                   └──────────────┘
```

## Files

```
ios-app/
├── README.md
├── build_simulator.sh              # CLI simulator build with Xcode DEVELOPER_DIR
├── SymphonyOps/
│   ├── SymphonyOps.xcodeproj/
│   └── SymphonyOps/
│       ├── SymphonyOpsApp.swift
│       ├── ContentView.swift
│       ├── APIClient.swift
│       └── Assets.xcassets/
└── SymphonyTrading/
    ├── SymphonyTrading.xcodeproj/
    ├── SymphonyTrading/
    │   ├── SymphonyTradingApp.swift
    │   ├── ContentView.swift
    │   ├── APIClient.swift
    │   └── Assets.xcassets/
    └── README.md
```

## Next Steps

1. Add app icon (1024x1024 PNG)
2. Add push notifications for alerts
3. Add widgets for iOS home screen
4. Add Siri shortcuts
