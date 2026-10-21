#!/usr/bin/env python3
"""GitHub Actions version of post_due.py: post approved queue items that are due.
Queue: data/queue/YYYY-MM-DD.json (Asia/Shanghai date), synced from the project by repo_sync.py.
Image paths in the queue are relative to data/. Results go to data/results/YYYY-MM-DD.json
(id -> status, tweet_id, url, posted_at | error), which only this script writes, so it never
conflicts with repo_sync.py pushing queue edits at the same time. At most --max items per run (default 2), so a
backlog after downtime goes out spread over several runs instead of all at once."""
import json, os, sys, datetime, zoneinfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_api

TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
dry = "--dry-run" in sys.argv
maxn = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 2
cfg = json.load(open(f"{DATA}/config.json"))
if not cfg.get("posting_enabled"):
    print("posting disabled in data/config.json"); sys.exit(0)
if not dry and not all(os.environ.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")):
    print("X secrets missing; nothing posted"); sys.exit(0)
now = datetime.datetime.now(TZ)
qf = f"{DATA}/queue/{now:%Y-%m-%d}.json"
if not os.path.exists(qf):
    print("no queue", qf); sys.exit(0)
q = json.load(open(qf))
rf = f"{DATA}/results/{now:%Y-%m-%d}.json"
res = json.load(open(rf)) if os.path.exists(rf) else {}
posted_today = sum(1 for r in res.values() if r["status"] == "posted")
n = 0
for p in sorted(q["posts"], key=lambda x: x["time"]):
    if p.get("status") != "approved" or p["id"] in res: continue
    t = datetime.datetime.fromisoformat(f"{q['date']}T{p['time']}").replace(tzinfo=TZ)
    if t > now: continue
    if posted_today >= cfg.get("daily_limit", 30):
        print("daily limit reached"); break
    if n >= maxn:
        print("more due items left for the next run"); break
    img = os.path.join(DATA, p["image"]) if p.get("image") else None
    if img and not os.path.exists(img): img = None
    if dry:
        print("would post", p["id"], p["time"], img); n += 1; continue
    try:
        code, js = x_api.post(p.get("text", ""), img)
    except Exception as e:
        code, js = 0, {"error": str(e)}
    if code and code < 300:
        r = {"status": "posted", "tweet_id": js["data"]["id"], "url": f"https://x.com/i/status/{js['data']['id']}",
             "posted_at": datetime.datetime.now(TZ).isoformat(timespec="seconds")}
        posted_today += 1
    else:
        r = {"status": "error", "error": f"{code} {json.dumps(js, ensure_ascii=False)[:500]}"}
    res[p["id"]] = r; n += 1
    print(p["id"], r["status"], r.get("url") or r.get("error"))
    os.makedirs(os.path.dirname(rf), exist_ok=True)
    json.dump(res, open(rf, "w"), ensure_ascii=False, indent=2)  # save after each post so a crash never re-posts
print(f"posted today: {posted_today}")
