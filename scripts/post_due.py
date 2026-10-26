#!/usr/bin/env python3
"""GitHub Actions version of post_due.py: post approved queue items that are due.
Queue: data/queue/YYYY-MM-DD.json (Asia/Shanghai date), synced from the project by repo_sync.py.
Image paths in the queue are relative to data/. Results go to data/results/YYYY-MM-DD.json
(id -> status, tweet_id, url, posted_at | error), which only this script writes, so it never
conflicts with repo_sync.py pushing queue edits at the same time. At most --max items per run (default 2), so a
backlog after downtime goes out spread over several runs instead of all at once."""
import json, os, re, sys, datetime, zoneinfo
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
# Browser posting (Jesse 2026-10-25「以后自动发帖也由浏览器来干」): his Chrome posts due items first. This script is the
# fallback when his computer is off: it leaves an item alone until it is browser_grace_minutes overdue, and before posting
# checks his recent tweets so an item the browser already posted is recorded instead of posted twice.
browser = cfg.get("browser_posting", False)
grace = datetime.timedelta(minutes=cfg.get("browser_grace_minutes", 30))
_recent = None
# Time placeholders (Jesse 2026-10-26「把这种随环境变化的日期值写成动态变量，发送时自动填入」): drafts keep {今天} {星期}
# {明天} {明天星期} {时段} {问候}; they are filled with Beijing time at the moment of posting (the browser does the same).
def fill(t, at=None):
    at = at or datetime.datetime.now(TZ)
    nx = at + datetime.timedelta(days=1)
    wd = "一二三四五六日"
    h = at.hour
    part = "凌晨" if h < 5 else "早上" if h < 11 else "中午" if h < 13 else "下午" if h < 18 else "晚上"
    greet = {"早上": "早上好", "中午": "中午好", "下午": "下午好", "晚上": "晚上好", "凌晨": "夜猫子们好"}[part]
    vals = {"今天": f"{at.month}月{at.day}日", "星期": "周" + wd[at.weekday()], "明天": f"{nx.month}月{nx.day}日",
            "明天星期": "周" + wd[nx.weekday()], "时段": part, "问候": greet}
    return re.sub(r"\{(今天|星期|明天星期|明天|时段|问候)\}", lambda m: vals[m.group(1)], t or "")
def _norm(t):
    return re.sub(r"https?://\S+|\s+", "", t or "")[:40]
def browser_posted(p):
    """The tweet the browser posted for this item, if any, matched on the first 40 non-space characters."""
    global _recent
    if _recent is None:
        uid = x_api.whoami()[1].get("data", {}).get("id")
        code, js = x_api._req("GET", f"{x_api.API}/2/users/{uid}/tweets?max_results=20&exclude=replies,retweets&tweet.fields=created_at") if uid else (0, {})
        _recent = js.get("data", []) if code and code < 300 else []
    # placeholders were filled at the browser's send time, so fill them with each tweet's own time before comparing
    def at(t):
        try: return datetime.datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).astimezone(TZ)
        except Exception: return None
    return next((t for t in _recent if _norm(fill(p.get("text"), at(t))) and _norm(fill(p.get("text"), at(t))) == _norm(t.get("text"))), None)
n = 0
for p in sorted(q["posts"], key=lambda x: x["time"]):
    if p.get("status") != "approved" or p["id"] in res: continue
    t = datetime.datetime.fromisoformat(f"{q['date']}T{p['time']}").replace(tzinfo=TZ)
    if t > now: continue
    if browser and not dry:
        if now - t < grace: continue  # the browser gets the first go
        bt = browser_posted(p)
        if bt:
            res[p["id"]] = {"status": "posted", "by": "browser", "tweet_id": bt["id"], "url": f"https://x.com/i/status/{bt['id']}",
                            "posted_at": bt.get("created_at") or now.isoformat(timespec="seconds")}
            posted_today += p["id"] not in extra
            print(p["id"], "already posted by the browser", res[p["id"]]["url"])
            os.makedirs(os.path.dirname(rf), exist_ok=True); json.dump(res, open(rf, "w"), ensure_ascii=False, indent=2)
            continue
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
    text = fill(p.get("text", ""))
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
        # 长文 (Jesse 2026-10-26): the sources go out as our own first reply (first_reply), not as links in the post
        if p.get("first_reply"):
            try:
                c3, j3 = x_api.post(p["first_reply"], reply_to=js["data"]["id"])
                r["first_reply"] = j3["data"]["id"] if c3 and c3 < 300 else f"error {c3} {json.dumps(j3, ensure_ascii=False)[:200]}"
            except Exception as e:
                r["first_reply"] = f"error {e}"
    else:
        r = {"status": "error", "error": f"{code} {json.dumps(js, ensure_ascii=False)[:500]}"}
    res[p["id"]] = r; n += 1
    print(p["id"], r["status"], r.get("url") or r.get("error"))
    os.makedirs(os.path.dirname(rf), exist_ok=True)
    json.dump(res, open(rf, "w"), ensure_ascii=False, indent=2)  # save after each post so a crash never re-posts
print(f"posted today: {posted_today}")
