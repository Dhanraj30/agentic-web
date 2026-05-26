# Telegram Setup

## 1. Create bot via @BotFather

Message `@BotFather` on Telegram:
```
/newbot
```
Copy the token it gives you.

## 2. Add to .env

```
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
```

## 3. Restart

```bash
./scripts/stop.sh && ./scripts/start.sh
```

## 4. Set webhook

Your machine needs to be reachable from the internet.

**With ngrok (easiest for hackathon):**
```bash
ngrok http 8000
# Copy the https URL, e.g. https://abc123.ngrok.io

curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://abc123.ngrok.io/telegram/webhook"
```

**Verify:**
```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

## 5. Test

Open your bot in Telegram and send:
```
/start
Find gold price in India today
```

## Commands

| Command | Action |
|---|---|
| `/start` | Welcome message |
| `/status` | Agent status + current provider |
| `/provider gemini` | Switch to Gemini |
| `/provider groq` | Switch to Groq |
