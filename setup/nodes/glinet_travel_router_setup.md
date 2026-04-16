# GL.iNet WiFi 7 Travel Router — Tailscale Setup Guide

## Purpose
Keep the M2 MacBook Pro connected to Bob's network securely from anywhere.
When traveling, the M2 connects to the GL.iNet travel router's WiFi, which
tunnels all traffic back to the home Tailnet via Tailscale.

## Architecture

### At Home
M2 (LAN: 192.168.1.x) <--LAN--> Bob (192.168.1.189)
M2 (Tailscale: x.x.x.x) <--Tailscale--> Bob (Tailscale: 100.89.1.51)

### Traveling
M2 --> GL.iNet WiFi --> Hotel/Airport Internet --> Tailscale Tunnel --> Bob (100.89.1.51)

## GL.iNet Router Setup (One-Time)

1. Power on the GL.iNet travel router and connect to its WiFi (default: GL-XXXX)
2. Access admin panel at http://192.168.8.1
3. Go to **Applications > Tailscale**
4. Click **Enable** and sign in with your Tailscale account
5. Enable **Allow Remote Access LAN**
6. In the Tailscale admin console (https://login.tailscale.com/admin/machines):
   - Find the GL.iNet device
   - Click the three dots > Edit route settings
   - Approve the advertised subnet (192.168.8.0/24)

## Travel Workflow

1. Plug in the GL.iNet router at the hotel/location
2. Connect it to the available internet (WiFi repeater, ethernet, or tethering)
3. Connect the M2 to the GL.iNet WiFi
4. Tailscale tunnel activates automatically
5. Bob can reach M2's Ollama at the M2's Tailscale IP
6. All traffic between M2 and Bob is encrypted

## Two Connectivity Options

### Option A: Tailscale on the GL.iNet Router (Recommended for Travel)
- All devices on the GL.iNet WiFi get tunneled
- No Tailscale needed on individual devices
- Router handles the VPN overhead
- GL.iNet Slate 7 WireGuard throughput: up to 490 Mbps

### Option B: Tailscale Directly on the M2 (Simpler)
- Works without the travel router
- M2 connects to any WiFi and Tailscale tunnels directly
- Good as a backup if the router is not available
- Run: `tailscale up --accept-routes`

### Recommended: Use Both
- Tailscale on the M2 directly (always connected to tailnet)
- GL.iNet router as a travel WiFi with additional Tailscale subnet routing
- This gives double redundancy — M2 stays reachable even if one method fails

## Security Notes
- All traffic between M2 and Bob is encrypted via WireGuard (Tailscale)
- No ports need to be opened on the home router
- No port forwarding required
- The GL.iNet router adds a second layer of network isolation when on untrusted WiFi
- Bob's Tailscale IP: 100.89.1.51 (stable, never changes)

## Verifying Connectivity
From Bob:
  curl http://<m2-tailscale-ip>:11434/api/tags

From M2:
  curl http://100.89.1.51:11434/api/tags

If both return model lists, the tunnel is working.
