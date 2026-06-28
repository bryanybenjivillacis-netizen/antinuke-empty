# AntiNuke Bot

Professional Discord server protection bot. Ultra-fast detection engine with 13+ protection modules, configurable thresholds, whitelist, detailed logs, and a clean command interface.

---

## Features

| Module | What it stops |
|---|---|
| Anti-Ban | Mass ban attacks |
| Anti-Kick | Mass kick attacks |
| Anti-Channel Delete | Bulk channel deletion |
| Anti-Channel Create | Channel spam creation |
| Anti-Role Delete | Bulk role deletion |
| Anti-Role Create | Role spam creation |
| Anti-Webhook | Unauthorized webhook creation |
| Anti-Mention Spam | Mass pings / @everyone abuse |
| Anti-Emoji Delete | Bulk emoji wiping |
| Anti-Bot Add | Unauthorized bot additions |
| Anti-Server Update | Unauthorized name/icon changes |
| Anti-Prune | Mass member pruning |
| Anti-Role Permissions | Dangerous permission grants |
| Account Age Gate | Blocks new accounts from joining |

---

## Deploy to Railway (recommended)

1. **Fork / push this repo to GitHub**
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
3. Select your repository
4. In **Variables**, add:
   - `TOKEN` → your Discord bot token
   - `OWNER_IDS` → your Discord user ID (optional but recommended)
5. Railway will auto-detect `railway.toml` and start the bot as a background worker

> The `data/db.json` file is created automatically on first run and persists on Railway's volume.

---

## Local setup

```bash
git clone <your-repo-url>
cd antinuke-bot
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in your TOKEN
python main.py
```

---

## Bot permissions required

When inviting the bot, enable the following:
- Administrator (recommended for full functionality)

Or individually:
- Manage Guild, Ban Members, Kick Members, Manage Roles, Manage Channels,
  Manage Webhooks, Moderate Members, View Audit Log, Send Messages, Embed Links

**Privileged Gateway Intents** (Discord Developer Portal → Bot):
- Server Members Intent ✓
- Message Content Intent ✓

---

## Quick start commands

```
,antinuke enable                    — turn on protection
,setlogs #channel                   — set where logs go
,whitelist add @user                — exempt a trusted admin
,antinuke punishment ban            — set action (ban/kick/strip/mute)
,antinuke status                    — view full config
```

---

## All commands

### AntiNuke
```
,antinuke enable
,antinuke disable
,antinuke status
,antinuke punishment <ban|kick|strip|mute>
,antinuke module <name> <on|off>
,antinuke threshold <module> <number>
,antinuke window <module> <seconds>
,antinuke accountage <days>          (0 = disabled)
,antinuke guildage <days>            (0 = disabled)
,antinuke reset                      (bot owner only)
```

### Module names
`ban` `kick` `channeldelete` `channelcreate` `roledelete` `rolecreate`
`webhook` `mention` `emojidelete` `botadd` `everyone` `serverupdate` `prune`

### Whitelist
```
,whitelist                           — list whitelisted users
,whitelist add <@user>
,whitelist remove <@user>
,whitelist clear
,whitelist check <@user>
```

### Settings
```
,setlogs [#channel]                  — omit to clear
,setprefix <prefix>
,logembed color <#hex>
,logembed footer <text>              — supports server emojis
,logembed thumbnail <on|off>
```

### Help
```
,help
,help antinuke
,help modules
,help whitelist
,help logs
```

---

## Architecture

```
main.py          — bot init, prefix resolver, cog loader
config.py        — JSON database, default guild config
cogs/
  antinuke.py    — detection engine (in-memory rate-limit buckets)
  whitelist.py   — whitelist CRUD
  settings.py    — all configuration commands
  help.py        — professional help system
utils/
  logger.py      — professional log embed builder
data/
  db.json        — per-guild configuration (auto-created)
```

Detection is done using **in-memory deque buckets** per `(guild, user, action)` — no database hit in the hot path, making responses near-instant. Punishments are dispatched with `asyncio.create_task` so they don't block the event loop.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `TOKEN` | Yes | Discord bot token |
| `OWNER_IDS` | No | Comma-separated owner IDs |
