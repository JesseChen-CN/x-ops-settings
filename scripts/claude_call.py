"""Ask Claude for structured JSON output. Used by fast_reply.py and people.py.
ANTHROPIC_API_KEY (Claude API) or CLAUDE_CODE_OAUTH_TOKEN (Claude Code on Jesse's subscription, `claude setup-token`)."""
import json, os, subprocess, sys

def ask(system, msg, schema):
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        resp = anthropic.Anthropic().beta.messages.create(
            model="claude-opus-5-5", max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", system=system,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": msg}])
        if resp.stop_reason != "end_turn":
            sys.exit(f"Claude stopped with {resp.stop_reason}")
        return json.loads(next(b.text for b in resp.content if b.type == "text"))
    # Claude Code on the subscription, no tools, structured output
    # a token pasted from a wrapped terminal line can carry line breaks
    env = dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN="".join(os.environ["CLAUDE_CODE_OAUTH_TOKEN"].split()))
    cp = subprocess.run(["claude", "-p", msg, "--model", "claude-opus-5-5", "--effort", "low", "--tools", "",
                         "--no-session-persistence", "--system-prompt", system, "--output-format", "json",
                         "--json-schema", json.dumps(schema)], capture_output=True, text=True, timeout=600, env=env)
    try: res = json.loads(cp.stdout)
    except ValueError: sys.exit(f"claude failed ({cp.returncode}): {(cp.stderr or cp.stdout)[:500]}")
    if res.get("is_error") or not res.get("structured_output"):
        sys.exit(f"claude returned nothing: {str(res.get('result'))[:300]}")
    return res["structured_output"]
