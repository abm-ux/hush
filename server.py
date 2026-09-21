#!/usr/bin/env python3
"""
Hush - local baby-monitor relay server
======================================
Pure stdlib Python (no installs). Serves an app-like site:
  /                landing   (brand, hero, features, join-by-code)
  /start           claim your room (your stable code, watch link, mint a fresh one)
  /new             mint a fresh throwaway room code
  /monitor/CODE    the NURSERY   (mic, controls, timeline, intervention timer)
  /watch/CODE      the VIEWER    (anyone with the code: live status + timeline)
  /history/CODE    sleep history (prior wakes, lengths, cry time)

API:
  POST /report?room=CODE   listener posts {level, crying}
  POST /settings?room=CODE stores {threshold, wait, minDur} and broadcasts
  POST /stop?room=CODE     closes the current session (Stop button)
  GET  /events?room=CODE   SSE stream to viewers
  GET  /history?room=CODE  JSON list of past sessions

Run:  python3 server.py   then open http://localhost:8080
"""

import json
import os
import queue
import random
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8080"))

rooms = {}
rooms_lock = threading.Lock()
DEFAULT_SETTINGS = {"threshold": -20.0, "wait": 300, "minDur": 1.0}


def new_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def get_room(code):
    with rooms_lock:
        code = code.upper()
        if code not in rooms:
            seed = list(OWNER_HISTORY) if code == OWNER else []
            rooms[code] = {
                "level": -100.0,
                "crying": False,
                "cry_start": 0.0,
                "settle_at": None,       # when the session's first cry event ended
                "events": [],            # completed events this session: {start, dur}
                "cry_time": 0.0,         # total cry seconds this session
                "settings": dict(DEFAULT_SETTINGS),
                "session_open": False,   # a monitoring session is active
                "session_start": 0.0,
                "wakeups": 0,
                "history": seed,         # completed sessions
                "subs": [],
            }
        return code, rooms[code]


def broadcast(room, payload):
    msg = json.dumps(payload)
    for sub in room["subs"]:
        try:
            sub.put_nowait(msg)
        except queue.Full:
            pass


# --- persistence: a stable "my room" so history tracks across restarts ---
STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "hush_state.json")
)
OWNER = None          # this machine's persistent room code
OWNER_HISTORY = []    # history loaded from disk for that room


def load_state():
    global OWNER, OWNER_HISTORY
    try:
        with open(STATE_FILE) as f:
            d = json.load(f)
    except Exception:
        d = {}
    OWNER = (d.get("owner") or new_code()).upper()
    OWNER_HISTORY = d.get("history", [])


def save_state():
    with rooms_lock:
        if OWNER in rooms:
            try:
                with open(STATE_FILE, "w") as f:
                    json.dump({"owner": OWNER, "history": rooms[OWNER]["history"]}, f)
            except Exception:
                pass


load_state()


def fmt_hms(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


# --------------------------------------------------------------------------
# Styles + page shell
# --------------------------------------------------------------------------
SHARED_CSS = """
  :root{--bg:#060a13;--card:#0c1424;--card2:#101a2e;--line:rgba(148,180,226,.11);
        --line2:rgba(148,180,226,.2);--text:#eaf0fa;--muted:#8d9bb6;--faint:#5f6d89;
        --teal:#45d9be;--teal-deep:#1e6b5a;--green:#4cd29a;--coral:#ec8a74;--amber:#f0b46a;
        --grad:linear-gradient(100deg,var(--amber),var(--teal));
        --serif:'Fraunces',Georgia,serif;--sans:'Inter',-apple-system,sans-serif}
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;font-family:var(--sans);color:var(--text);background:var(--bg);min-height:100vh;
       background-image:radial-gradient(900px 520px at 50% -180px,rgba(69,217,190,.09),transparent 65%)}
  ::selection{background:rgba(69,217,190,.28)}
  :focus-visible{outline:2px solid var(--teal);outline-offset:2px}
  .nav{position:sticky;top:0;z-index:50;background:rgba(6,10,19,.72);backdrop-filter:blur(14px);
       -webkit-backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
  .navin{display:flex;align-items:center;gap:6px;max-width:1120px;margin:0 auto;padding:13px 24px}
  .logo{font-family:var(--serif);font-weight:600;font-size:1.75rem;display:flex;align-items:center;gap:11px;
        color:var(--text);text-decoration:none;letter-spacing:.01em}
  .dot{width:17px;height:17px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#a9ecdc,var(--teal) 55%,var(--teal-deep));
       box-shadow:0 0 14px rgba(69,217,190,.6);animation:breathe 3.4s ease-in-out infinite}
  .nav a.nl{color:var(--muted);text-decoration:none;font-size:.9rem;font-weight:500;padding:7px 12px;border-radius:999px}
  .nav a.nl:hover{color:var(--text);background:rgba(255,255,255,.05)}
  .nav .spacer{flex:1}

  .wrap{max-width:1120px;margin:0 auto;padding:0 24px}
  .narrow{max-width:620px;margin:0 auto}
  .card{background:linear-gradient(180deg,rgba(255,255,255,.025),rgba(255,255,255,0)),var(--card);
        border:1px solid var(--line);border-radius:20px;padding:24px;margin-top:16px;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 20px 50px rgba(0,0,0,.35)}
  .card h2{margin:0 0 4px;font-size:1.06rem;font-weight:600;letter-spacing:-.01em}
  .eyebrow{display:inline-block;color:var(--teal);font-size:.7rem;font-weight:600;letter-spacing:.16em;
           text-transform:uppercase;margin-bottom:8px}
  .tag{color:var(--muted);font-size:.9rem;line-height:1.6}
  .hint{color:var(--faint);font-size:.8rem}
  .btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;
       background:linear-gradient(135deg,#5ee0ae,var(--green));color:#052a1b;font-weight:600;border:none;
       padding:13px 26px;border-radius:999px;font-size:.95rem;font-family:inherit;cursor:pointer;
       box-shadow:0 8px 24px rgba(76,210,154,.22);transition:transform .15s ease,filter .15s ease,box-shadow .15s ease}
  .btn:hover{filter:brightness(1.07);transform:translateY(-1px);box-shadow:0 12px 30px rgba(76,210,154,.3)}
  .btn:active{transform:scale(.97)}
  .btn.ghost{background:rgba(255,255,255,.04);color:var(--text);border:1px solid var(--line2);box-shadow:none}
  .btn.ghost:hover{background:rgba(255,255,255,.08)}
  .btn.stop{background:linear-gradient(135deg,#b3574d,var(--coral));color:#fff;box-shadow:0 8px 24px rgba(236,138,116,.2)}
  .btn:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}
  .code{font-weight:700;letter-spacing:.3em;color:var(--teal);font-variant-numeric:tabular-nums}
  input[type=text]{background:#0a1120;border:1px solid var(--line2);color:var(--text);padding:13px 16px;
                   border-radius:12px;font-size:1rem;text-align:center;letter-spacing:.3em;font-family:inherit;
                   width:210px;text-transform:uppercase}
  input[type=text]:focus{border-color:var(--teal);outline:none;box-shadow:0 0 0 3px rgba(69,217,190,.15)}
  input[type=range]{-webkit-appearance:none;appearance:none;height:4px;border-radius:999px;background:#1b2946;cursor:pointer}
  input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;
       background:var(--teal);border:3px solid #0c1424;box-shadow:0 0 0 1px var(--teal),0 2px 8px rgba(0,0,0,.5)}
  input[type=range]::-moz-range-thumb{width:16px;height:16px;border-radius:50%;background:var(--teal);
       border:3px solid #0c1424;box-shadow:0 0 0 1px var(--teal)}
  .grid{display:grid;gap:16px;margin-top:16px}
  .g3{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
  .g4{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}
  .g2{grid-template-columns:1fr 1fr}
  .foot{border-top:1px solid var(--line);margin-top:72px}
  .footin{display:flex;align-items:center;gap:22px;flex-wrap:wrap;padding:26px 24px;color:var(--faint);font-size:.82rem}
  .footin .logo{font-size:1.05rem}
  .flinks{display:flex;gap:16px}
  .flinks a{color:var(--muted);text-decoration:none}
  .flinks a:hover{color:var(--text)}
  .fnote{margin-left:auto}
  .seg{display:flex;gap:8px;margin-top:14px}
  .seg button{flex:1;padding:10px;border-radius:12px;border:1px solid var(--line2);background:rgba(255,255,255,.03);
       color:var(--muted);font-family:inherit;font-size:.88rem;font-weight:600;cursor:pointer;transition:all .15s ease}
  .seg button:hover{color:var(--text)}
  .seg button.on{border-color:var(--teal);color:var(--teal);background:rgba(69,217,190,.1)}
  .set{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;flex-wrap:wrap}
  .set label{color:var(--muted);font-size:.88rem;min-width:120px}
  .set input[type=range]{flex:1;min-width:120px}
  .set span{font-weight:600;color:var(--teal);min-width:74px;text-align:right;font-variant-numeric:tabular-nums}
  .caprow{display:flex;justify-content:space-between;color:var(--faint);font-size:.68rem;margin:-6px 0 4px}
  .tl::-webkit-scrollbar{width:8px}
  .tl::-webkit-scrollbar-thumb{background:#1c2946;border-radius:99px}
  @keyframes breathe{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.15);opacity:.82}}
  @media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
  body{overflow-x:hidden}
  @media (max-width:640px){
    .navin{padding:11px 16px}
    .nav a.nl{font-size:.82rem;padding:6px 7px}
    .logo{font-size:1.4rem}
    .card{padding:18px;border-radius:16px}
    .wrap{padding:0 16px}
    .footin{gap:14px}
    .fnote{margin-left:0;width:100%}
    .code-xl{font-size:1.3rem;letter-spacing:.22em}
    input[type=text]{width:100%;max-width:230px}
  }
"""


def _page(title, css="", body="", js="", narrow=False):
    return ("<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>" + title + " / hush</title>"
            "<meta name='theme-color' content='#060a13'>"
            "<meta name='apple-mobile-web-app-capable' content='yes'>"
            "<meta name='apple-mobile-web-app-title' content='hush'>"
            "<meta name='apple-mobile-web-app-status-bar-style' content='black-translucent'>"
            "<link rel='manifest' href='/manifest.json'>"
            "<link rel='icon' href='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><circle cx=%2250%22 cy=%2250%22 r=%2242%22 fill=%22%2345d9be%22/></svg>'>"
            "<link rel='preconnect' href='https://fonts.googleapis.com'>"
            "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
            "<link href='https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600;1,9..144,500&family=Inter:wght@400;500;600;700&display=swap' rel='stylesheet'>"
            "<style>" + SHARED_CSS + css + "</style></head><body>"
            "<nav class='nav'><div class='navin'>"
            "<a href='/' class='logo'><span class='dot'></span><span>hush</span></a>"
            "<span class='spacer'></span>"
            "<a class='nl' href='/setup'>set up</a><a class='nl' href='/monitor'>nursery</a><a class='nl' href='/history'>sleep log</a>"
            "</div></nav>" + body +
            "<footer class='foot'><div class='wrap footin'>"
            "<a href='/' class='logo'><span class='dot'></span><span>hush</span></a>"
            "<span class='flinks'><a href='/setup'>set up</a><a href='/monitor'>nursery</a><a href='/history'>sleep log</a><a href='/brand'>brand</a></span>"
            "<span class='fnote'>no accounts · no downloads · nothing to buy</span>"
            "</div></footer>"
            "<script>if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js');}</script>"
            "<script>" + js + "</script></body></html>")


# --------------------------------------------------------------------------
# Landing page
# --------------------------------------------------------------------------
LANDING_CSS = """
  .hero{display:grid;grid-template-columns:1.05fr .95fr;gap:48px;align-items:center;max-width:1120px;
        margin:0 auto;padding:76px 24px 48px}
  .hero h1{font-family:var(--serif);font-weight:600;font-size:clamp(2.5rem,5vw,3.7rem);line-height:1.05;
           letter-spacing:-.015em;margin:14px 0 18px}
  .hero h1 em{font-style:italic;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
  .hero .desc{color:var(--muted);font-size:1.08rem;line-height:1.65;max-width:490px;margin:0}
  .cta{display:flex;gap:12px;margin-top:30px;flex-wrap:wrap}
  .bignums{display:flex;gap:16px;justify-content:center;align-items:baseline;margin-top:14px;color:var(--muted);font-size:1rem}
  .bignums b{font-family:var(--serif);font-size:2.4rem;font-weight:600;color:var(--teal)}
  .bignums i{color:var(--faint);font-style:normal}
  .stage{position:relative;display:flex;justify-content:center;padding:20px 0}
  .halo{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:460px;height:460px;border-radius:50%;
        background:radial-gradient(closest-side,rgba(69,217,190,.14),transparent 70%);pointer-events:none}
  .phone{position:relative;width:264px;height:520px;border-radius:44px;background:linear-gradient(180deg,#0e1626,#080d18);
         border:1px solid var(--line2);box-shadow:0 40px 80px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.06);padding:14px}
  .phone .notch{position:absolute;top:12px;left:50%;transform:translateX(-50%);width:96px;height:22px;border-radius:999px;background:#04070d;z-index:2}
  .scr{height:100%;border-radius:32px;background:radial-gradient(240px 200px at 50% 0%,rgba(69,217,190,.08),transparent 70%),#070c16;
       display:flex;flex-direction:column;align-items:center;justify-content:center;gap:15px;padding:20px}
  .mini-pill{display:inline-flex;align-items:center;gap:7px;font-size:.68rem;font-weight:600;letter-spacing:.08em;
             color:var(--green);border:1px solid rgba(76,210,154,.35);border-radius:999px;padding:5px 12px;background:rgba(76,210,154,.08)}
  .mini-pill i{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:breathe 2.4s infinite}
  .mini-orb{width:86px;height:86px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#d7f6e8,#6ee7a0 55%,#1e5c3a);
            box-shadow:0 0 34px rgba(110,231,160,.35);animation:breathe 3.4s ease-in-out infinite}
  .mini-code{font-weight:700;letter-spacing:.32em;color:var(--teal);font-size:.95rem}
  .mini-meter{display:flex;align-items:flex-end;gap:4px;height:34px}
  .mini-meter b{width:5px;border-radius:3px;background:linear-gradient(180deg,var(--teal),var(--teal-deep));animation:eq 1.3s ease-in-out infinite}
  .mini-meter b:nth-child(1){height:12px}.mini-meter b:nth-child(2){height:22px;animation-delay:.15s}
  .mini-meter b:nth-child(3){height:16px;animation-delay:.3s}.mini-meter b:nth-child(4){height:28px;animation-delay:.45s}
  .mini-meter b:nth-child(5){height:18px;animation-delay:.6s}.mini-meter b:nth-child(6){height:24px;animation-delay:.75s}
  .mini-meter b:nth-child(7){height:14px;animation-delay:.9s}
  @keyframes eq{0%,100%{transform:scaleY(.5)}50%{transform:scaleY(1)}}
  .mini-state{color:var(--faint);font-size:.72rem}
  .chip{position:absolute;background:rgba(12,20,36,.92);border:1px solid var(--line2);border-radius:14px;padding:10px 14px;
        box-shadow:0 16px 40px rgba(0,0,0,.4);backdrop-filter:blur(6px)}
  .chip b{display:block;font-size:.95rem;letter-spacing:-.01em}
  .chip span{color:var(--faint);font-size:.7rem}
  .c1{top:18%;left:-2%;animation:float 7s ease-in-out infinite}
  .c2{bottom:16%;right:-2%;animation:float 8s ease-in-out infinite reverse}
  @keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
  .sec{max-width:1120px;margin:0 auto;padding:44px 24px}
  .sec-h{max-width:560px;margin:0 auto 36px;text-align:center}
  .sec-h h2{font-family:var(--serif);font-weight:600;font-size:clamp(1.7rem,3vw,2.3rem);letter-spacing:-.01em;margin:10px 0}
  .sec-h p{color:var(--muted);margin:0;line-height:1.6}
  .steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}
  .step{background:linear-gradient(180deg,rgba(255,255,255,.025),transparent),var(--card);border:1px solid var(--line);
        border-radius:20px;padding:26px;transition:transform .18s ease,border-color .18s ease}
  .step:hover{transform:translateY(-4px);border-color:var(--line2)}
  .step h3{margin:2px 0 8px;font-size:1.05rem;font-weight:600}
  .step p{margin:0;color:var(--muted);font-size:.9rem;line-height:1.6}
  .join{position:relative;overflow:hidden;text-align:center;padding:46px 28px;max-width:560px;margin:0 auto}
  .join:before{content:'';position:absolute;inset:0;background:radial-gradient(420px 200px at 50% -60px,rgba(69,217,190,.12),transparent 70%);pointer-events:none}
  .join h2{font-family:var(--serif);font-weight:600;font-size:1.8rem;margin:0 0 8px;letter-spacing:-.01em}
  .joinrow{display:flex;gap:10px;justify-content:center;margin-top:22px;flex-wrap:wrap}
  .rise{opacity:0;transform:translateY(14px);transition:opacity .6s ease,transform .6s ease}
  .rise.in{opacity:1;transform:none}
  @media (prefers-reduced-motion:reduce){.rise{opacity:1;transform:none}}
  @media (max-width:900px){.hero{grid-template-columns:1fr;padding-top:56px}.c1{left:0}.c2{right:0}}
  @media (max-width:640px){
    .hero{padding:44px 16px 28px;gap:30px}
    .stage{transform:scale(.84);transform-origin:top center;margin-bottom:-60px}
    .sec{padding:32px 16px}
    .bignums{gap:10px;font-size:.9rem;flex-wrap:wrap}
    .bignums b{font-size:1.8rem}
    .chip{padding:8px 10px}
  }
"""


def landing_page():
    body = """
  <section class='hero'>
    <div>
      <h1>the baby monitor <em>you already own</em></h1>
      <p class='desc'>hush listens for cries, times every nap, and lets anyone check in live from any browser - no app to install, no account, nothing to buy</p>
      <div class='cta'>
        <a class='btn' href='/setup'>set up now</a>
        <a class='btn ghost' href='#join'>already have a code? listen now</a>
      </div>
    </div>
    <div class='stage'>
      <div class='halo'></div>
      <div class='phone'><div class='notch'></div>
        <div class='scr'>
          <span class='mini-pill'><i></i>live</span>
          <div class='mini-orb'></div>
          <div class='mini-code'>2dl716</div>
          <div class='mini-meter'><b></b><b></b><b></b><b></b><b></b><b></b><b></b></div>
          <span class='mini-state'>quiet - listening</span>
        </div>
      </div>
      <div class='chip c1'><b>1h 28m</b><span>afternoon nap</span></div>
      <div class='chip c2'><b>2:14</b><span>self-soothe left</span></div>
    </div>
  </section>

  <section class='sec'>
    <div class='sec-h rise'>
      <h2>a nursery in two minutes</h2>
      <p class='bignums'><b>2</b> phones<i>·</i><b>1</b> unique code<i>·</i><b>0</b> purchases</p>
    </div>
    <div class='steps'>
      <div class='step rise'><h3>claim your code</h3><p>one link is the whole system - generate it once and it stays yours</p></div>
      <div class='step rise'><h3>put hush on your home screen</h3><p>save your link to the home screen and it opens like an app - full screen, one tap away</p></div>
      <div class='step rise'><h3>leave your phone</h3><p>the spare phone stays by the crib and keeps listening - walk away, and text the link to anyone who should hear it</p></div>
    </div>
  </section>

  <section class='sec' id='join'>
    <div class='card join rise'>
      <span class='eyebrow'>listen live</span>
      <h2>have a code?</h2>
      <p class='tag'>enter a room code to listen from any device - no app, no account</p>
      <div class='joinrow'>
        <input type='text' id='joincode' maxlength='6' placeholder='2dl716' autocomplete='off'>
        <a class='btn' href='#' id='go'>listen</a>
      </div>
      <p class='hint' style='margin-top:14px'>ask whoever's monitoring for the 6-character code</p>
    </div>
  </section>
"""
    js = """
function go(){var v=document.getElementById('joincode').value.trim().toUpperCase();if(v)location.href='watch/'+v;}
document.getElementById('go').addEventListener('click',function(e){e.preventDefault();go();});
document.getElementById('joincode').addEventListener('keydown',function(e){if(e.key==='Enter')go();});
if('IntersectionObserver' in window){
  var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});},{threshold:.12});
  document.querySelectorAll('.rise').forEach(function(el){io.observe(el);});
}else{document.querySelectorAll('.rise').forEach(function(el){el.classList.add('in');});}
"""
    return _page("home", LANDING_CSS, body, js)


# --------------------------------------------------------------------------
# PWA plumbing - manifest, icon, service worker (push lands in a later pass)
# --------------------------------------------------------------------------
MANIFEST = {
    "name": "hush",
    "short_name": "hush",
    "description": "turn a spare phone into a baby monitor",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#060a13",
    "theme_color": "#060a13",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
}

ICON_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'>"
            "<rect width='512' height='512' rx='110' fill='#060a13'/>"
            "<defs><radialGradient id='g' cx='35%' cy='30%'>"
            "<stop offset='0' stop-color='#a9ecdc'/><stop offset='.55' stop-color='#45d9be'/>"
            "<stop offset='1' stop-color='#1e6b5a'/></radialGradient></defs>"
            "<circle cx='256' cy='256' r='150' fill='url(#g)'/></svg>")

SW_JS = """
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('push',e=>{
  let d={};try{d=e.data?e.data.json():{};}catch(err){}
  e.waitUntil(self.registration.showNotification(d.title||'hush',{
    body:d.body||'crying in the nursery',icon:'/icon.svg',badge:'/icon.svg'}));
});
self.addEventListener('notificationclick',e=>{
  e.notification.close();
  e.waitUntil(self.clients.openWindow((e.notification.data&&e.notification.data.url)||'/'));
});
"""


# --------------------------------------------------------------------------
# Setup - guided onboarding with animated walkthroughs
# --------------------------------------------------------------------------
SETUP_CSS = """
  .sethead{max-width:640px;margin:46px auto 10px;text-align:center}
  .sethead h1{font-family:var(--serif);font-weight:600;font-size:clamp(2rem,4vw,2.8rem);letter-spacing:-.01em;margin:6px 0 10px}
  .scard{display:grid;grid-template-columns:300px 1fr;gap:28px;align-items:center;
        background:linear-gradient(180deg,rgba(255,255,255,.025),transparent),var(--card);
        border:1px solid var(--line);border-radius:20px;padding:26px;margin-top:22px;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 20px 50px rgba(0,0,0,.35)}
  .scard h2{font-family:var(--serif);font-weight:600;font-size:1.5rem;margin:2px 0 8px;letter-spacing:-.01em}
  .scard p{color:var(--muted);font-size:.92rem;line-height:1.6;margin:0}
  .scont .eyebrow{margin-bottom:2px}
  .vis{position:relative;height:200px;display:flex;align-items:center;justify-content:center;overflow:hidden;
       background:#0a1120;border:1px solid var(--line);border-radius:16px}
  .bigcode{font-size:2.2rem;font-weight:700;letter-spacing:.3em;color:var(--teal);font-variant-numeric:tabular-nums;text-indent:.3em}
  .srow{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}
  .btn.sm{padding:10px 16px;font-size:.85rem}
  .after{opacity:0;transform:translateY(8px);transition:opacity .4s ease,transform .4s ease;pointer-events:none}
  .after.show{opacity:1;transform:none;pointer-events:auto}
  .after a{color:var(--teal);text-decoration:none;font-weight:600}
  .hidden{display:none}
  .how{counter-reset:s;list-style:none;padding:0;margin:16px 0 0;text-align:left}
  .how li{position:relative;padding:10px 0 10px 44px;color:var(--muted);font-size:.9rem;border-bottom:1px solid var(--line);line-height:1.5}
  .how li:last-child{border-bottom:none}
  .how li:before{counter-increment:s;content:counter(s);position:absolute;left:0;top:8px;width:26px;height:26px;border-radius:50%;
       background:rgba(69,217,190,.1);border:1px solid rgba(69,217,190,.25);color:var(--teal);font-size:.78rem;font-weight:700;
       display:flex;align-items:center;justify-content:center}
  /* step 2: listening rings */
  .mphone{width:46px;height:86px;border:2px solid var(--line2);border-radius:12px;background:#070c16;position:relative;z-index:1}
  .ring{position:absolute;left:50%;top:50%;width:26px;height:26px;border:1px solid var(--teal);border-radius:50%;
        transform:translate(-50%,-50%) scale(.6);opacity:0;animation:ping 2.6s ease-out infinite}
  .r2{animation-delay:.85s}.r3{animation-delay:1.7s}
  @keyframes ping{0%{transform:translate(-50%,-50%) scale(.6);opacity:.9}100%{transform:translate(-50%,-50%) scale(6);opacity:0}}
  /* step 3: add-to-home-screen animation */
  .iphone{position:relative;width:130px;height:190px;border:2px solid var(--line2);border-radius:24px;background:#070c16}
  .sicon{position:absolute;bottom:16px;left:50%;transform:translateX(-50%);width:24px;height:24px;border:2px solid var(--teal);border-radius:7px}
  .sicon:before{content:'';position:absolute;left:50%;top:5px;width:2px;height:11px;background:var(--teal);transform:translateX(-50%)}
  .sicon:after{content:'';position:absolute;left:50%;top:2px;width:7px;height:7px;border-top:2px solid var(--teal);border-left:2px solid var(--teal);transform:translateX(-50%) rotate(45deg)}
  .sheet{position:absolute;left:8px;right:8px;bottom:8px;height:56px;background:var(--card2);border:1px solid var(--line2);border-radius:14px;
         display:flex;align-items:center;gap:8px;padding:0 10px;font-size:.62rem;color:var(--muted);
         animation:sheetup 5s ease-in-out infinite;transform:translateY(90px);opacity:0}
  .odot{width:16px;height:16px;border-radius:5px;flex-shrink:0;background:radial-gradient(circle at 35% 30%,#a9ecdc,var(--teal) 55%,var(--teal-deep))}
  @keyframes sheetup{10%,70%{transform:translateY(0);opacity:1}0%,90%,100%{transform:translateY(90px);opacity:0}}
  .appicon{position:absolute;top:14px;right:14px;width:22px;height:22px;border-radius:7px;
           background:radial-gradient(circle at 35% 30%,#a9ecdc,var(--teal) 55%,var(--teal-deep));
           box-shadow:0 0 10px rgba(69,217,190,.5);animation:pop 5s ease-in-out infinite;transform:scale(0)}
  @keyframes pop{0%,45%{transform:scale(0)}55%,92%{transform:scale(1)}100%{transform:scale(0)}}
  .donecard{text-align:center;margin-top:36px}
  .donecard h2{font-family:var(--serif);font-weight:600;font-size:1.6rem;margin:0 0 16px}
  @media (max-width:760px){.scard{grid-template-columns:1fr}.vis{height:170px}}
"""


def setup_page(code):
    body = """
  <div class='wrap'>
    <div class='sethead'>
      <span class='eyebrow'>setup</span>
      <h1>set up your nursery</h1>
      <p class='tag'>three steps, zero purchases</p>
      <p class='hint' style='margin-top:10px'>iphone · android · ipad · mac · pc - if it has a browser, it's in</p>
    </div>

    <div class='scard'>
      <div class='vis'><span class='bigcode' id='code'>••••••</span></div>
      <div class='scont'>
        <span class='eyebrow'>step 1</span>
        <h2>claim your code</h2>
        <p>one link is the whole system - the nursery uses it, listeners use it, no account needed</p>
        <div class='srow'><button class='btn' id='gen'>generate my code</button></div>
        <div class='after' id='after'>
          <div class='srow'><button class='btn ghost sm' id='cplink'>copy link</button></div>
          <p class='hint'>setting up a second room? <a href='/new'>mint a fresh code</a></p>
        </div>
      </div>
    </div>

    <div class='scard'>
      <div class='vis'>
        <div class='iphone'>
          <span class='appicon'></span>
          <span class='sicon'></span>
          <div class='sheet'><span class='odot'></span><span>add to home screen</span></div>
        </div>
      </div>
      <div class='scont'>
        <span class='eyebrow'>step 2</span>
        <h2>put hush on your home screen</h2>
        <p>open your link on your own phone first, then save it - full screen, one tap away, ready for alerts</p>
        <div class='seg' style='max-width:260px'>
          <button id='tabios' class='on'>iphone</button>
          <button id='taband'>android</button>
        </div>
        <ol class='how' id='howios'>
          <li>open your link in safari</li>
          <li>tap the share icon - the square with an arrow</li>
          <li>scroll down and tap "add to home screen"</li>
          <li>tap add - hush now opens like an app</li>
        </ol>
        <ol class='how hidden' id='howand'>
          <li>open your link in chrome</li>
          <li>tap the three-dot menu, top right</li>
          <li>tap "add to home screen" or "install app"</li>
          <li>tap add - hush now opens like an app</li>
        </ol>
      </div>
    </div>

    <div class='scard'>
      <div class='vis'>
        <div class='ring r1'></div><div class='ring r2'></div><div class='ring r3'></div>
        <div class='mphone'></div>
      </div>
      <div class='scont'>
        <span class='eyebrow'>step 3</span>
        <h2>leave your phone</h2>
        <ol class='how'>
          <li>on the spare phone, open your link and tap "this phone stays with the baby"</li>
          <li>tap start, allow the mic, plug it in, and angle it at the crib</li>
          <li>text your link to anyone who should listen - it opens in any browser</li>
        </ol>
      </div>
    </div>

    <div class='donecard'>
      <h2>all set?</h2>
      <a class='btn' href='/monitor/__CODE__'>open the nursery</a>
    </div>
  </div>
"""
    js = """
const CODE='__CODE__';
const $=id=>document.getElementById(id);
function cp(u,b,label){const done=()=>{b.textContent='copied';setTimeout(()=>b.textContent=label,1600);};
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(u).then(done,done);}
  else{const t=document.createElement('textarea');t.value=u;document.body.appendChild(t);t.select();try{document.execCommand('copy');}catch(e){}t.remove();done();}}
$('gen').addEventListener('click',()=>{
  $('gen').disabled=true;$('gen').textContent='generating';
  const chars='ABCDEFGHJKMNPQRSTUVWXYZ23456789';let i=0;const el=$('code');
  const iv=setInterval(()=>{i++;
    el.textContent=CODE.split('').map((c,idx)=>idx<i?c:chars[Math.floor(Math.random()*chars.length)]).join('');
    if(i>=CODE.length){clearInterval(iv);el.textContent=CODE;$('gen').textContent='your code';$('after').classList.add('show');}
  },110);
});
$('cplink').addEventListener('click',()=>cp(location.origin+'/'+CODE,$('cplink'),'copy link'));
$('tabios').addEventListener('click',()=>{$('tabios').classList.add('on');$('taband').classList.remove('on');$('howios').classList.remove('hidden');$('howand').classList.add('hidden');});
$('taband').addEventListener('click',()=>{$('taband').classList.add('on');$('tabios').classList.remove('on');$('howand').classList.remove('hidden');$('howios').classList.add('hidden');});
"""
    return _page("setup", SETUP_CSS, body, js).replace("__CODE__", code)


# --------------------------------------------------------------------------
# Monitor (nursery) page
# --------------------------------------------------------------------------
MONITOR_CSS = """
  .stage-top{text-align:center;padding-top:38px}
  .orb{width:150px;height:150px;margin:16px auto 8px;border-radius:50%;
       background:radial-gradient(circle at 35% 30%,#d7f6e8,#6ee7a0 55%,#1e5c3a);
       box-shadow:0 0 44px rgba(110,231,160,.32);transition:all .4s ease}
  button.orb{display:flex;flex-direction:column;align-items:center;justify-content:center;color:#063a2a;font-weight:700;font-size:1.2rem;
       font-family:inherit;border:none;cursor:pointer;letter-spacing:.04em}
  .orbsub{display:block;font-size:.6rem;font-weight:600;opacity:.75;letter-spacing:.1em;margin-top:2px}
  .orb.alert{background:radial-gradient(circle at 35% 30%,#ffd6c8,var(--coral) 55%,#8f3b2a);box-shadow:0 0 54px rgba(236,138,116,.7)}
  .orb.off{background:radial-gradient(circle at 35% 30%,#bfe8d8,var(--green) 55%,#1f5c44);box-shadow:0 0 26px rgba(76,210,154,.25);opacity:.55;animation:breathe 3.4s ease-in-out infinite}
  .pill{display:inline-flex;align-items:center;gap:8px;padding:7px 15px;border-radius:999px;border:1px solid var(--line2);
        background:rgba(255,255,255,.03);font-size:.85rem;font-weight:600;margin:8px 0 2px}
  .pill:before{content:'';width:8px;height:8px;border-radius:50%;background:var(--faint)}
  .pill.live:before{background:var(--green);box-shadow:0 0 10px var(--green);animation:breathe 2.6s infinite}
  .pill.alert{color:var(--coral);border-color:rgba(236,138,116,.4)}
  .pill.alert:before{background:var(--coral);box-shadow:0 0 10px var(--coral)}
  #levelText{color:var(--muted);font-size:.85rem;margin:4px 0 0;font-variant-numeric:tabular-nums}
  .code-xl{font-size:1.6rem;font-weight:700;letter-spacing:.28em;color:var(--teal);font-variant-numeric:tabular-nums}
  .roombox{display:flex;gap:10px;align-items:center;background:#0a1120;border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-top:14px}
  .roombox span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
"""


def monitor_page(code):
    body = """
  <div class='wrap narrow'>
    <div class='stage-top'>
      <span class='eyebrow' style='margin:0'>nursery</span>
      <div class='code-xl' style='margin-top:8px'>__CODE__</div>
      <button class='orb off' id='orb' aria-label='start listening'>start<span class='orbsub'>to listen</span></button>
      <div><button class='btn stop' id='stopBtn' disabled style='margin-top:12px;padding:9px 22px;font-size:.85rem'>stop</button></div>
      <div><span class='pill' id='stateText' style='display:none'></span></div>
      <p id='levelText'>- dB</p>
      <div class='roombox' style='justify-content:center'>
        <button class='btn ghost' id='share' style='margin:0;padding:9px 14px;font-size:.82rem'>copy link to share & listen</button>
      </div>
    </div>

    <div class='card'>
      <span class='eyebrow'>tuning</span>
      <h2>sensitivity</h2>
      <p class='hint' style='margin:2px 0 4px'>tip: tap start, watch the live dB number while the room is quiet, then set the threshold a little above it</p>
      <div class='set'><label>volume threshold</label><input type='range' id='thr' min='-50' max='0' step='1' value='-20'><span id='thrL'>-20 dB</span></div>
      <div class='caprow'><span>hears whispers</span><span>only loud cries</span></div>
      <div class='set'><label>min cry length</label><input type='range' id='mind' min='0.3' max='3' step='0.1' value='1'><span id='mindL'>1.0 s</span></div>
      <div class='caprow'><span>any noise counts</span><span>only sustained cries</span></div>
    </div>

    <div class='card'>
      <span class='eyebrow'>soothe</span>
      <h2>self-soothe window</h2>
      <p class='hint' style='margin:2px 0 0'>how long a cry runs before hush says go in - watchers see the countdown live</p>
      <div class='set' style='margin-top:10px'><label>window length</label><input type='range' id='wait' min='30' max='600' step='15' value='300'><span id='waitL'>5:00</span></div>
      <div style='height:1px;background:var(--line);margin:18px 0'></div>
      <h2>white noise</h2>
      <p class='hint' style='margin:2px 0 0'>a soft hush into the nursery - keeps playing while it listens</p>
      <div class='seg'>
        <button id='nwhite'>white</button>
        <button id='nbrown'>brown</button>
        <button id='noff' class='on'>off</button>
      </div>
      <div class='set' style='margin-top:8px'><label>volume</label><input type='range' id='nvol' min='0' max='1' step='0.05' value='0.5'><span id='nvolL'>50%</span></div>
    </div>

    <p class='hint' style='text-align:center;margin:14px 0 0'>the mic listens while this page is open</p>
  </div>
"""
    js = """
const CODE='__CODE__';
const $=id=>document.getElementById(id);
const orb=$('orb'),stateText=$('stateText'),levelText=$('levelText');
const el={active:null,wait:300,started:false,stream:null};
let analyser=null;

function db(){if(!analyser)return -100;const b=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(b);
  let s=0;for(let i=0;i<b.length;i++)s+=b[i]*b[i];const r=Math.sqrt(s/b.length);if(r<0.00001)return -100;return 20*Math.log10(r);}
function fmt(s){s=Math.max(0,Math.round(s||0));const m=Math.floor(s/60),ss=s%60;return m+':'+String(ss).padStart(2,'0');}
function postSettings(){
  fetch('/settings?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({threshold:+$('thr').value,minDur:+$('mind').value,wait:+$('wait').value})});
}
['thr','mind','wait'].forEach(id=>$(id).addEventListener('input',()=>{
  if(id==='thr')$('thrL').textContent=$('thr').value+' dB';
  if(id==='mind')$('mindL').textContent=(+$('mind').value).toFixed(1)+' s';
  if(id==='wait')$('waitL').textContent=fmt($('wait').value);
  if(el.started)postSettings();
}));

async function start(){
  el.stream=await navigator.mediaDevices.getUserMedia({audio:true});
  const ctx=new AudioContext();analyser=ctx.createAnalyser();analyser.fftSize=2048;
  ctx.createMediaStreamSource(el.stream).connect(analyser);
  nctx=nctx||new (window.AudioContext||window.webkitAudioContext)();if(nctx.state==='suspended')nctx.resume();
  el.started=true;el.wait=+$('wait').value;
  $('stopBtn').disabled=false;orb.classList.remove('off');orb.textContent='';
  stateText.style.display='inline-flex';stateText.textContent='listening';stateText.className='pill live';postSettings();
  fetch('/rtc?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hello:true,from:'nursery',to:'all'})});
  setInterval(async()=>{
    const lv=db();levelText.textContent=lv.toFixed(0)+' dB';
    const th=+$('thr').value;const crying=lv>th;
    orb.classList.toggle('alert',crying);
    if(crying&&!el.active){el.active={start:Date.now()};stateText.textContent='alert - loud noise';stateText.className='pill alert';}
    if(!crying&&el.active){el.active=null;stateText.textContent='quiet';stateText.className='pill live';}
    try{await fetch('/report?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({level:lv,crying})});}catch(e){}
  },250);
}
async function stop(){
  if(!el.started)return;
  if(el.stream)el.stream.getTracks().forEach(t=>t.stop());el.stream=null;
  el.started=false;el.active=null;
  $('stopBtn').disabled=true;orb.classList.add('off');
  orb.innerHTML='start<span class=\\'orbsub\\'>to listen</span>';
  stateText.textContent='stopped';stateText.className='pill';
  Object.keys(pcs).forEach(k=>{try{pcs[k].close();}catch(e){}delete pcs[k];});
  await fetch('/stop?room='+CODE,{method:'POST'});
}
$('stopBtn').addEventListener('click',stop);
$('orb').addEventListener('click',()=>{if(!el.started)start();});
// soothe noise: white or brown, generated on-device with web audio
let nctx=null,nsrc=null,ngain=null;
function mknoise(type){const len=2*nctx.sampleRate;const buf=nctx.createBuffer(1,len,nctx.sampleRate);const d=buf.getChannelData(0);
  if(type==='brown'){let last=0;for(let i=0;i<len;i++){const w=Math.random()*2-1;last=(last+0.02*w)/1.02;d[i]=last*3.5;}}
  else{for(let i=0;i<len;i++)d[i]=Math.random()*2-1;}
  return buf;}
function setNoise(type,bcast){
  if(nsrc){try{nsrc.stop();}catch(e){}nsrc=null;}
  ['nwhite','nbrown','noff'].forEach(id=>$(id).classList.remove('on'));
  if(!type){$('noff').classList.add('on');}
  else{
    nctx=nctx||new (window.AudioContext||window.webkitAudioContext)();
    if(nctx.state==='suspended')nctx.resume();
    nsrc=nctx.createBufferSource();nsrc.buffer=mknoise(type);nsrc.loop=true;
    ngain=nctx.createGain();ngain.gain.value=+$('nvol').value;
    nsrc.connect(ngain);ngain.connect(nctx.destination);nsrc.start();
    $(type==='white'?'nwhite':'nbrown').classList.add('on');
  }
  if(bcast!==false)fetch('/rtc?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from:'nursery',noise:type||'off',vol:+$('nvol').value})});
}
$('nwhite').addEventListener('click',()=>setNoise('white'));
$('nbrown').addEventListener('click',()=>setNoise('brown'));
$('noff').addEventListener('click',()=>setNoise(null));
$('nvol').addEventListener('input',()=>{const v=+$('nvol').value;$('nvolL').textContent=Math.round(v*100)+'%';if(ngain)ngain.gain.value=v;});
// webrtc uplink: stream the mic to any watcher who turns sound on
const pcs={};
const rtcES=new EventSource('/events?room='+CODE);
rtcES.onmessage=async e=>{const d=JSON.parse(e.data);
  if(d.type!=='rtc')return;
  if(d.cmd==='noise'&&d.from!=='nursery'){
    if(d.vol!=null){$('nvol').value=d.vol;$('nvolL').textContent=Math.round(d.vol*100)+'%';if(ngain)ngain.gain.value=d.vol;}
    setNoise(d.mode==='off'?null:d.mode,false);return;}
  if(d.hello||!el.started)return;
  if(d.to!=='nursery')return;
  const wid2=d.from;
  try{
    if(d.offer){
      if(pcs[wid2]){try{pcs[wid2].close();}catch(err){}}
      const pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
      pcs[wid2]=pc;
      el.stream.getTracks().forEach(t=>pc.addTrack(t,el.stream));
      pc.onicecandidate=c=>{if(c.candidate)fetch('/rtc?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to:wid2,from:'nursery',candidate:c.candidate})});};
      pc.onconnectionstatechange=()=>{if(['disconnected','failed','closed'].indexOf(pc.connectionState)>=0)delete pcs[wid2];};
      await pc.setRemoteDescription(d.offer);
      await pc.setLocalDescription(await pc.createAnswer());
      fetch('/rtc?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to:wid2,from:'nursery',answer:pc.localDescription})});
    }else if(d.candidate&&pcs[wid2]){pcs[wid2].addIceCandidate(d.candidate).catch(()=>{});}
  }catch(err){}
};
$('share').addEventListener('click',()=>{const u=location.origin+'/'+CODE;const b=$('share');
  const ok=()=>{b.textContent='copied';setTimeout(()=>b.textContent='copy link to share & listen',1600);};
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(u).then(ok,ok);}
  else{const t=document.createElement('textarea');t.value=u;document.body.appendChild(t);t.select();try{document.execCommand('copy');}catch(e){}t.remove();ok();}});
"""
    return _page("nursery", MONITOR_CSS, body, js).replace("__CODE__", code)


# --------------------------------------------------------------------------
# Watch (viewer) page
# --------------------------------------------------------------------------
WATCH_CSS = """
  .stage-top{text-align:center;padding-top:38px}
  .orb{display:block;width:120px;height:120px;margin:16px auto 8px;border-radius:50%;
       background:radial-gradient(circle at 35% 30%,#d7f6e8,#6ee7a0 55%,#1e5c3a);
       box-shadow:0 0 30px rgba(110,231,160,.3);transition:all .4s ease}
  .orb.alert{background:radial-gradient(circle at 35% 30%,#ffd6c8,var(--coral) 55%,#8f3b2a);box-shadow:0 0 48px rgba(236,138,116,.75);animation:blink .9s infinite}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.35}}
  .pill{display:inline-flex;align-items:center;gap:8px;padding:7px 15px;border-radius:999px;border:1px solid var(--line2);
        background:rgba(255,255,255,.03);font-size:.85rem;font-weight:600;margin:8px 0 2px}
  .pill:before{content:'';width:8px;height:8px;border-radius:50%;background:var(--faint)}
  .pill.live:before{background:var(--green);box-shadow:0 0 10px var(--green);animation:breathe 2.6s infinite}
  .pill.alert{color:var(--coral);border-color:rgba(236,138,116,.4)}
  .pill.alert:before{background:var(--coral);box-shadow:0 0 10px var(--coral)}
  #levelText{color:var(--muted);font-size:.85rem;margin:4px 0 0;font-variant-numeric:tabular-nums}
  .code-xl{font-size:1.6rem;font-weight:700;letter-spacing:.28em;color:var(--teal);font-variant-numeric:tabular-nums}
  .bar{position:relative;height:12px;background:#0a1120;border-radius:999px;overflow:visible;margin:16px 0 4px;border:1px solid var(--line)}
  .bar i{display:block;height:100%;width:0%;background:linear-gradient(90deg,#22c55e,#eab308,#f87171);border-radius:999px;transition:width 120ms linear;overflow:hidden}
  .tick{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--teal);opacity:.9;border-radius:1px;pointer-events:none}
  .metercap{display:flex;justify-content:space-between;color:var(--faint);font-size:.7rem}
  .sleeptime{color:var(--teal);font-size:.88rem;margin:8px 0 0}
  .sleeptime span{font-family:var(--serif);font-size:1.3rem;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:.01em}
  .waittrack{height:10px;background:#0a1120;border-radius:999px;overflow:hidden;border:1px solid var(--line);margin-top:10px}
  .waittrack i{display:block;height:100%;width:0%;background:var(--teal);border-radius:999px;transition:width 300ms linear}
  #waitText{color:var(--muted);font-size:.9rem;min-height:1.3em;margin-top:12px}
  #waitText.now{color:var(--coral);font-weight:700}
  .tl{list-style:none;padding:0;margin:12px 0 0;max-height:180px;overflow-y:auto;text-align:left}
  .tl li{padding:9px 0;border-bottom:1px solid var(--line);font-size:.88rem;display:flex;justify-content:space-between}
  .tl li:last-child{border:none}
  .dim{color:var(--faint);font-style:italic}
"""


def watch_page(code):
    body = """
  <div class='wrap narrow'>
    <div class='stage-top'>
      <span class='eyebrow' style='margin:0'>watching</span>
      <div class='code-xl' style='margin-top:8px'>__CODE__</div>
      <div class='orb' id='orb'></div>
      <div><span class='pill' id='stateText'>connecting</span></div>
      <p id='levelText'> -  dB</p>
      <p id='sleepText' class='sleeptime' hidden>asleep for <span id='sleepFor'></span></p>
    </div>
    <div class='bar'><i id='bar'></i><span class='tick' id='thrtick'></span></div>
    <div class='metercap'><span>quiet</span><span>loud</span></div>
    <div style='text-align:center;margin-top:14px'>
      <button class='btn ghost' id='sndBtn'>turn sound on</button>
      <p class='hint' id='sndHint' style='margin-top:8px'>hear the nursery live - mute anytime, the orb keeps watching</p>
    </div>

    <div class='card'>
      <span class='eyebrow'>soothe</span>
      <h2>white noise</h2>
      <p class='hint' style='margin:2px 0 0'>plays from the nursery phone - you control it from here</p>
      <div class='seg'>
        <button id='nwhite'>white</button>
        <button id='nbrown'>brown</button>
        <button id='noff' class='on'>off</button>
      </div>
      <div class='set' style='margin-top:8px'><label>volume</label><input type='range' id='nvol' min='0' max='1' step='0.05' value='0.5'><span id='nvolL'>50%</span></div>
    </div>

    <div class='card'>
      <span class='eyebrow'>timer</span>
      <h2>self-soothe window</h2>
      <div id='waitText'>connecting</div>
      <div class='waittrack'><i id='waitfill'></i></div>
    </div>

    <div class='card'>
      <div style='display:flex;justify-content:space-between;align-items:baseline'>
        <div><span class='eyebrow'>this session</span><h2>timeline</h2></div>
        <span id='badge' class='hint'>0 cries</span>
      </div>
      <ul class='tl' id='tl'><li class='dim'>waiting for activity</li></ul>
    </div>
    <p class='hint' style='text-align:center;margin:14px 0 0'>keep this page open to listen live - no app, no download</p>
  </div>
"""
    js = """
const CODE='__CODE__';
const $=id=>document.getElementById(id);
const orb=$('orb'),stateText=$('stateText'),levelText=$('levelText'),bar=$('bar'),
      tl=$('tl'),badge=$('badge'),waitText=$('waitText'),waitfill=$('waitfill');
const el={events:[],active:null,wait:300};
function fmt(s){s=Math.max(0,Math.round(s||0));const m=Math.floor(s/60),ss=s%60;return m+':'+String(ss).padStart(2,'0');}
let quietSince=null,clockOff=0;
function fmtDur(s){s=Math.max(0,Math.round(s));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),ss=s%60;
  if(h)return h+'h '+String(m).padStart(2,'0')+'m';
  if(m)return m+'m '+String(ss).padStart(2,'0')+'s';
  return ss+'s';}
function tickSleep(){const st=$('sleepText');if(!quietSince){st.hidden=true;return;}
  st.hidden=false;$('sleepFor').textContent=fmtDur(Date.now()/1000+clockOff-quietSince);}
setInterval(tickSleep,1000);
function setTick(v){const p=Math.max(0,Math.min(100,((v+60)/60)*100));$('thrtick').style.left='calc('+p+'% - 1px)';}
function fmtClock(s){return new Date(s*1000).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'}).toLowerCase();}
function fmtGap(s){const m=Math.round(s/60);if(m<1)return 'moments';if(m<60)return m+'m';return Math.floor(m/60)+'h '+(m%60)+'m';}
function renderTimeline(){tl.innerHTML='';
  if(!el.events.length){tl.innerHTML='<li class=\\'dim\\'>no cries yet</li>';return;}
  const evs=el.events.slice().reverse();
  evs.forEach((e,i)=>{const li=document.createElement('li');
    let r='cried '+Math.round(e.d)+'s';
    const prev=evs[i+1];
    if(prev)r+=' · '+fmtGap(e.s-(prev.s+prev.d))+' after last';
    li.innerHTML='<span>'+fmtClock(e.s)+'</span><span class=\\'dim\\'>'+r+'</span>';tl.appendChild(li);});
  badge.textContent=el.events.length+(el.events.length===1?' cry':' cries');}
function updateWait(){if(!el.active){waitText.textContent='quiet';waitfill.style.width='0%';return;}
  const cryMs=Date.now()-el.active.start;const frac=Math.min(1,cryMs/(el.wait*1000));
  const left=el.wait*1000-cryMs;waitfill.style.width=(frac*100)+'%';
  if(left<=0){waitText.className='now';waitText.textContent='time to go in - crying for '+fmt(cryMs/1000);}
  else{waitText.className='';waitText.textContent='crying for '+fmt(cryMs/1000)+' - intervene in '+fmt(left/1000);}}
setInterval(updateWait,500);

// webrtc downlink: tap to hear the nursery, tap again to mute
let pc=null,audioEl=null,soundOn=false;
const wid='w'+Math.random().toString(36).slice(2,9);
function setSnd(on,label){$('sndBtn').textContent=on?'mute':'turn sound on';if(label)$('sndHint').textContent=label;}
async function makeOffer(){
  if(pc){try{pc.close();}catch(e){}}
  pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
  pc.addTransceiver('audio',{direction:'recvonly'});
  pc.ontrack=e=>{if(!audioEl){audioEl=new Audio();audioEl.autoplay=true;}audioEl.srcObject=e.streams[0];audioEl.play().catch(()=>{});};
  pc.onicecandidate=c=>{if(c.candidate)fetch('/rtc?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to:'nursery',from:wid,candidate:c.candidate})});};
  pc.onconnectionstatechange=()=>{const s=pc.connectionState;
    if(s==='connected')setSnd(true,'nursery audio live');
    if(s==='disconnected'||s==='failed'){setSnd(false,'reconnecting');if(soundOn)setTimeout(makeOffer,1500);}};
  const offer=await pc.createOffer();await pc.setLocalDescription(offer);
  fetch('/rtc?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to:'nursery',from:wid,offer:pc.localDescription})});
  setTimeout(()=>{if(soundOn&&pc&&pc.connectionState!=='connected')$('sndHint').textContent='no live audio - is the nursery listening?';},6000);
}
$('sndBtn').addEventListener('click',async()=>{
  if(!soundOn){soundOn=true;setSnd(true,'connecting');
    if(!audioEl)audioEl=new Audio();
    try{await audioEl.play();}catch(e){} // unlock audio inside the tap
    makeOffer();}
  else{soundOn=false;if(pc){try{pc.close();}catch(e){}pc=null;}if(audioEl)audioEl.srcObject=null;setSnd(false,'sound off - orb and meter keep running');}
});
// remote soothe: watchers control the nursery's white noise
let nmode='off';
function markNoise(mode){nmode=mode;['nwhite','nbrown','noff'].forEach(id=>$(id).classList.remove('on'));
  $(mode==='white'?'nwhite':mode==='brown'?'nbrown':'noff').classList.add('on');}
function sendNoise(mode){markNoise(mode);
  fetch('/rtc?room='+CODE,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({cmd:'noise',mode:mode,vol:+$('nvol').value,from:wid})});}
$('nwhite').addEventListener('click',()=>sendNoise('white'));
$('nbrown').addEventListener('click',()=>sendNoise('brown'));
$('noff').addEventListener('click',()=>sendNoise('off'));
$('nvol').addEventListener('input',()=>{const v=+$('nvol').value;$('nvolL').textContent=Math.round(v*100)+'%';if(nmode!=='off')sendNoise(nmode);});
const es=new EventSource('/events?room='+CODE);
es.onmessage=e=>{const d=JSON.parse(e.data);
  if(d.type==='rtc'){
    if(d.hello){if(soundOn)makeOffer();return;}
    if(d.noise!==undefined){markNoise(d.noise);if(d.vol!=null){$('nvol').value=d.vol;$('nvolL').textContent=Math.round(d.vol*100)+'%';}return;}
    if(d.to!==wid)return;
    if(d.answer&&pc)pc.setRemoteDescription(d.answer).catch(()=>{});
    if(d.candidate&&pc)pc.addIceCandidate(d.candidate).catch(()=>{});
    return;
  }
  if(d.type==='init'){el.events=(d.events||[]).map(x=>({s:x.start,d:x.dur}));
    el.wait=d.settings?d.settings.wait:300;if(d.settings)setTick(d.settings.threshold);
    if(d.level&&d.level>-99){stateText.textContent='listening';stateText.className='pill live';}
    else{stateText.textContent='waiting for the nursery';stateText.className='pill';}
    clockOff=(d.now||Date.now()/1000)-Date.now()/1000;quietSince=d.quiet_since||null;
    if(d.crying&&d.cry_start){el.active={start:d.cry_start*1000};orb.classList.add('alert');stateText.textContent='alert - loud noise starting';stateText.className='pill alert';updateWait();}
    renderTimeline();tickSleep();}
  if(d.type==='state'){const lv=d.level,pct=Math.max(0,Math.min(100,((lv+60)/60)*100));bar.style.width=pct+'%';
    levelText.textContent=(lv<=-99?' - ':lv.toFixed(0)+' dB');}
  if(d.type==='settings'){el.wait=d.wait;if(d.threshold!==undefined)setTick(d.threshold);}
  if(d.type==='cry_start'){el.active={start:d.start*1000};orb.classList.add('alert');stateText.textContent='alert - loud noise starting';stateText.className='pill alert';quietSince=null;tickSleep();updateWait();}
  if(d.type==='cry_end'){orb.classList.remove('alert');stateText.textContent='quiet';stateText.className='pill live';
    if(d.recorded)el.events.push({s:d.start,d:d.dur});
    el.active=null;quietSince=d.start+d.dur;renderTimeline();updateWait();tickSleep();}
  if(d.type==='session_end'){stateText.textContent='monitoring stopped';stateText.className='pill';orb.classList.remove('alert');quietSince=null;tickSleep();}
};
es.onerror=()=>{stateText.textContent='reconnecting';stateText.className='pill';};
"""
    return _page("watch", WATCH_CSS, body, js).replace("__CODE__", code)


# --------------------------------------------------------------------------
# History page
# --------------------------------------------------------------------------
HISTORY_CSS = """
  .pagehead{display:flex;align-items:center;gap:14px;margin-top:38px;flex-wrap:wrap}
  .pagehead h1{font-family:var(--serif);font-weight:600;font-size:2.1rem;margin:0;letter-spacing:-.01em}
  .roomchip{font-size:.8rem;color:var(--teal);border:1px solid rgba(69,217,190,.3);background:rgba(69,217,190,.08);
            padding:5px 12px;border-radius:999px;letter-spacing:.14em;font-weight:600}
  table{width:100%;border-collapse:collapse;font-size:.9rem;margin-top:8px}
  th,td{text-align:left;padding:11px 10px;border-bottom:1px solid var(--line)}
  th{color:var(--faint);font-weight:600;font-size:.7rem;text-transform:uppercase;letter-spacing:.1em}
  td{font-variant-numeric:tabular-nums}
  tbody tr:hover td{background:rgba(69,217,190,.05)}
  tbody tr:last-child td{border-bottom:none}
  .big{font-family:var(--serif);font-size:2.1rem;font-weight:600;margin:0;letter-spacing:-.01em}
  .stat{text-align:center;padding:22px 14px}
  .stat .lbl{color:var(--faint);font-size:.78rem;margin:4px 0 0}
  .none{color:var(--faint);font-style:italic}
  .daygrid{display:flex;gap:18px;align-items:flex-end;min-height:240px;padding-top:16px;overflow-x:auto}
  .daycol{flex:1;text-align:center;min-width:64px}
  .daycol .bar{position:relative;overflow:hidden;width:36px;margin:0 auto;background:linear-gradient(180deg,var(--teal),#2b8f6f);
       border-radius:9px 9px 3px 3px;transition:filter .15s ease}
  .daycol:hover .bar{filter:brightness(1.14)}
  .daycol .barlbl{font-size:.72rem;color:var(--muted);margin-bottom:6px;font-variant-numeric:tabular-nums}
  .daycol .top{font-size:.88rem;font-weight:600;margin-top:9px}
  .daycol .wk{font-size:.7rem;color:var(--faint);margin-top:4px;text-transform:uppercase;letter-spacing:.06em}
"""


def history_page(code):
    body = """
  <div class='wrap'>
    <div class='pagehead'>
      <h1>sleep history</h1>
      <span class='roomchip'>__CODE__</span>
    </div>
    <div class='card'>
      <span class='eyebrow'>this week</span>
      <h2>naps and nights</h2>
      <p class='hint' style='margin:2px 0 0'>total sleep per day</p>
      <div id='days' class='none'>loading</div>
    </div>
    <div class='grid g4' id='stats'></div>
    <div class='card'>
      <span class='eyebrow'>log</span>
      <h2>sessions</h2>
      <p class='hint' style='margin:2px 0 0'>stored only on the device running hush - no cloud copy exists</p>
      <div id='rows' class='none' style='margin-top:8px'>loading</div>
    </div>
  </div>
"""
    js = """
const CODE='__CODE__';
const $=id=>document.getElementById(id);
function fmt(s){s=Math.max(0,Math.round(s||0));const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);return h?h+'h '+m+'m':m+'m '+String(s%60).padStart(2,'0')+'s';}
function tstr(ts){return new Date(ts*1000).toLocaleString([],{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}
function dayKey(ts){const d=new Date(ts*1000);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function wd(ts){return new Date(ts*1000).toLocaleDateString('en-US',{weekday:'short'});}
function md(ts){return new Date(ts*1000).toLocaleDateString('en-US',{month:'numeric',day:'numeric'});}

fetch('/api/history?room='+CODE).then(r=>r.json()).then(data=>{
  const h=data.sessions||[];
  // group by day
  const g={};
  h.forEach(s=>{
    const k=dayKey(s.start);
    if(!g[k])g[k]={naps:0,len:0,cry:0,quiet:0,first:s.start};
    const L=s.end-s.start;
    g[k].naps++; g[k].len+=L; g[k].cry+=s.cry_time; g[k].quiet+=Math.max(0,L-s.cry_time);
  });
  const days=Object.keys(g).sort().slice(-7).map(k=>g[k]).map(d=>({
    naps:d.naps, len:d.len, cry:d.cry, quiet:d.quiet, wk:wd(d.first), md:md(d.first)}));
  const maxLen=Math.max(1,...days.map(d=>d.len));

  // this week bars (oldest first)
  const dw=$('days');
  if(!days.length){dw.className='none';dw.textContent='no naps tracked yet';}
  else{
    dw.className='daygrid';
    dw.innerHTML=days.map(d=>{
      const pct=Math.max(6,Math.round(140*d.len/maxLen));
      const tip=d.naps+' nap'+(d.naps===1?'':'s')+' - '+fmt(d.len)+' of sleep';
      return '<div class=\\'daycol\\'><div class=\\'barlbl\\'>'+fmt(d.len)+'</div>'+
        '<div class=\\'bar\\' style=\\'height:'+pct+'px\\' title=\\''+tip+'\\'></div>'+
        '<div class=\\'top\\'>'+d.naps+' nap'+(d.naps===1?'':'s')+'</div>'+
        '<div class=\\'wk\\'>'+d.wk+' '+d.md+'</div></div>';
    }).join('');
  }

  // stats
  const nb=h.length;
  const wakes=h.reduce((a,s)=>a+s.wakeups,0);
  const avg= nb?Math.round(wakes/nb*10)/10:0;
  const avgLen= nb?Math.round(h.reduce((a,s)=>a+(s.end-s.start),0)/nb):0;
  const weekLen=days.reduce((a,d)=>a+d.len,0);
  const settle=h.filter(s=>s.settle_secs!=null);
  const avgSettle= settle.length?Math.round(settle.reduce((a,s)=>a+s.settle_secs,0)/settle.length):null;
  const nights=h.filter(s=>{const hr=new Date(s.start*1000).getHours();return hr>=18||hr<3;});
  const avgNight= nights.length?Math.round(nights.reduce((a,s)=>a+(s.end-s.start),0)/nights.length):null;
  $('stats').innerHTML=
    '<div class=\\'stat card\\' style=\\'margin:0\\'><p class=\\'big\\'>'+fmt(weekLen)+'</p><p class=\\'lbl\\'>total sleep this week</p></div>'+
    '<div class=\\'stat card\\' style=\\'margin:0\\'><p class=\\'big\\'>'+fmt(avgLen)+'</p><p class=\\'lbl\\'>avg nap</p></div>'+
    '<div class=\\'stat card\\' style=\\'margin:0\\'><p class=\\'big\\'>'+avg+'</p><p class=\\'lbl\\'>avg wake-ups</p></div>'+
    '<div class=\\'stat card\\' style=\\'margin:0\\'><p class=\\'big\\'>'+(avgSettle!=null?fmt(avgSettle):'—')+'</p><p class=\\'lbl\\'>avg time to fall asleep</p></div>'+
    '<div class=\\'stat card\\' style=\\'margin:0\\'><p class=\\'big\\'>'+(avgNight!=null?fmt(avgNight):'—')+'</p><p class=\\'lbl\\'>avg night sleep</p></div>';

  const r=$('rows');
  if(!h.length){r.className='none';r.textContent='no sessions yet - start monitoring to begin capturing history';return;}
  r.className='';
  r.innerHTML='<table><thead><tr><th>nap</th><th>length</th><th>wake-ups</th><th>crying</th></tr></thead><tbody>'+h.map(s=>
    '<tr><td>'+tstr(s.start)+'</td><td>'+fmt(s.end-s.start)+'</td><td>'+s.wakeups+'</td><td>'+fmt(s.cry_time)+'</td></tr>').join('')+'</tbody></table>';
});
"""
    return _page("history", HISTORY_CSS, body, js).replace("__CODE__", code)


# --------------------------------------------------------------------------
# Brand board - a few icon / wordmark directions to react to
# --------------------------------------------------------------------------
BRAND_CSS = """
  .pagehead{margin-top:38px}
  .pagehead h1{font-family:var(--serif);font-weight:600;font-size:2.1rem;margin:0 0 8px;letter-spacing:-.01em}
  .brows{margin-top:22px}
  .brow{display:flex;align-items:center;gap:18px;background:linear-gradient(180deg,rgba(255,255,255,.025),transparent),var(--card);
        border:1px solid var(--line);border-radius:20px;padding:20px;margin-top:14px;transition:border-color .18s ease}
  .brow:hover{border-color:var(--line2)}
  .brow.cur{outline:2px solid var(--teal)}
  .brow .tno{width:30px;height:30px;border-radius:50%;background:rgba(69,217,190,.12);color:var(--teal);
        display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0}
  .brow .tile{flex-shrink:0;min-width:90px;min-height:90px;display:flex;align-items:center;justify-content:center;gap:12px}
  .brow .meta{text-align:left}
  .brow .meta .name{font-weight:600;font-size:1.05rem}
  .brow .meta .lbl{color:var(--muted);font-size:.85rem;margin-top:4px}
  .tile .word{font-family:var(--serif);font-size:1.7rem;font-weight:600;letter-spacing:-.01em}
  .b1{width:52px;height:52px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#ffd9a0,var(--amber) 60%,#b06a1a);box-shadow:0 0 18px rgba(240,180,106,.4);animation:breathe 3.4s ease-in-out infinite}
  .b2{width:50px;height:50px;border-radius:16px;background:linear-gradient(135deg,#ffcf7e,#e8922c);box-shadow:0 6px 18px rgba(240,180,106,.35)}
  .b2 .line{width:22px;height:3px;margin:5px auto 0;border-radius:2px;background:rgba(26,18,5,.35)}
  .b2 .line:first-child{margin-top:14px}
  .b3{width:52px;height:52px;position:relative}
  .ring{position:absolute;inset:2px;border-radius:50%;border:3px solid var(--amber);border-top-color:transparent;animation:spin 4s linear infinite}
  .core{position:absolute;top:50%;left:50%;width:20px;height:20px;transform:translate(-50%,-50%);border-radius:50%;background:var(--amber);box-shadow:0 0 14px rgba(240,180,106,.6)}
  @keyframes spin{to{transform:rotate(360deg)}}
  .b4{width:50px;height:50px;display:flex;align-items:flex-end;justify-content:center;gap:3px}
  .b4 b{display:block;width:6px;background:var(--amber);border-radius:3px;animation:bounce 1.1s ease-in-out infinite}
  .b4 b:nth-child(1){height:16px}.b4 b:nth-child(2){height:30px;animation-delay:.12s}
  .b4 b:nth-child(3){height:22px;animation-delay:.24s}.b4 b:nth-child(4){height:36px;animation-delay:.36s}.b4 b:nth-child(5){height:26px;animation-delay:.48s}
  @keyframes bounce{0%,100%{transform:scaleY(.55)}50%{transform:scaleY(1)}}
  .foot2{text-align:center;color:var(--faint);font-size:.8rem;margin-top:28px}
"""


def brand_page():
    body = """
  <div class='wrap'>
    <div class='pagehead'>
      <span class='eyebrow'>identity</span>
      <h1>brand directions</h1>
      <p class='tag'>a few icon + wordmark ideas - the orb ① is the current look, pick one (or mix)</p>
    </div>
    <div class='brows'>
      <div class='brow cur'>
        <span class='tno'>1</span>
        <div class='tile'><span class='b1'></span><span class='word'>hush</span></div>
        <div class='meta'><div class='name'>soft breathing orb</div><div class='lbl'>calm, warm, familiar - current</div></div>
      </div>
      <div class='brow'>
        <span class='tno'>2</span>
        <div class='tile'><span class='b2'></span><span class='word'>hush</span></div>
        <div class='meta'><div class='name'>zzz pill</div><div class='lbl'>sleepy, rounded mark</div></div>
      </div>
      <div class='brow'>
        <span class='tno'>3</span>
        <div class='tile'><span class='b3'></span><span class='word'>hush</span></div>
        <div class='meta'><div class='name'>listening ring</div><div class='lbl'>sensing, always on</div></div>
      </div>
      <div class='brow'>
        <span class='tno'>4</span>
        <div class='tile'><span class='b4'></span><span class='word'>hush</span></div>
        <div class='meta'><div class='name'>listen bars</div><div class='lbl'>audio meter, dynamic</div></div>
      </div>
    </div>
    <p class='foot2'>all shown lowercase - drop the capital for a softer, more modern mark</p>
    <div style='text-align:center;margin-top:12px'><a class='btn ghost' href='/'>← back home</a></div>
  </div>
"""
    return _page("brand", BRAND_CSS, body, "")


# --------------------------------------------------------------------------
# Room chooser - one link for everyone: /CODE asks "which device is this?"
# --------------------------------------------------------------------------
def room_page(code):
    body = """
  <div class='wrap narrow'>
    <div class='card' style='max-width:440px;margin:70px auto;text-align:center;padding:42px 28px'>
      <span class='eyebrow'>room</span>
      <div style='font-size:2.2rem;font-weight:700;letter-spacing:.3em;color:var(--teal);margin:8px 0 16px;text-indent:.3em'>__CODE__</div>
      <p class='tag'>which device is this?</p>
      <div style='display:flex;flex-direction:column;gap:10px;margin-top:20px'>
        <a class='btn' href='/monitor/__CODE__'>this phone stays with the baby</a>
        <a class='btn ghost' href='/watch/__CODE__'>i'm here to listen</a>
      </div>
      <p class='hint' style='margin-top:18px'>the nursery phone runs the mic - everyone else just listens</p>
    </div>
  </div>
"""
    return _page("room", "", body).replace("__CODE__", code)


# --------------------------------------------------------------------------
# 404
# --------------------------------------------------------------------------
def not_found_page():
    body = """
  <div class='wrap narrow' style='text-align:center;padding-top:90px'>
    <span class='eyebrow'>404</span>
    <h1 style='font-family:var(--serif);font-weight:600;font-size:2rem;margin:6px 0 10px;letter-spacing:-.01em'>nothing but quiet here</h1>
    <p class='tag'>this page doesn't exist - but somewhere, a baby is sleeping</p>
    <div style='margin-top:24px'><a class='btn' href='/'>back home</a></div>
  </div>
"""
    return _page("not found", "", body)


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send_html(self, html, code=200):
        b = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _send_json(self, obj, code=200):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _send_raw(self, text, ctype, code=200):
        b = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _q(self, name):
        return parse_qs(urlparse(self.path).query).get(name, [""])[0]

    def _go(self, loc):
        self.send_response(302)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(landing_page())
        elif path == "/brand":
            self._send_html(brand_page())
        elif path == "/start":
            self._go("/setup")
        elif path == "/setup":
            # every visitor claims a fresh room - the owner's code is never handed out
            self._send_html(setup_page(new_code()))
        elif path == "/manifest.json":
            self._send_json(MANIFEST)
        elif path == "/sw.js":
            self._send_raw(SW_JS, "text/javascript; charset=utf-8")
        elif path == "/icon.svg":
            self._send_raw(ICON_SVG, "image/svg+xml")
        elif path == "/new":
            # mint a fresh throwaway room code
            self._go("/monitor/" + new_code())
        elif path == "/monitor":
            # no bare path leads to the owner's room - mint a fresh one instead
            self._go("/monitor/" + new_code())
        elif path == "/history":
            self._go("/setup")
        elif path.startswith("/monitor/"):
            self._send_html(monitor_page(path.split("/")[-1].upper()))
        elif path.startswith("/watch/"):
            self._send_html(watch_page(path.split("/")[-1].upper()))
        elif path.startswith("/history/"):
            self._send_html(history_page(path.split("/")[-1].upper()))
        elif path == "/api/history":
            _, room = get_room(self._q("room"))
            self._send_json({"sessions": room["history"][-50:]})
        elif path == "/events":
            _, room = get_room(self._q("room"))
            self._stream(room)
        elif len(path) == 7 and path[1:].isalnum():
            # bare room code: one link for everyone, choose the role here
            self._send_html(room_page(path[1:].upper()))
        else:
            self._send_html(not_found_page(), 404)

    def do_POST(self):
        path = urlparse(self.path).path
        code, room = get_room(self._q("room"))
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) or b"{}"
        data = json.loads(body) if body else {}

        if path == "/report":
            level = float(data.get("level", -100))
            crying = bool(data.get("crying", False))
            room["level"] = level
            now = time.time()
            if not room["session_open"]:
                room["session_open"] = True
                room["session_start"] = now
                room["events"] = []
                room["cry_time"] = 0.0
                room["wakeups"] = 0
                room["settle_at"] = None
            if crying != room["crying"]:
                room["crying"] = crying
                if crying:
                    room["cry_start"] = now
                    broadcast(room, {"type": "cry_start", "start": now})
                else:
                    dur = now - room["cry_start"]
                    recorded = dur >= room["settings"]["minDur"]
                    if recorded:
                        room["events"].append({"start": room["cry_start"], "dur": round(dur, 1)})
                        if room["settle_at"] is None:
                            room["settle_at"] = now
                        room["cry_time"] += round(dur, 1)
                        room["wakeups"] += 1
                        if code == OWNER:
                            save_state()
                    # always close the alert for watchers - only recorded cries hit the timeline
                    broadcast(room, {"type": "cry_end", "start": room["cry_start"], "dur": round(dur, 1), "recorded": recorded})
            broadcast(room, {"type": "state", "level": round(level, 1)})

        elif path == "/settings":
            s = room["settings"]
            for k in ("threshold", "wait", "minDur"):
                if k in data:
                    s[k] = float(data[k])
            broadcast(room, {"type": "settings", "threshold": s["threshold"], "wait": s["wait"], "minDur": s["minDur"]})

        elif path == "/rtc":
            # webrtc signaling relay: offers/answers/candidates between nursery and watchers
            payload = {"type": "rtc"}
            payload.update(data)
            broadcast(room, payload)

        elif path == "/stop":
            if room["session_open"]:
                end = time.time()
                room["session_open"] = False
                sess = {
                    "start": room["session_start"], "end": end,
                    "wakeups": room["wakeups"], "cry_time": round(room["cry_time"], 1),
                }
                if room.get("settle_at"):
                    sess["settle_secs"] = round(room["settle_at"] - room["session_start"])
                room["history"].append(sess)
                room["events"] = []
                broadcast(room, {"type": "session_end"})
                if code == OWNER:
                    save_state()

        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _chunk(self, data):
        raw = data.encode("utf-8")
        self.wfile.write(f"{len(raw):X}\r\n".encode() + raw + b"\r\n")
        self.wfile.flush()

    def _stream(self, room):
        sub = queue.Queue(maxsize=200)
        with rooms_lock:
            room["subs"].append(sub)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        # padding comment defeats proxy response buffering (ignored by EventSource)
        self._chunk(": " + (" " * 4096) + "\n\n")
        init = {"type": "init", "level": room["level"], "settings": room["settings"],
                "events": room["events"], "now": time.time()}
        if room["session_open"]:
            if room["crying"]:
                init["crying"] = True
                init["cry_start"] = room.get("cry_start")
            elif room["events"]:
                last = room["events"][-1]
                init["quiet_since"] = last["start"] + last["dur"]
            else:
                init["quiet_since"] = room["session_start"]
        self._chunk("data: " + json.dumps(init) + "\n\n")
        try:
            while True:
                try:
                    msg = sub.get(timeout=2.0)
                    self._chunk("data: " + msg + "\n\n")
                except queue.Empty:
                    self._chunk(": ping\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with rooms_lock:
                try:
                    room["subs"].remove(sub)
                except ValueError:
                    pass


if __name__ == "__main__":
    print("Hush is running at  http://localhost:%d" % PORT)
    try:
        import socket
        ip = socket.gethostbyname(socket.gethostname())
        print("On your local network:  http://%s:%d" % (ip, PORT))
    except Exception:
        pass
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
