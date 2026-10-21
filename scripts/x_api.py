#!/usr/bin/env python3
"""X API helper (stdlib only, OAuth 1.0a user context).

Usage:
  x_api.py whoami                      # GET /2/users/me, no posting
  x_api.py post TEXT [IMAGE_PATH]      # upload image (optional) and post
  x_api.py reply TWEET_ID TEXT [IMAGE_PATH]  # reply to a tweet (image optional)
Env: X_API_KEY X_API_SECRET X_ACCESS_TOKEN X_ACCESS_TOKEN_SECRET
"""
import base64, hashlib, hmac, json, os, secrets, sys, time, urllib.parse, urllib.request, urllib.error

API = "https://api.x.com"

def _q(s):
    return urllib.parse.quote(str(s), safe="~")

def _auth_header(method, url, params=None):
    ck, cs = os.environ["X_API_KEY"], os.environ["X_API_SECRET"]
    tk, ts = os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"]
    oauth = {
        "oauth_consumer_key": ck, "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(int(time.time())),
        "oauth_token": tk, "oauth_version": "1.0",
    }
    u = urllib.parse.urlsplit(url)
    allp = dict(urllib.parse.parse_qsl(u.query)); allp.update(params or {}); allp.update(oauth)
    base_url = f"{u.scheme}://{u.netloc}{u.path}"
    pstr = "&".join(f"{_q(k)}={_q(v)}" for k, v in sorted(allp.items()))
    base = "&".join([method.upper(), _q(base_url), _q(pstr)])
    key = f"{_q(cs)}&{_q(ts)}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_q(k)}="{_q(v)}"' for k, v in sorted(oauth.items()))

def _req(method, url, body=None, headers=None, sign_params=None):
    h = {"Authorization": _auth_header(method, url, sign_params)}
    h.update(headers or {})
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            txt = resp.read().decode()
            return resp.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")
        try: return e.code, json.loads(txt)
        except Exception: return e.code, {"raw": txt}

def whoami():
    return _req("GET", f"{API}/2/users/me")

def upload_image(path):
    """v2 media upload (multipart). Returns media_id string."""
    data = open(path, "rb").read()
    boundary = "----xops" + secrets.token_hex(8)
    parts = []
    cat = "tweet_gif" if path.lower().endswith(".gif") else "tweet_image"
    for name, val in (("media_category", cat),):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="{os.path.basename(path)}"\r\nContent-Type: {mime}\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    code, js = _req("POST", f"{API}/2/media/upload", b"".join(parts),
                    {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    if code >= 300:
        raise RuntimeError(f"media upload failed {code}: {json.dumps(js, ensure_ascii=False)}")
    d = js.get("data", js)
    return str(d.get("id") or d.get("media_id_string") or d.get("media_id"))

def post(text, image=None, reply_to=None):
    body = {"text": text} if text else {}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
    if image:
        body["media"] = {"media_ids": [upload_image(image)]}
    return _req("POST", f"{API}/2/tweets", json.dumps(body).encode(), {"Content-Type": "application/json"})

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "whoami"
    if cmd == "whoami":
        code, js = whoami()
    elif cmd == "post":
        code, js = post(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "reply":
        code, js = post(sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None, reply_to=sys.argv[2])
    else:
        sys.exit(__doc__)
    print(code, json.dumps(js, ensure_ascii=False))
    sys.exit(0 if code < 300 else 1)
