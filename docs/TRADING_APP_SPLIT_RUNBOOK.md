# Trading App Split Runbook

This runbook covers running separated Work API + Trading API and iOS apps.

## Processes

- Work API: `api/mobile_api.py` on `:8420`
- Trading API: `api/trading_api.py` on `:8421`

## Start Trading API Manually

```bash
bash api/start_trading_api.sh
```

## Install Trading API launchd

```bash
cp setup/launchd/com.symphony.trading-api.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.symphony.trading-api.plist
```

## Validate Endpoints

```bash
curl http://localhost:8421/health
curl http://localhost:8421/portfolio
curl http://localhost:8421/memory/curator/status
```

## iOS Apps

- Work app project: `ios-app/SymphonyOps/SymphonyOps.xcodeproj`
- Trading app project: `ios-app/SymphonyTrading/SymphonyTrading.xcodeproj`

Build helpers:

```bash
bash ios-app/build_simulator.sh
bash ios-app/build_trading_simulator.sh
```
