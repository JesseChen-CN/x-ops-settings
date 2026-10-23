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
maxn = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 1
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
# Extra posts (gm, 时事临时帖; queue field extra) don't count toward daily_limit (Jesse: the morning post is on top of the 20)
extra = {p["id"] for p in q["posts"] if p.get("extra") or p["id"] == "gm"}
posted_today = sum(1 for k, r in res.items() if r["status"] == "posted" and k not in extra)
# Gap (Jesse 2026-10-22): at least min_gap_minutes between two posts, counting posts made from the project too
times = [r["posted_at"] for r in res.values() if r.get("posted_at")] + [p["posted_at"] for p in q["posts"] if p.get("posted_at")]
last = max((datetime.datetime.fromisoformat(t) for t in times), default=None)
if last and now - last < datetime.timedelta(minutes=cfg.get("min_gap_minutes", 15)):
    print("last post at", last.isoformat(timespec="minutes"), "- waiting for the gap"); sys.exit(0)
n = 0
for p in sorted(q["posts"], key=lambda x: x["time"]):
    if p.get("status") != "approved" or p["id"] in res: continue
    t = datetime.datetime.fromisoformat(f"{q['date']}T{p['time']}").replace(tzinfo=TZ)
    if t > now: continue
    if p["id"] not in extra and posted_today >= cfg.get("daily_limit", 30):
        print("daily limit reached for", p["id"]); continue  # extras later in the day still go out
    if n >= maxn:
        print("more due items left for the next run"); break
    img = os.path.join(DATA, p["image"]) if p.get("image") else None
    if img and not os.path.exists(img): img = None
    if dry:
        print("would post", p["id"], p["time"], img); n += 1; continue
    # News link (Jesse 2026-10-23: 明星八卦和社会新闻发帖时都需要带新闻链接). data/config.json news_link_mode:
    # "reply" (default) posts the link as our own first reply right after the post, so the post keeps its reach and
    # its 280-weight limit; "inline" appends it to the post text; "off" drops it.
    link, mode = p.get("link"), cfg.get("news_link_mode", "reply")
    text = p.get("text", "")
    if link and mode == "inline": text = f"{text}\n{link}"
    try:
        code, js = x_api.post(text, img)
    except Exception as e:
        code, js = 0, {"error": str(e)}
    if code and code < 300:
        r = {"status": "posted", "tweet_id": js["data"]["id"], "url": f"https://x.com/i/status/{js['data']['id']}",
             "posted_at": datetime.datetime.now(TZ).isoformat(timespec="seconds")}
        posted_today += p["id"] not in extra
        if link and mode == "reply":
            try:
                c2, j2 = x_api.post(f"新闻原文：{link}", reply_to=js["data"]["id"])
                r["link_reply"] = j2["data"]["id"] if c2 and c2 < 300 else f"error {c2} {json.dumps(j2, ensure_ascii=False)[:200]}"
            except Exception as e:
                r["link_reply"] = f"error {e}"
    else:
        r = {"status": "error", "error": f"{code} {json.dumps(js, ensure_ascii=False)[:500]}"}
    res[p["id"]] = r; n += 1
    print(p["id"], r["status"], r.get("url") or r.get("error"))
    os.makedirs(os.path.dirname(rf), exist_ok=True)
    json.dump(res, open(rf, "w"), ensure_ascii=False, indent=2)  # save after each post so a crash never re-posts
print(f"posted today: {posted_today}")
