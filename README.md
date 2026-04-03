# LexGuard AML Pro

Railway-ready single-service build for:

- Telegram bot
- Manual quick scan flow
- Manual premium AML / KYC audit flow
- Signed PDF reports
- Verification landing page on `/verify`

## Required environment variables

- `BOT_TOKEN`
- `ADMIN_USER_ID`

## Recommended environment variables

- `BOT_NAME=LexGuard AML Pro`
- `BOT_LINK=https://t.me/LexAML_Bot`
- `SITE_URL=https://your-public-railway-url.up.railway.app`
- `FULL_REPORT_PRICE_USD=1400`
- `PAYMENT_NETWORK=USDT (TRC20)`
- `PAYMENT_WALLET=YOUR_WALLET`
- `REPORT_SIGNING_SECRET=CHANGE_ME`
- `START_BANNER_PATH=lexguard_banner.png`

## Run

The repository uses a single process:

```bash
python main.py
```

For Railway landing + bot mode, use the included `Procfile`.

## Notes

- Keep only one running bot instance, otherwise Telegram polling conflicts will happen.
- Set `SITE_URL` so verification links point to the live landing page.
- Health endpoint: `/health`
