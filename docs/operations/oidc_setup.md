# OIDC Setup

## Nextcloud configuration

Create an OIDC client in Nextcloud and configure:

- Redirect URI: `https://postbuch.example.com/auth/callback`
- Client ID: `POSTBUCH_OIDC_CLIENT_ID`
- Client secret: `POSTBUCH_OIDC_CLIENT_SECRET`
- Scopes: `openid profile email`

## Postbuch environment

Set the following values in `.env`:

- `POSTBUCH_OIDC_ENABLED=true`
- `POSTBUCH_OIDC_SERVER_METADATA_URL`
- `POSTBUCH_OIDC_CLIENT_ID`
- `POSTBUCH_OIDC_CLIENT_SECRET`
- `POSTBUCH_OIDC_SCOPES`
- `POSTBUCH_DEV_AUTH_ENABLED=false` (recommended in production)

## Preapproval requirement

OIDC logins are allowed only for users that already exist in the `users` table and are active.

Before enabling OIDC in a new environment, seed an initial super admin:

```bash
python -m postbuch.bootstrap_super_admin --email admin@example.com --display-name "Initial Admin"
```

After that, manage additional users through `/api/users` (super admin only).
