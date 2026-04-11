# Voice Receptionist — Go-Live Checklist

## Prerequisites
- [ ] Twilio account active with phone number provisioned
- [ ] TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env
- [ ] SYMPHONY_PHONE set to the Twilio number (E.164 format: +1XXXXXXXXXX)
- [ ] OPENAI_API_KEY set with Realtime API access
- [ ] SERVER_URL set to public HTTPS URL (Bob needs to be reachable from Twilio)

## Networking
- [ ] Bob's Mac Mini is reachable from the internet on port 8093 (or reverse proxy)
- [ ] TLS certificate valid (Twilio requires HTTPS for webhooks, WSS for media streams)
- [ ] Option A: Use cloudflared tunnel (recommended — no port forwarding needed)
- [ ] Option B: Use ngrok (for testing)
- [ ] Option C: Port forward 8093 through router + Let's Encrypt cert

## Twilio Configuration
- [ ] TwiML App created (or use voice webhook directly)
- [ ] Phone number voice webhook set to: POST https://YOUR_URL/incoming-call
- [ ] Test call placed from a real phone — verify Bob answers and speaks

## Post-Go-Live
- [ ] Set VOICE_SERVER_URL in .env to the public URL
- [ ] Verify call logging works (check /data/voice-receptionist/bob.db)
- [ ] Verify calendar scheduling works (make a test appointment)
- [ ] Monitor OpenAI costs — each call uses Realtime API ($0.06/min audio)

## Recommended: Cloudflare Tunnel Setup
```zsh
brew install cloudflare/cloudflare/cloudflared
cloudflared tunnel login
cloudflared tunnel create bob-voice
cloudflared tunnel route dns bob-voice voice.symphonysh.com
```

Then add to docker-compose.yml or run as launchd service:
```zsh
cloudflared tunnel run --url http://localhost:8093 bob-voice
```
