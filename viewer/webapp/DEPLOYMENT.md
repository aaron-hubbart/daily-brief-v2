# Deploying the hosted viewer at dashboard.es-sandbox.com

This assumes what you described: a VM (or container host) with nginx already serving something else at `dashboard.es-sandbox.com`, and you're adding this app alongside it at a sub-path — `/daily-brief/` in the examples below, adjust freely. It uses Camunda's existing Azure AD tenant and an app registration you've already created.

Since this isn't Azure App Service, there's no platform-level Easy Auth — `app.py` does the OAuth 2.0 authorization code flow itself via MSAL. See the module docstring in `app.py` for exactly what that flow does and doesn't touch.

## 1. Finish configuring the existing app registration

You said you already have the app registration — a few things it needs, if it doesn't have them yet:

1. **Redirect URI**: Entra ID → App registrations → your app → **Authentication** → **Add a platform** → **Web** → add `https://dashboard.es-sandbox.com/daily-brief/auth/callback` (match your actual sub-path exactly). This must be an exact string match with `AZURE_REDIRECT_URI` below — trailing slashes matter.
2. **Client secret**: **Certificates & secrets** → **New client secret**, if one doesn't already exist or you don't have the value saved anywhere. Copy the **value** immediately; you can't retrieve it again later.
3. **Supported account types**: should already be single-tenant ("Accounts in this organizational directory only") for Camunda's tenant — this is what makes "any Camunda user" work correctly and is also what enforces that non-Camunda accounts can't sign in. If it's currently set to multi-tenant, narrow it to single-tenant.
4. Note the **Application (client) ID** and **Directory (tenant) ID** from the Overview page.

## 2. Server setup

```bash
# as whatever user will run this — adjust paths to match your actual layout
cd /opt/daily-brief/viewer/webapp
python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp .env.example .env
# edit .env: FLASK_SECRET_KEY, AZURE_TENANT_ID, AZURE_CLIENT_ID,
# AZURE_CLIENT_SECRET, AZURE_REDIRECT_URI, UPLOAD_TOKENS (see comments in
# the file for how to generate each value). Leave ALLOWED_GROUPS empty for
# "any Camunda tenant user."
chmod 600 .env
```

Test it runs before wiring up systemd/nginx:

```bash
set -a; source .env; set +a
venv/bin/gunicorn -c gunicorn.conf.py app:app
# in another shell: curl http://127.0.0.1:8000/healthz  -> should print "ok"
```

## 3. systemd (keeps it running, restarts on crash/reboot)

```bash
sudo cp daily-brief-viewer.service.example /etc/systemd/system/daily-brief-viewer.service
sudo nano /etc/systemd/system/daily-brief-viewer.service   # fix User/WorkingDirectory/paths for your actual layout
sudo systemctl daemon-reload
sudo systemctl enable --now daily-brief-viewer
sudo systemctl status daily-brief-viewer
```

## 4. nginx

Add the block from `nginx.conf.example` into the existing server block for `dashboard.es-sandbox.com` — don't create a separate server block, since this needs to coexist with whatever's already being served there. Then:

```bash
sudo nginx -t   # validate config before reloading
sudo systemctl reload nginx
```

## 5. Verify

- `https://dashboard.es-sandbox.com/daily-brief/healthz` → `ok`, no sign-in prompt (intentionally unauthenticated).
- `https://dashboard.es-sandbox.com/daily-brief/` → redirects to a Microsoft sign-in page, then back to the viewer once you sign in with any `@camunda.com` account.
- Sign in as two different test users and confirm each only ever sees their own (empty, at first) brief list — `/api/briefs` is scoped per-session, never client-supplied.

## 6. Roll out to test users

Nothing else to configure per-user for sign-in itself — any Camunda tenant account can already authenticate once the above is live. Two things do need a per-person step:

- **Viewing**: nothing extra — they just visit the URL and sign in. Their `data/{slug}/` folder is created automatically on first request.
- **Getting their own reports in**: each person who wants their own daily-brief skill pushing reports to this viewer needs an entry in `UPLOAD_TOKENS` (a token mapped to their slug) and their own copy of the daily-brief skill configured with that token. Signing in to view and having reports show up are two separate things — a test user can sign in today and see an empty state until either (a) they get an upload token and run their own skill, or (b) you manually drop a sample file into their `data/{slug}/` folder for a quick look.

## What's still not wired up

- **The skill itself doesn't call `/api/upload` yet.** Same as before — I held off until this is deployed and confirmed working, so we're not adding a call to an endpoint nobody's verified yet. Once you've confirmed steps 5 and 6 above, say so and I'll wire it into `references/html-output.md`'s delivery step (alongside the existing Drive upload, not instead of it) and set up the Admin Config values for whichever user(s) need it.
- **Multi-tenant automation.** This gets each test user a login and an isolated folder. It doesn't make the daily-brief *skill* itself multi-user — each person who wants their own automated briefs still needs their own Claude project and their own Drive/Slack/Asana connections. This PR is the viewer/hosting layer only.
- **Group-based restriction.** `ALLOWED_GROUPS` is there but inactive, since you want open-to-any-Camunda-user for this test. If you later want to restrict to a specific group (e.g. once this graduates past testing), that's an app-registration token-configuration change plus setting one env var — not a code change.
