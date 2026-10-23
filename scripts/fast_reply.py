#!/usr/bin/env python3
"""Fast auto-replies: find new comments under @jessechen1991's own posts, have Claude write a reply in 陈不忧's voice
(rules in reply_style.md), and send them with the X API, 20-40 s apart, max 30 per run, stopping at the first error.
Started after every posting run (fast-reply.yml), so about every 5 minutes. Switch: data/config.json fast_replies_enabled.

Finding comments: mentions plus a `to:me is:reply` search (the mentions timeline leaves some replies out or shows them
late). To save read cost (Jesse 2026-10-22) each run reads only from state read_from: 10 minutes before the last run
(search lag), or the oldest comment still left unanswered, never more than 60 minutes back. Keeps direct replies
to me inside conversations started by my own posts, less than 24 h old, one reply per person per post (newest comment
wins). A follow-up under one of my replies counts as a new comment. Skips comments already answered: by this script
(state replied), by Jesse by hand (my own tweets, read incrementally), or skipped as spam, and comments with no Chinese characters (English-only, emoji-only).
Someone who sends the same (or nearly the same) comment twice in a row under one of my posts is muted under that
post (state muted "<person>:<post>"); their comments under other posts still get replies. Right before each send it
also asks X whether I already replied to that comment.
Each reply is written with the commenter's profile and our past exchanges (people.py, Jesse 2026-10-23).
State: data/fast_reply/state.json. Log of sent replies: data/fast_reply/log/YYYY-MM-DD.jsonl.
Claude: ANTHROPIC_API_KEY (Claude API) or CLAUDE_CODE_OAUTH_TOKEN (Claude Code on Jesse's subscription, `claude
setup-token`). --dry-run writes the replies and prints them without sending or saving state."""
import json, os, re, sys, glob, time, random, datetime, zoneinfo, subprocess, urllib.parse, difflib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_api, claude_call, people

TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
SF = f"{DATA}/fast_reply/state.json"
MAX = 30
BANNED = ("回关", "必回", "互关", "浇水", "已关", "互助", "http", "#", "@")
dry = "--dry-run" in sys.argv

cfg = json.load(open(f"{DATA}/config.json"))
if not cfg.get("fast_replies_enabled") and not dry:
    print("fast replies disabled in data/config.json"); sys.exit(0)
keys = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
if not all(os.environ.get(k) for k in keys) or not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
    print("secrets missing (X keys, or ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN); nothing sent"); sys.exit(0)

now = datetime.datetime.now(TZ)
st = json.load(open(SF)) if os.path.exists(SF) else {}
def utc(t): return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def save_state():
    if dry: return
    if "cands" in globals():   # next run starts 10 min before now, or at the oldest comment still unanswered
        done = set(st.get("answered", [])) | set(st.get("replied", [])) | set(st.get("skipped", []))
        left = [datetime.datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) for t in cands.values() if t["id"] not in done]
        st["read_from"] = utc(min([now - datetime.timedelta(minutes=10)] + [x - datetime.timedelta(seconds=1) for x in left]))
    os.makedirs(os.path.dirname(SF), exist_ok=True)
    json.dump(st, open(SF, "w"), ensure_ascii=False, indent=2)
if not st.get("uid"):
    code, js = x_api.whoami()
    if code >= 300: sys.exit(f"whoami failed {code}: {js}")
    st["uid"], st["handle"] = js["data"]["id"], js["data"]["username"]
uid, handle = st["uid"], st.get("handle", "jessechen1991")

# 1. comments: mentions + search, from read_from (at most the last 60 minutes)
start = now - datetime.timedelta(minutes=60)
if st.get("read_from"): start = max(start, datetime.datetime.fromisoformat(st["read_from"].replace("Z", "+00:00")))
p = {"max_results": "100", "tweet.fields": "created_at,conversation_id,in_reply_to_user_id,author_id,referenced_tweets",
     "expansions": "author_id,referenced_tweets.id", "user.fields": "username,name",
     "start_time": utc(start)}
tweets, users, names, refs = [], {}, {}, {}
def add(js):
    seen = {t["id"] for t in tweets}
    tweets.extend(t for t in js.get("data", []) if t["id"] not in seen)
    users.update({u["id"]: u["username"] for u in js.get("includes", {}).get("users", [])})
    names.update({u["id"]: u.get("name", "") for u in js.get("includes", {}).get("users", [])})
    refs.update({t["id"]: t for t in js.get("includes", {}).get("tweets", [])})
for _ in range(3):
    code, js = x_api._req("GET", f"{x_api.API}/2/users/{uid}/mentions?" + urllib.parse.urlencode(p))
    if code >= 300: sys.exit(f"mentions failed {code}: {json.dumps(js, ensure_ascii=False)[:300]}")
    add(js)
    nt = js.get("meta", {}).get("next_token")
    if not nt: break
    p["pagination_token"] = nt
p.pop("pagination_token", None)
sp = dict(p, query=f"to:{handle} is:reply -from:{handle}")
code, js = x_api._req("GET", f"{x_api.API}/2/tweets/search/recent?" + urllib.parse.urlencode(sp))
if code >= 300: sys.exit(f"search failed {code}: {json.dumps(js, ensure_ascii=False)[:300]}")
add(js)

# 2. my own replies since the last run, so comments Jesse answered by hand are skipped
mp = {"max_results": "100", "tweet.fields": "referenced_tweets"}
if st.get("my_since"): mp["since_id"] = st["my_since"]
else: mp["start_time"] = p["start_time"]
code, js = x_api._req("GET", f"{x_api.API}/2/users/{uid}/tweets?" + urllib.parse.urlencode(mp))
if code >= 300: sys.exit(f"my tweets failed {code}: {json.dumps(js, ensure_ascii=False)[:300]}")
answered = set(st.get("answered", []))
for t in js.get("data", []):
    st["my_since"] = str(max(int(st.get("my_since") or 0), int(t["id"])))
    answered |= {r["id"] for r in t.get("referenced_tweets", []) if r["type"] == "replied_to"}
st["answered"] = sorted(answered, key=int)[-2000:]

# 3. keep new direct replies to me in conversations started by my own posts
mine = set(st.get("my_posts", []))
for rf in glob.glob(f"{DATA}/results/*.json"):
    mine |= {r["tweet_id"] for r in json.load(open(rf)).values() if r.get("tweet_id")}
for t in tweets:
    if t.get("in_reply_to_user_id") == uid and t["conversation_id"] in {r["id"] for r in t.get("referenced_tweets", [])}:
        mine.add(t["conversation_id"])
st["my_posts"] = sorted(mine, key=int)[-500:]
done = answered | set(st.get("replied", [])) | set(st.get("skipped", []))
cut = now - datetime.timedelta(hours=24)

# Jesse 2026-10-22: someone who sends the same (or nearly the same) comment twice in a row under the same post of mine
# gets no more replies under that post (other posts are not affected).
# history: each person's last comments, {id: [post, text without @names, links, emoji, punctuation]}, plus the log.
def norm(s): return "".join(re.findall(r"[\u4e00-\u9fff0-9a-z]", re.sub(r"@\w+|https?://\S+", "", s.lower())))
def same(a, b): return a == b or (min(len(a), len(b)) >= 6 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)
hist = {k: v for k, v in st.get("history", {}).items() if all(isinstance(x, list) for x in v.values())}
muted = {k: v for k, v in st.get("muted", {}).items() if ":" in k}   # "<person id>:<post id>"
st["history"], st["muted"] = hist, muted
for f in sorted(glob.glob(f"{DATA}/fast_reply/log/*.jsonl"))[-7:]:
    for l in open(f):
        if not l.strip(): continue
        x = json.loads(l)
        if x.get("post"): hist.setdefault("@" + x["commenter"], {})[x["comment_id"]] = [x["post"], norm(x["comment"])]
for t in sorted(tweets, key=lambda t: int(t["id"])):
    a, c = t["author_id"], t["conversation_id"]
    if a == uid or t.get("in_reply_to_user_id") != uid or c not in mine: continue
    n = norm(t["text"])
    if not n: continue
    prev = {**hist.get("@" + users.get(a, ""), {}), **hist.get(a, {})}
    last = max((k for k, v in prev.items() if v[0] == c and int(k) < int(t["id"])), key=int, default=None)
    if last and f"{a}:{c}" not in muted and same(n, prev[last][1]):
        muted[f"{a}:{c}"] = users.get(a, "")
        print(f"@{users.get(a, '')} repeated a comment under post {c} ({t['text'][:30]}); no more replies there")
    hist.setdefault(a, {})[t["id"]] = [c, n]
for k in list(hist):   # keep 20 comments per person, 2000 people; log-based entries are rebuilt each run
    if k.startswith("@"): hist.pop(k); continue
    hist[k] = dict(sorted(hist[k].items(), key=lambda kv: int(kv[0]))[-20:])
for k in sorted(hist, key=lambda k: max(map(int, hist[k])))[:-2000]: hist.pop(k)

# every comment under my posts goes to the people log (user profiles, people.py), also the ones Jesse answered by hand
if not dry:
    people.log_comments([dict(t, username=users.get(t["author_id"], ""), name=names.get(t["author_id"], ""),
                              on=" ".join(refs.get(r["id"], {}).get("text", "") for r in t.get("referenced_tweets", []) if r["type"] == "replied_to"))
                         for t in tweets if t["author_id"] != uid and t.get("in_reply_to_user_id") == uid and t["conversation_id"] in mine],
                        st, now)

cands = {}
for t in tweets:
    parent = next((r["id"] for r in t.get("referenced_tweets", []) if r["type"] == "replied_to"), None)
    if t["author_id"] == uid or t.get("in_reply_to_user_id") != uid or not parent or t["id"] in done: continue
    if t["conversation_id"] not in mine: continue
    if f"{t['author_id']}:{t['conversation_id']}" in muted:   # never list again, so read_from can move on
        st.setdefault("skipped", []).append(t["id"]); st["skipped"] = st["skipped"][-3000:]; done.add(t["id"]); continue
    if not re.search(r"[\u4e00-\u9fff]", t["text"]): continue   # Jesse 2026-10-22: only reply to comments with Chinese in them
    if datetime.datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) < cut: continue
    key = (t["author_id"], parent)
    old = cands.get(key)
    if not old or int(t["id"]) > int(old["id"]): cands[key] = dict(t, parent=parent)
todo = sorted(cands.values(), key=lambda t: int(t["id"]))[:MAX]   # the rest come back on the next run
if not todo:
    save_state(); print("no new comments"); sys.exit(0)

# card posts have empty text; take the card's words from the queue
cards = dict(st.get("cards", {}))
for rf in glob.glob(f"{DATA}/results/*.json"):
    qf = f"{DATA}/queue/{os.path.basename(rf)}"
    if not os.path.exists(qf): continue
    q = {x["id"]: x for x in json.load(open(qf))["posts"]}
    for pid, r in json.load(open(rf)).items():
        if r.get("tweet_id") and q.get(pid, {}).get("card_text"): cards[r["tweet_id"]] = q[pid]["card_text"]
def clean(s):
    s = " ".join(w for w in s.split() if not w.startswith("https://t.co/"))
    return re.sub(r"^(@\w+\s*)+", "", s).strip()
items = []
for t in todo:
    ptxt = clean(refs.get(t["parent"], {}).get("text", ""))
    if t["parent"] in cards: ptxt = (ptxt + "\n[配图文字卡片] " + cards[t["parent"]]).strip()
    items.append({"comment_id": t["id"], "commenter": users.get(t["author_id"], ""),
                  "post": t["conversation_id"], "my_post": ptxt or "（只有图片，看不到内容）", "comment": clean(t["text"]) or "（只有图片或表情）"})
# Jesse 2026-10-23: reply according to who the person is and our relationship (profiles from people.py)
ph = people.history()
for i in items: i.update(people.context(i["commenter"], before=i["comment_id"], h=ph))

# 4. Claude writes the replies
recent = []
for f in sorted(glob.glob(f"{DATA}/fast_reply/log/*.jsonl"))[-2:]:
    recent += [json.loads(l)["text"] for l in open(f) if l.strip()]
schema = {"type": "object", "additionalProperties": False, "required": ["replies"], "properties": {"replies": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["comment_id", "text"],
                               "properties": {"comment_id": {"type": "string"}, "text": {"type": "string"}}}}}}
ev = people.events_text()
msg = (("中文圈最近的事（背景，评论提到了就接得上，用不上不硬塞）：\n" + ev + "\n\n" if ev else "") +
       "最近已发过的回复（不要重复）：\n" + "\n".join(recent[-60:]) +
       "\n\n要回复的评论（my_post 是你被评论的那条帖子或回复）：\n" + json.dumps(items, ensure_ascii=False, indent=1) +
       "\n\n每条评论给一条回复，comment_id 原样带回。who 是这个人的画像和你们的关系，past 是你们以前的对话（旧的在前），按关系回。")
system = open(f"{HERE}/reply_style.md").read()
out = claude_call.ask(system, msg, schema)["replies"]

by_id = {i["comment_id"]: i for i in items}
seen, rows = set(recent), []
for r in out:
    text = r["text"].strip().rstrip("。")
    if r["comment_id"] not in by_id: continue
    if not text:   # spam, scams, abuse: never reply, never list again
        st.setdefault("skipped", []).append(r["comment_id"]); by_id.pop(r["comment_id"]); continue
    if text in seen or len(text) > 60 or any(b in text for b in BANNED): continue   # retried next run
    seen.add(text)
    rows.append(dict(by_id.pop(r["comment_id"]), text=text))
if dry:
    print(*[f"@{x['commenter']}：{x['comment'][:20]} → {x['text']}" for x in rows], sep="\n"); sys.exit(0)

# 5. send, 20-40 s apart, stop at the first error
os.makedirs(f"{DATA}/fast_reply/log", exist_ok=True)
log = open(f"{DATA}/fast_reply/log/{now.date()}.jsonl", "a")
sent = 0
for x in rows:
    q = {"query": f"from:{handle} is:reply in_reply_to_tweet_id:{x['comment_id']}", "max_results": "10"}
    code, js = x_api._req("GET", f"{x_api.API}/2/tweets/search/recent?" + urllib.parse.urlencode(q))
    if code < 300 and js.get("data"):
        st["answered"].append(x["comment_id"]); continue
    if sent: time.sleep(random.uniform(20, 40))
    code, js = x_api.post(x["text"], reply_to=x["comment_id"])
    if code >= 300:
        save_state(); sys.exit(f"reply to {x['comment_id']} failed {code}: {json.dumps(js, ensure_ascii=False)[:300]}")
    sent += 1
    st.setdefault("replied", []).append(x["comment_id"])
    st["replied"] = st["replied"][-3000:]
    log.write(json.dumps({"at": datetime.datetime.now(TZ).isoformat(timespec="seconds"), "comment_id": x["comment_id"],
                          "reply_id": js.get("data", {}).get("id"), "commenter": x["commenter"],
                          "post": x["post"], "comment": x["comment"], "text": x["text"]}, ensure_ascii=False) + "\n")
    log.flush(); save_state()
    print(f"@{x['commenter']}：{x['comment'][:20]} → {x['text']}")
save_state()
print(f"sent {sent}")
