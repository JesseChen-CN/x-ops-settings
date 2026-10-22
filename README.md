# x-ops-settings

Posting and auto-replies for @jessechen1991 (陈不忧) run here on GitHub Actions, so they don't depend on a Claude session.

- `.github/workflows/post.yml` is started every 5 minutes from 07:00 to 23:59 Beijing time by cron-job.org (GitHub's own schedule is a backup).
- `scripts/post_due.py` posts approved queue items that are due: at most 1 per run, and at least `min_gap_minutes` after the previous post.
- `scripts/send_replies.py` sends queued replies to comments under @jessechen1991's own posts (20-40 s apart, max 30 per run, stops at the first error).
- `data/queue/` and `data/replies/` are written by the project's `repo_sync.py`. `data/results/` and `data/reply_results/` are written only by Actions.
- `data/config.json` has the on/off switches `posting_enabled` and `replies_enabled`.

The X API keys live in this repo's Actions secrets: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`.
