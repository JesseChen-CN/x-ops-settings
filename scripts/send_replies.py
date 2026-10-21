#!/usr/bin/env python3
"""Send queued auto-replies to comments under @jessechen1991's own posts.
Requests: data/replies/YYYY-MM-DD.json, a list of {comment_id, text, image?}, written by the reply
radar through repo_sync.py. Results: data/reply_results/YYYY-MM-DD.json (comment_id -> status, reply_id
| error), written only by this script. 20-40 s between replies, at most 30 per run,
and stop at the first failure (no retries)."""
import json, os, sys, time, random, datetime, zoneinfo, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_api

TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
dry = "--dry-run" in sys.argv
cfg = json.load(open(f"{DATA}/config.json"))
if not cfg.get("replies_enabled"):
    print("replies disabled in data/config.json"); sys.exit(0)
if not dry and not all(os.environ.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")):
    print("X secrets missing; nothing sent"); sys.exit(0)
today = datetime.datetime.now(TZ).date()
files = [f for f in sorted(glob.glob(f"{DATA}/replies/*.json"))
         if os.path.basename(f)[:10] >= str(today - datetime.timedelta(days=1))]
sent, first = 0, True
for qf in files:
    rf = f"{DATA}/reply_results/{os.path.basename(qf)}"
    res = json.load(open(rf)) if os.path.exists(rf) else {}
    for r in json.load(open(qf)):
        if r["comment_id"] in res: continue
        if sent >= 30:
            print("30 sent; the rest wait for the next run"); sys.exit(0)
        if dry:
            print("would reply", r["comment_id"], r["text"]); continue
        if not first: time.sleep(random.uniform(20, 40))
        first = False
        img = os.path.join(DATA, r["image"]) if r.get("image") else None
        try:
            code, js = x_api.post(r["text"], img if img and os.path.exists(img) else None, reply_to=r["comment_id"])
        except Exception as e:
            code, js = 0, {"error": str(e)}
        at = datetime.datetime.now(TZ).isoformat(timespec="seconds")
        if code and code < 300:
            out = {"status": "sent", "reply_id": js["data"]["id"], "at": at}; sent += 1
            print("sent", r["comment_id"], f"https://x.com/i/status/{js['data']['id']}")
        else:
            out = {"status": "error", "error": f"{code} {json.dumps(js, ensure_ascii=False)[:500]}", "at": at}
        res[r["comment_id"]] = out
        os.makedirs(os.path.dirname(rf), exist_ok=True)
        json.dump(res, open(rf, "w"), ensure_ascii=False, indent=2)
        if out["status"] == "error":
            print("error", r["comment_id"], out["error"], "- stopping"); sys.exit(1)
print(f"replies sent this run: {sent}")
