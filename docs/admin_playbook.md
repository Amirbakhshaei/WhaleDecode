# WhaleDecode — Admin Playbook

## Admin Access

Admin users are defined by `ADMIN_USER_IDS` in `.env` (comma-separated Telegram user IDs).

## Commands

### Grant Paid Plan
```
/admin grant <tg_id> paid
```
Grants paid plan to a user. User must have already started the bot.

### View Stats
```
/admin stats
```
Shows:
- Total users (free/paid)
- Alerts sent today
- Active curated wallets
- Total tracked wallets

### Wallet Management

List all curated wallets:
```
/admin wallet list
```

Add a curated wallet:
```
/admin wallet add <address> <chain> <label>
```
Chains: `ETH`, `BASE`, `ARB`

Remove a curated wallet:
```
/admin wallet remove <id>
```

## Common Operations

### Restart Services
```bash
# Via Railway dashboard or CLI
railway restart bot
railway restart worker
```

### Check Worker Health
```bash
# Check worker logs for polling and alert activity
railway logs worker --tail 50
```

### Verify Alerts Are Flowing
1. Check worker logs: search for `alert_sent`
2. Check bot logs: search for `alert_dispatched`
3. Ask a user to verify they are receiving alerts

### Manual Seed
```bash
# Re-run wallet seeding
whaledecode seed
```

## Troubleshooting

### Alerts Not Being Sent
1. Check `alerts_enabled` on user (ensure not disabled)
2. Check worker is running
3. Check bot token is valid
4. Check user has started the bot

### Worker Crashes
1. Check logs for errors
2. Verify `DATABASE_URL` is accessible
3. Verify `GROQ_API_KEY` is valid
4. Restart the worker

### Polling Not Detecting Events
1. Check `CHAIN_PROVIDER` setting (should be `drpc` for real data)
2. Verify `DRPC_API_KEY` is set
3. Check curated wallets have active status
4. Check poll logs for `candidate_created` messages

## Maintenance

### Daily
- Nothing required (automated)

### Weekly
- Review dead letter events (candidate_events with status FAILED)
- Check LLM cost metrics in AgentRun table

### Monthly
- Review curated wallet quality scores
- Update curated wallets (add/remove as needed)
- Check for wallet label changes
