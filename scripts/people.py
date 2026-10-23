#!/usr/bin/env python3
"""User profiles for the people who interact with @jessechen1991 most (Jesse 2026-10-23: 「我每天互动最多的用户，每个都需要
用户画像，然后根据我和他之间的关系回帖」). No extra X API reads: everything comes from comments fast_reply.py already
fetched (data/people/comments/) and the replies it sent (data/fast_reply/log/).

  people.py build [--if-due] [--dry-run]   # Claude writes/refreshes profiles; --if-due: only when the last build is
                                            # people_every_hours (config, default 8) old
  people.py show HANDLE...                  # print what fast_reply.py hands Claude for these people
  people.py events [DAYS]                   # recent 中文圈 events
  people.py add-events FILE.json SOURCE     # append events [{"event": "...", "who": ["handle", ...]}] (radar routine)

A build profiles the top people_top (config, default 15) commenters of today and yesterday with at least 2 comments in the last 14 days,
plus everyone who already has a profile and commented since it was written; at most 25 people per build.
Files: data/people/profiles.json (written by builds), data/people/overrides.json (Jesse's corrections, win over Claude:
{"handle": {"relation": "...", "note": "..."}}), data/people/画像.md (readable list, rebuilt with each build).
中文圈大事记 (Jesse 2026-10-23 「一些中文圈子里发生的事情也要记入记忆里」): data/people/circle.jsonl, one event per line
({date, event, who, source}), written by builds (from comments) and by the project's reply radar (from rising posts it
already read). fast_reply.py and radar drafts get the last 7 days as background.
This repo is public: profiles only describe how someone talks to 陈不忧 in public comments, no guesses about their real
identity, location, age or private life."""
import json, os, re, sys, glob, datetime, zoneinfo, collections

TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
PD = f"{DATA}/people"
PF, OF = f"{PD}/profiles.json", f"{PD}/overrides.json"
DAYS = 14
CF = f"{PD}/circle.jsonl"
RELATIONS = ["老熟人", "互怼搭子", "擦边搭子", "捧场粉", "打卡号", "杠精", "普通路人"]

def _clean(s):
    s = " ".join(w for w in (s or "").split() if not w.startswith("https://t.co/"))
    return re.sub(r"^(@\w+\s*)+", "", s).strip()

def log_comments(tweets, st, now):
    """fast_reply.py: append comments under my posts not logged before (state people_logged keeps the last 3000 ids)."""
    seen = set(st.get("people_logged", []))
    new = [t for t in sorted(tweets, key=lambda t: int(t["id"])) if t["id"] not in seen and t.get("username")]
    if not new: return
    os.makedirs(f"{PD}/comments", exist_ok=True)
    with open(f"{PD}/comments/{now.date()}.jsonl", "a") as f:
        for t in new:
            f.write(json.dumps({"id": t["id"], "at": t.get("created_at"), "uid": t["author_id"], "handle": t["username"],
                                "name": t.get("name", ""), "post": t["conversation_id"], "on": _clean(t.get("on", ""))[:80],
                                "text": _clean(t["text"])}, ensure_ascii=False) + "\n")
    st["people_logged"] = (st.get("people_logged", []) + [t["id"] for t in new])[-3000:]

def _load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default

def _jsonl(pattern, days):
    out = []
    for f in sorted(glob.glob(pattern))[-days:]:
        out += [json.loads(l) for l in open(f) if l.strip()]
    return out

def _bj_date(at):
    if not at: return ""
    return str(datetime.datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(TZ).date())

def history():
    """{handle: {comment_id: {date, post, on, comment, reply, name, uid}}} from the last 14 days, oldest first."""
    h = collections.defaultdict(dict)
    for c in _jsonl(f"{PD}/comments/*.jsonl", DAYS):
        h[c["handle"]][c["id"]] = {"date": _bj_date(c.get("at")), "post": c["post"], "on": c.get("on", ""),
                                   "comment": c["text"], "reply": None, "name": c.get("name", ""), "uid": c.get("uid")}
    for x in _jsonl(f"{DATA}/fast_reply/log/*.jsonl", DAYS):
        e = h[x["commenter"]].setdefault(x["comment_id"], {"date": x["at"][:10], "post": x.get("post", ""), "on": "",
                                                            "comment": x["comment"], "name": "", "uid": None})
        e["reply"] = x["text"]
        e["date"] = e["date"] or x["at"][:10]
    cards = _load(f"{DATA}/fast_reply/state.json", {}).get("cards", {})   # my card posts: the card's words
    for v in h.values():
        for e in v.values():
            if not e["on"] and e["post"] in cards: e["on"] = cards[e["post"]][:80]
    return {k: dict(sorted(v.items(), key=lambda kv: int(kv[0]))) for k, v in h.items()}

def add_events(events, source, now=None):
    now = now or datetime.datetime.now(TZ)
    old = {e["event"] for e in recent_events(3)}
    new = [e for e in events if e.get("event", "").strip() and e["event"].strip() not in old]
    if not new: return 0
    os.makedirs(PD, exist_ok=True)
    with open(CF, "a") as f:
        for e in new:
            f.write(json.dumps({"date": str(now.date()), "event": e["event"].strip(), "who": [w.lstrip("@") for w in e.get("who", [])],
                                "source": source}, ensure_ascii=False) + "\n")
    return len(new)

def recent_events(days=7, n=30):
    if not os.path.exists(CF): return []
    cut = str(datetime.datetime.now(TZ).date() - datetime.timedelta(days=days))
    return [e for e in (json.loads(l) for l in open(CF) if l.strip()) if e["date"] > cut][-n:]

def events_text(days=7, n=30):
    return "\n".join(f"- {e['date'][5:]} {e['event']}" + (f"（{'、'.join('@' + w for w in e['who'])}）" if e["who"] else "")
                     for e in recent_events(days, n))

def _who(handle, ex):
    prof = _load(PF, {}).get("people", {}).get(handle)
    over = _load(OF, {}).get(handle, {})
    days = len({e["date"] for e in ex.values()})
    stats = f"最近 {DAYS} 天评论 {len(ex)} 次（{days} 天）"
    if not prof and not over:
        return ("新面孔，第一次来评论" if len(ex) <= 1 else f"还没有画像，{stats}")
    p = dict(prof or {}, **{k: v for k, v in over.items() if v})
    parts = [f"关系：{p.get('relation', '普通路人')}", stats]
    for k, label in (("persona", "这个人"), ("tone", "说话风格"), ("jokes", "你们的老梗"), ("reply_tips", "怎么回"), ("note", "Jesse 备注")):
        if p.get(k): parts.append(f"{label}：{p[k]}")
    return "；".join(parts)

def context(handle, before=None, h=None):
    """fast_reply.py: {"who": profile line, "past": last 4 exchanges before this comment}."""
    h = h if h is not None else history()
    ex = {k: v for k, v in h.get(handle, {}).items() if before is None or int(k) < int(before)}
    past = [f"TA：{e['comment'][:60]} → 你：{e['reply']}" if e["reply"] else f"TA：{e['comment'][:60]}（没回或 Jesse 手动回的）"
            for e in list(ex.values())[-4:]]
    return {"who": _who(handle, h.get(handle, {}) or {"x": {"date": ""}}), "past": past}

SYSTEM = f"""你在帮 X 账号 @jessechen1991（陈不忧，一个只发犀利吐槽的中文账号）整理常来评论的人的画像，之后自动回复他们的评论时会按画像和关系来回。
只根据给你的公开评论和回复来写：这个人在陈不忧评论区是什么样的人、怎么说话、常聊什么、和陈不忧有什么来往。
不要猜真实身份、职业、年龄、住址、私生活，不写对人的负面定性（如人品），只写互动风格。每个字段一两句，简短具体。

relation 从这几个里选一个：{"、".join(RELATIONS)}。
- 老熟人：来过很多天、来回聊过不少，彼此熟了
- 互怼搭子：爱抬杠、损陈不忧或被损，玩得起
- 擦边搭子：评论常带擦边/荤段子
- 捧场粉：主要夸、附和、哈哈哈
- 打卡号：主要早安、互关、报到、套话
- 杠精：较真、反驳观点、带情绪
- 普通路人：来过几次，看不出明显特点
persona：这个人在评论区的样子（如「每天早上来打卡的蓝V，爱接时事帖的梗」）。tone：说话风格。topics：常在哪类帖子下评论/聊什么。
jokes：你们之间来回出现过的梗或称呼，没有就留空。reply_tips：陈不忧回他时该怎么回（一句话，如「可以直接损，他接得住」「别重复早安套话，换个角度调侃打卡这件事」）。
已有画像的人：结合新评论更新，不要无故推翻。handle 原样带回。

events：从这些评论里看出的中文圈（中文推特/X 圈）最近发生的事、流行的梗或话题，0 到 3 条，每条一句话，who 填相关的 handle。
只记圈子里的事（谁和谁吵起来了、大家都在聊什么、新出的梗），不记某个人的私事；没证实的写「网传」；和已知大事记重复的不写。没有就给空数组。"""

def build(if_due=False, dry=False):
    cfg = _load(f"{DATA}/config.json", {})
    now = datetime.datetime.now(TZ)
    pf = _load(PF, {"built_at": None, "people": {}})
    if if_due and pf.get("built_at"):
        if now - datetime.datetime.fromisoformat(pf["built_at"]) < datetime.timedelta(hours=cfg.get("people_every_hours", 8)):
            print("profiles are fresh"); return
    h = history()
    recent = {str(now.date()), str(now.date() - datetime.timedelta(days=1))}
    def n_today(k): return sum(1 for e in h[k].values() if e["date"] in recent)
    first = not pf["people"]   # first build: everyone with 2+ comments in the last 14 days
    top = [k for k in sorted(h, key=lambda k: (n_today(k), len(h[k])), reverse=True)
           if len(h[k]) >= 2 and (n_today(k) or first)][:25 if first else cfg.get("people_top", 15)]
    stale = [k for k, p in pf["people"].items() if k in h and int(max(h[k], key=int)) > int(p.get("last_comment") or 0)
             and k not in top]
    todo = (top + sorted(stale, key=lambda k: len(h[k]), reverse=True))[:25]
    pf["built_at"] = now.isoformat(timespec="seconds")
    if todo:
        items = []
        for k in todo:
            ex = list(h[k].values())
            items.append({"handle": k, "name": next((e["name"] for e in reversed(ex) if e["name"]), ""),
                          f"最近{DAYS}天": f"评论 {len(ex)} 次，{len({e['date'] for e in ex})} 天，今天和昨天 {n_today(k)} 次",
                          "old_profile": {f: pf["people"].get(k, {}).get(f) for f in ("relation", "persona", "tone", "topics", "jokes", "reply_tips")} if k in pf["people"] else None,
                          "exchanges": [{"date": e["date"], "on": e["on"][:50], "TA": e["comment"][:100], "陈不忧": e["reply"]} for e in ex[-25:]]})
        fields = ("relation", "persona", "tone", "topics", "jokes", "reply_tips")
        ev = {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["event", "who"],
                                         "properties": {"event": {"type": "string"}, "who": {"type": "array", "items": {"type": "string"}}}}}
        schema = {"type": "object", "additionalProperties": False, "required": ["people", "events"], "properties": {"events": ev, "people": {
            "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["handle", *fields],
                                       "properties": dict({"handle": {"type": "string"}, "relation": {"type": "string", "enum": RELATIONS}},
                                                          **{f: {"type": "string"} for f in fields[1:]})}}}}
        msg = "已知的中文圈大事记：\n" + (events_text() or "（暂无）") + "\n\n按要求给下面每个人写画像（exchanges 里旧的在前，on 是他评论的那条帖子或回复，陈不忧为空表示没自动回或 Jesse 手动回的）：\n" + json.dumps(items, ensure_ascii=False, indent=1)
        if dry:
            print(msg[:3000]); return
        sys.path.insert(0, HERE)
        import claude_call
        res = claude_call.ask(SYSTEM, msg, schema)
        print(f"{add_events(res['events'], 'comments', now)} new circle events")
        for p in res["people"]:
            k = p.pop("handle")
            if k not in h: continue
            ex = h[k]
            pf["people"][k] = dict(p, name=next((e["name"] for e in reversed(list(ex.values())) if e["name"]), pf["people"].get(k, {}).get("name", "")),
                                   uid=next((e["uid"] for e in ex.values() if e["uid"]), pf["people"].get(k, {}).get("uid")),
                                   last_comment=max(ex, key=int), updated=now.isoformat(timespec="seconds"))
            print(f"@{k}: {p['relation']} | {p['persona']}")
    os.makedirs(PD, exist_ok=True)
    json.dump(pf, open(PF, "w"), ensure_ascii=False, indent=1)
    write_md(pf, h, now)

def write_md(pf, h, now):
    over = _load(OF, {})
    rows = sorted(pf["people"].items(), key=lambda kv: len(h.get(kv[0], {})), reverse=True)
    lines = [f"# 高互动用户画像\n\n更新：{now:%Y-%m-%d %H:%M}（北京）。数据：最近 {DAYS} 天在陈不忧帖子下的评论。"
             "想改某人的关系或补一句备注，告诉 Claude 写进 overrides.json，自动回复以备注为准。\n"]
    for k, p in rows:
        o = over.get(k, {})
        ex = h.get(k, {})
        lines.append(f"## @{k}{'（' + p['name'] + '）' if p.get('name') else ''}  ·  {o.get('relation') or p['relation']}\n")
        lines.append(f"- 最近 {DAYS} 天评论 {len(ex)} 次，{len({e['date'] for e in ex.values()})} 天")
        for f, label in (("persona", "画像"), ("tone", "风格"), ("topics", "常聊"), ("jokes", "老梗"), ("reply_tips", "怎么回")):
            if p.get(f): lines.append(f"- {label}：{p[f]}")
        if o.get("note"): lines.append(f"- Jesse 备注：{o['note']}")
        lines.append("")
    open(f"{PD}/画像.md", "w").write("\n".join(lines))

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["build"]: build("--if-due" in a, "--dry-run" in a)
    elif a[:1] == ["show"]:
        h = history()
        for k in a[1:]: print(f"@{k}", json.dumps(context(k, h=h), ensure_ascii=False, indent=1))
    elif a[:1] == ["events"]: print(events_text(int(a[1]) if len(a) > 1 else 7, 100) or "no events")
    elif a[:1] == ["add-events"]: print(f"{add_events(json.load(open(a[1])), a[2] if len(a) > 2 else 'radar')} added")
    else: sys.exit(__doc__)
