# hush — competitive matrix (iphone baby monitor apps)

researched 2026-09-19 · sources: app store listings, vendor sites (tuck.baby, bibinoapp.com, cloudbabymonitor.com), techpp / cnet / wifibaby roundups

legend: ✅ yes · ◐ partial / roadmap · — no

## table A — monitoring and soothe

| company | live video | live audio | cry alerts | motion detect | lullabies / white noise | two-way talk | background audio (screen off) | works w/o internet | apple watch |
|---|---|---|---|---|---|---|---|---|---|
| **hush** | — (audio-first, deliberate) | ✅ | ✅ | — | ✅ (white/brown noise) | — | ◐ (pwa roadmap) | ✅ (any local wi-fi, zero internet) | ◐ (pwa push mirrors to watch - roadmap) |
| tuck | ✅ | ✅ | ✅ (AI-tuned) | ✅ (AI scenes) | ✅✅ (curated + AI) | ✅ | ✅ | ✅ (bluetooth) | — |
| annie | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| bibino | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| cloud baby monitor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (bluetooth) | ✅ (native) |
| baby monitor 3g | ✅ | ✅ | ✅ | ◐ | ✅ | ✅ | ✅ | — | — |
| nanit pro ($300 hw) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |

## table B — data, access, and business model

| company | sleep history | cry clips | self-soothe timer | multi-viewer | multi-child | no install | no account | cross-platform | pricing model | price |
|---|---|---|---|---|---|---|---|---|---|---|
| **hush** | ✅ (free, day-grouped) | — | ✅ (nobody else has it) | ✅ (just a code) | ◐ (mint codes, needs UI) | ✅ | ✅ | ✅✅ (any browser, any os) | **free** | $0 |
| tuck | ✅ (morning diary) | ◐ | — | ✅ | — | — | — (apple sign-in) | — (ios 17+ only) | subscription | $14.99/mo or $99.99/yr |
| annie | ◐ (alerts list) | ◐ | — | ✅ | ✅ | — | — | ✅ | subscription + lifetime | $6.99/wk · $12.99/mo · $64.99/yr · $149.99 lifetime |
| bibino | ✅ (activity log) | ✅ | — | ✅ | ✅ | — | — | ✅ | subscription | ~$4.99/mo |
| cloud baby monitor | ◐ | ◐ | — | ✅ | — | — | ◐ | ✅ | **one-time** | $6.99 |
| baby monitor 3g | — | — | — | ✅ | — | — | ✅ | ◐ | **one-time** | ~$5.99 |
| nanit pro | ✅ (paywalled) | ✅ | — | ✅ | ✅ | — | — | ✅ | hardware + subscription | $300 + $50-300/yr |

## what this means for hush

**our lane (nobody else is in it):** no install, no account, no subscription, any device with a browser. every competitor requires an app store download; most require accounts and subscriptions. tuck is the philosophical neighbor (reuse your iphone) but gates everything behind apple sign-in and $99.99/yr.

**already differentiated:**
- self-soothe countdown timer — nobody ships this; it maps to how parents actually sleep-train
- full sleep history free — nanit paywalls this at $50-300/yr, tuck bundles it behind subscription
- watch-from-any-browser sharing — grandparents don't install anything
- works on plain wi-fi with zero internet — tuck markets bluetooth offline hard; we have the same story free and unclaimed

**honest gaps (by design or to fix):**
- background audio (screen off) — biggest real gap; pwa + service worker is the fix
- ~~lullabies / white noise~~ — shipped: white + brown noise on the nursery device (lullaby tracks still open)
- two-way talk — table stakes for apps; needs webrtc (server can relay signaling)
- live video — deliberate skip (privacy, battery, "calm by design"), motion-detection-only is a middle path
- cry recordings — bibino has it; mediarecorder per event ties neatly into our timeline

## the "any device" play (user's idea, expanded)

vision: leave any phone in the nursery, check in from whatever is on you - phone, watch, ipad, laptop, a browser at work.

- **apple watch, realistically:** no watch browser exists, so the honest path is pwa + web push (ios 16.4+ pushes for installed web apps). a cry alert notification on the iphone mirrors to the watch automatically → "cry alert on your wrist" with zero watch app. a native watchos companion (orb + alert only) is a later cherry
- **app store as discovery, not product:** nobody knows monitor apps exist until they search "use iphone as baby monitor" - and that search happens in the app store. a thin native wrapper (wkwebview around the same server) lists hush where the searches happen while keeping the no-install promise for the core product. web wins friction, store wins discovery - do both
- **continuity-style story:** nursery phone → any signed-in-by-code device. no pairing, no bluetooth, no qr - the 6-char code IS the pairing. competitors use qr codes (tuck) or account sync (bibino); ours is a word you can text

## net-new candidates (ranked by effort vs impact)

1. **white noise / lullaby player on nursery device** — low effort, closes a checklist item every competitor has
2. **pwa install + web push cry alerts** — kills "keep tab open", puts alerts on the wrist via watch mirroring
3. **"last night" summary card on history** — tuck's sleep diary, but free; we already have the data
4. **cry clips (audio per event, replay from timeline)** — medium; mediarecorder, stored locally
5. **multi-child rooms page** — low; minted rooms already work, needs a list UI
6. **two-way talk** — big swing; webrtc with server-relayed signaling
7. **quiet-hours smart alerts** (learn typical cry times, soften at nap time) — medium; tuck's "learns your baby" but simpler
8. **thin app store wrapper for discovery** — marketing move as much as engineering

## marketing angles (the "nobody knows these exist" problem)

- **"you already own a baby monitor"** — the spare-phone hook; universal, instantly understood
- **travel wedge:** hotel rooms, grandparents' house, airbnb - the moment hardware monitors fail and nobody packs
- **contrast pages:** tuck runs 55 "vs" pages for a reason - comparison seo works; "hush vs nanit: $0 vs $300+" writes itself
- **grandparent demo:** "text them a code, they're listening in 10 seconds" - the most viral moment in the product
- **local-first privacy:** audio never leaves your house (LAN mode) - no cloud, no account, nothing to leak
- **free vs $99/yr:** annie charges $6.99 *per week*. the price contrast is the headline
