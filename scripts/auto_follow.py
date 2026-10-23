#!/usr/bin/env python3
"""Auto-follow (Jesse 2026-10-23): follow verified candidates from the daily follow check, slowly.
Candidates: data/follow/candidates/YYYY-MM-DD.json (Asia/Shanghai date), pushed by the project's repo_sync.py from
follow_check.py output: [{id, username, name, followers_count}]. Runs after every posting run (follow.yml).
Each run follows at most 1 account, only between follow_start and follow_end (Beijing hour), at least
follow_min_gap_minutes after the last follow. Daily amount is about 100 but not fixed (Jesse 2026-10-23 「每天100个吧，但不要
限死」): each day picks its own limit between follow_daily_min and follow_daily_max, and follows are paced evenly across
the window so they never come in a burst. Never follows anyone twice
(data/follow/log/*.jsonl). Never unfollows. On any API error it writes data/follow/stopped.json and stops for good
until someone deletes that file, so a rate limit or restriction is never pushed through."""
import json, os, sys, glob, random, datetime, zoneinfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_api

TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
F = f"{DATA}/follow"
UID = "1228638933837172739"  # @jessechen1991
dry = "--dry-run" in sys.argv
cfg = json.load(open(f"{DATA}/config.json"))
if not cfg.get("follow_enabled"):
    print("following disabled in data/config.json"); sys.exit(0)
if os.path.exists(f"{F}/stopped.json"):
    print("stopped after an error:", open(f"{F}/stopped.json").read()); sys.exit(0)
if not dry and not all(os.environ.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")):
    print("X secrets missing; nobody followed"); sys.exit(0)
now = datetime.datetime.now(TZ)
start, end = cfg.get("follow_start", 9), cfg.get("follow_end", 22)
if not start <= now.hour < end:
    print("outside following hours"); sys.exit(0)

log = []
for f in sorted(glob.glob(f"{F}/log/*.jsonl")):
    log += [json.loads(l) for l in open(f) if l.strip()]
done = {r["id"] for r in log}
today = [r for r in log if r["at"][:10] == f"{now:%Y-%m-%d}"]
limit = random.Random(f"{now:%Y-%m-%d}").randint(cfg.get("follow_daily_min", 85), cfg.get("follow_daily_max", 110))
if len(today) >= limit:
    print("daily follow limit reached:", len(today), "of", limit); sys.exit(0)
# pace: by this time of the window, about this many should be done (+2 slack)
frac = (now.hour - start + now.minute / 60) / (end - start)
if len(today) >= int(limit * frac) + 2:
    print("ahead of pace:", len(today), "of", limit, "today"); sys.exit(0)
if log:
    last = datetime.datetime.fromisoformat(log[-1]["at"])
    if now - last < datetime.timedelta(minutes=cfg.get("follow_min_gap_minutes", 4)):
        print("last follow at", last.isoformat(timespec="minutes"), "- waiting for the gap"); sys.exit(0)

# today's list first, then leftovers from the 2 days before
todo, seen = [], set(done)
for d in range(3):
    cf = f"{F}/candidates/{now - datetime.timedelta(days=d):%Y-%m-%d}.json"
    for c in json.load(open(cf)) if os.path.exists(cf) else []:
        if c["id"] not in seen: seen.add(c["id"]); todo.append(c)
if not todo:
    print("no candidates left"); sys.exit(0)
c = todo[0]
if dry:
    print("would follow", c["username"], f"({len(todo) - 1} left, {len(today)} of {limit} today)"); sys.exit(0)
try:
    code, js = x_api._req("POST", f"{x_api.API}/2/users/{UID}/following",
                          json.dumps({"target_user_id": c["id"]}).encode(), {"Content-Type": "application/json"})
except Exception as e:
    code, js = 0, {"error": str(e)}
at = datetime.datetime.now(TZ).isoformat(timespec="seconds")
d = (js.get("data") or {}) if isinstance(js, dict) else {}
if code and code < 300 and (d.get("following") or d.get("pending_follow")):
    os.makedirs(f"{F}/log", exist_ok=True)
    with open(f"{F}/log/{now:%Y-%m-%d}.jsonl", "a") as f:
        f.write(json.dumps({"at": at, "id": c["id"], "username": c["username"],
                            "pending": bool(d.get("pending_follow"))}, ensure_ascii=False) + "\n")
    print("followed", c["username"], f"({len(today) + 1} of {limit} today)")
else:
    err = {"at": at, "username": c["username"], "code": code, "error": json.dumps(js, ensure_ascii=False)[:500]}
    json.dump(err, open(f"{F}/stopped.json", "w"), ensure_ascii=False, indent=2)
    sys.exit(f"follow failed, auto-follow stopped: {err}")
