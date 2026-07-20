# Hosting the viewer at dashboard.es-sandbox.com with Azure AD auth

This covers deploying `viewer/webapp/` to Azure App Service with Azure AD (Entra ID) sign-in via App Service's built-in Authentication ("Easy Auth"), and pointing `dashboard.es-sandbox.com` at it.

**Assumptions made building this** — check these against what you actually want before following the steps below:

- **Tenant:** a separate Azure AD tenant/app registration you control for this sandbox app, not Camunda's corporate tenant. `es-sandbox.com` reads as a personal sandbox domain, and registering an app in Camunda's tenant would need IT/security sign-off for something that isn't a corporate tool. If you actually want Camunda's tenant, that's a different (heavier) conversation — say so and I'll adjust this doc.
- **Users:** built to support more than one person (per-user data folders, per-user upload tokens) but only you need to actually exist as a user right now. Adding a second TAM later is a config change (a new upload token, them completing Azure AD sign-in once), not a redeploy.
- **What's already there:** written assuming nothing is provisioned yet — you have the domain, nothing else. If you already have a VM or App Service, skip to the sections that still apply.

## 1. Register an app in Azure AD

1. Portal → **Microsoft Entra ID** → **App registrations** → **New registration**.
2. Name: `daily-brief-viewer` (or whatever you'd like — cosmetic only).
3. Supported account types: **Accounts in this organizational directory only**, unless you specifically want personal Microsoft accounts too.
4. Redirect URI: leave blank for now — App Service fills this in automatically when you wire up Easy Auth in step 4.
5. Note the **Application (client) ID** and **Directory (tenant) ID** from the registration's Overview page. You'll need both shortly.
6. **Certificates & secrets** → **New client secret** → copy the secret **value** immediately (it's only shown once).

## 2. Create the App Service

1. Portal → **Create a resource** → **Web App**.
2. Runtime stack: **Python 3.12** (or latest available). OS: **Linux**.
3. Pick or create a resource group and App Service plan (Basic B1 tier is plenty for this).
4. Once created, go to **Configuration** → **Application settings** and add:
   - `FLASK_SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_hex(32))"`
   - `UPLOAD_TOKENS` — a JSON string like `{"<a-long-random-token>": "aaron-hubbart"}`. Generate the token the same way as the secret key above. This is what the daily-brief skill authenticates with — see step 6.
5. **Configuration** → **General settings** → **Startup Command**: `bash startup.sh`

## 3. Deploy the code

Simplest path — zip deploy from this repo:

```powershell
cd viewer\webapp
Compress-Archive -Path * -DestinationPath deploy.zip -Force
az webapp deploy --resource-group <your-rg> --name <your-app-name> --src-path deploy.zip --type zip
```

(Local scripts note: this repo's conventions default to Podman over Docker and zip over gz — the command above already uses zip. A Docker/Podman-based deploy is also possible via App Service's container support if you'd rather build an image, but isn't necessary for a Flask app this size.)

Confirm it's running: `https://<your-app-name>.azurewebsites.net/healthz` should return `ok` without any sign-in prompt (that route is intentionally unauthenticated).

## 4. Turn on Authentication (Easy Auth)

1. App Service → **Authentication** → **Add identity provider**.
2. Provider: **Microsoft**.
3. App registration: **Pick an existing app registration** → select the one from step 1.
4. Client secret: paste the value from step 1.6.
5. **Restrict access**: **Require authentication**.
6. **Unauthenticated requests**: **HTTP 302 Found redirect: recommended for websites**.
7. Save. This is what makes `current_user()` in `app.py` see `X-MS-CLIENT-PRINCIPAL-NAME` / `X-MS-CLIENT-PRINCIPAL-ID` on every request — no code in this app ever touches a token directly.

Test: visiting `https://<your-app-name>.azurewebsites.net/` should now redirect to a Microsoft sign-in page before showing the viewer.

## 5. Point dashboard.es-sandbox.com at it

1. App Service → **Custom domains** → **Add custom domain**, enter `dashboard.es-sandbox.com`.
2. It'll show you a TXT record (for ownership verification) and either a CNAME or A record to add. Add both at your DNS provider for `es-sandbox.com`.
3. Once verified, App Service → **Certificates** → add a **free App Service Managed Certificate** for the custom domain, then bind it in **Custom domains** (TLS/SSL type: SNI SSL).
4. `https://dashboard.es-sandbox.com` should now show the same sign-in-gated viewer as the `azurewebsites.net` URL.

## 6. Point the daily-brief skill at the upload endpoint

The skill still uploads to Google Drive as it does today — this is additive. Add two values to your local `SKILL.md` Admin Config block:

```
HOSTED_VIEWER_UPLOAD_URL: https://dashboard.es-sandbox.com/api/upload
HOSTED_VIEWER_UPLOAD_TOKEN: <the same token you put in UPLOAD_TOKENS above>
```

**This isn't wired into `references/html-output.md`'s "Delivering the file" step yet** — I held off on that change until the app above is actually deployed and confirmed working, since adding an upload call for an endpoint that doesn't exist yet would just produce failed requests on every brief run. Once you've confirmed `/healthz` and a real sign-in both work, say so and I'll add the `POST /api/upload` call to the delivery step (alongside the existing Drive upload, not instead of it).

## What this doesn't cover yet

- **Automatic reconciliation between Drive and the server.** If a brief only gets uploaded via `/api/upload` and never touched Drive (or vice versa), the two can drift. Once the upload call is wired in, both writes happen in the same skill run from the same generated HTML, so they should always match — but there's no reconciliation job checking that after the fact.
- **True multi-tenant TAM support.** This gives each person their own viewer login and data folder. It does not make the daily-brief *skill itself* multi-tenant — a second TAM using this would still need their own Claude project, their own Drive/Slack/Asana connections, and their own copy of the skill's Admin Config. Hosting the viewer for multiple people is a much smaller lift than making the automation itself multi-user.
