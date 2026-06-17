# Meta OAuth Setup

BotNesia uses one Meta App while storing each tenant's authorized assets and tokens separately.

## Environment

```env
APP_URL=https://app.example.com
SECRET_KEY=<strong-random-secret>
CHANNEL_ENCRYPTION_KEY=<fernet-key>
META_APP_ID=<meta-app-id>
META_APP_SECRET=<meta-app-secret>
META_API_VERSION=v21.0
META_VERIFY_TOKEN=<webhook-verification-token>
META_OAUTH_REDIRECT_URI=https://app.example.com/api/integrations/meta/oauth/callback
META_EMBEDDED_SIGNUP_CONFIG_ID=<whatsapp-config-id>
```

Generate `CHANNEL_ENCRYPTION_KEY`:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Meta dashboard

1. Add Facebook Login for Business, Messenger, Instagram, and WhatsApp products.
2. Add the exact OAuth redirect URI from `META_OAUTH_REDIRECT_URI`.
3. Configure the Meta webhook callback as `https://app.example.com/webhooks/meta`.
4. Use `META_VERIFY_TOKEN` as the webhook verification token.
5. Subscribe the app to Page and Instagram messaging webhook fields.
6. Request production permissions for Pages, Messenger, Instagram messaging, and WhatsApp Embedded Signup.

## Tenant flow

- Facebook/Instagram: `Channels` -> Login with Facebook -> select Page or linked Instagram Business -> select agent.
- WhatsApp: `Channels` -> Connect WhatsApp -> Embedded Signup -> select WABA and phone number.
- Tokens are encrypted and never returned to the browser.
- `settings.manage` RBAC permission is required for all management operations.
