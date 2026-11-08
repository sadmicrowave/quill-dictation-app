# Quill support relay

Receives a problem report from Quill's **Help > Report a Problem** form and opens an issue on GitHub, so people need no GitHub account. It runs on Cloudflare Workers (free plan is plenty).

Why a relay: anything shipped inside the app can be extracted, so the app never holds a GitHub token. It holds only this relay's public address. The token is a Cloudflare secret that can be rotated or revoked at any time with no new app release.

## One-time setup

1. **A private repository for reports**, e.g. `quill-support` (the main repo is public, and reports hold system details and log lines). Turn on Issues.
2. **A fine-grained token** (GitHub > Settings > Developer settings > Fine-grained tokens): only that repository, permission *Issues: Read and write*, nothing else. Set an expiry and calendar a renewal.
3. In this folder:
   ```bash
   npx wrangler login
   npx wrangler secret put GITHUB_TOKEN     # paste the token
   npx wrangler deploy
   ```
   Edit `GITHUB_REPO` in `wrangler.toml` first if the repository has another name.
4. Copy the address `wrangler deploy` prints (`https://quill-support.<you>.workers.dev`) into `SUPPORT_URL` in `quill/support.py`, rebuild.

## Retiring or changing the token

`npx wrangler secret put GITHUB_TOKEN` with the new token. Old app versions keep working because they never saw it. To switch the app off completely, delete the Worker; the form then says sending is unavailable and *Copy Diagnostics* still works.

## What it checks

Size limits, a per-minute limit per connection (and an optional hourly one with KV), only lines labelled `SYS` are kept from the log, `@mentions` are defused, and a reply address is stored only if `INCLUDE_CONTACT = "true"` (use that only with a private repository).

## Tests

```bash
node --test relay/worker.test.mjs
```

