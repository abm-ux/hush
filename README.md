# hush

the baby monitor you already own - turn a spare phone into a gentle listener, share a link, and anyone can check in live from any browser. no app to install, no account, nothing to buy.

## what it does

- **nursery phone** — any spare phone or tablet runs the mic, white/brown noise, and cry detection (sensitivity, min cry length, self-soothe window)
- **watch page** — anyone with the link gets live status, a sound toggle (real audio over webrtc), the self-soothe countdown, remote white-noise control, and a per-session timeline
- **history** — naps and nights grouped by day: total sleep this week, avg nap, avg wake-ups, avg time to fall asleep, avg night sleep
- **one link** — a 6-character room code; `/CODE` asks each device "which one are you" and routes nursery vs listener
- **installable** — pwa manifest + service worker; add to home screen for the app feel
- **private by architecture** — mic audio is analyzed on the nursery device and discarded; the server only ever sees a dB number. webrtc audio between nursery and watchers is peer-to-peer

## run it locally

```bash
python3 server.py
# open http://localhost:8080
```

no dependencies. python 3.9+ standard library only.

## deploy (railway)

1. push this folder to a github repo
2. railway → new project → deploy from repo (the Procfile handles the start command)
3. add a volume mounted at `/data` and set env var `STATE_FILE=/data/hush_state.json` so your room code and history survive redeploys
4. optional: point a custom domain at the service

## stack

single-file python `ThreadingHTTPServer` + server-sent events for live status + webrtc for nursery audio (signaling relayed over `/rtc`). all pages are server-rendered template strings - no build step, no framework, no javascript dependencies.
