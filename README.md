# LectureGPT — private AI study workspace

This is the updated Streamlit application based on the uploaded deployed source code. It retains the existing dark UI, study workspace, provider router, saved chats, library, quizzes, analytics, focus mode and YouTube learning page.

## Important fixes in this build

### 1. Cross-user privacy isolation
- Hosted mode defaults to OIDC authentication. A visitor must sign in before the app opens.
- Each authenticated OIDC subject gets a different SQLite database file. Existing app queries run against that user's database only, so profile names, lectures, study packs, chats, progress and settings are separated.
- The display name is not used as an identity. A stable OIDC `sub` claim is hashed to select the user's database file.
- `APP_AUTH_MODE=local` is for a private, single-user local laptop only. Never use local mode on a public multi-user deployment.

**Storage limitation:** Streamlit Community Cloud's local filesystem should not be treated as durable production storage. Per-user SQLite files isolate users, but may be lost when the app is rebuilt/restarted. For durable multi-user production, migrate the database layer to a managed database with row-level security (e.g. PostgreSQL/Supabase) and private object storage for uploaded files. This ZIP does not pretend that ephemeral SQLite is permanent storage.

### 2. YouTube captions
- Automatic YouTube transcript fetching is retained, but YouTube can block requests from cloud-hosting IP addresses. This is an upstream restriction; no code can guarantee that cloud IPs will be allowed.
- If automatic captions fail, copy the transcript from YouTube and use **Caption fallback · paste transcript**. The pasted transcript is saved to the signed-in user's private library.
- This project does not use proxy rotation or attempt to bypass YouTube's access restrictions.

### 3. AI generation and Streamlit Secrets
- API settings are now read from environment variables / local `.env` and from Streamlit Community Cloud Secrets.
- Add at least one valid provider API key and a supported model ID. The app still needs internet access, available quota, and a provider account that permits the selected model.
- Errors returned by providers are shown in the app. A successful request cannot be guaranteed without valid credentials and quota.

## Local Windows setup (single user)

1. Extract the ZIP to a new folder.
2. Install Python 3.10 or newer.
3. Open PowerShell in the extracted folder.
4. Create a virtual environment and install dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

5. Copy `.env.example` to `.env`.
6. Add at least one valid provider API key to `.env`. `APP_AUTH_MODE=local` is already set for private local use.
7. Run:

```powershell
py -m streamlit run app.py
```

8. Open `http://localhost:8501`.

## Deploy to Streamlit Community Cloud (multi-user mode)

**Do not deploy this app publicly with `APP_AUTH_MODE=local`.**

### A. Push files to GitHub
Upload `app.py`, `requirements.txt`, `.env.example`, `.gitignore`, and `README.md`. Do not upload:
- `.env`
- `lecturegpt.db`
- `.lecturegpt_users/`
- any API key or personal database backup

### B. Configure OIDC sign-in
Create an OAuth/OIDC client with your identity provider (Google is one option). Add the Streamlit app callback URL as an authorized redirect URI:

`https://YOUR-APP-NAME.streamlit.app/oauth2callback`

In Streamlit Community Cloud, open **App → Settings → Secrets** and add the following TOML, replacing every placeholder:

```toml
APP_AUTH_MODE = "oidc"

[auth]
redirect_uri = "https://YOUR-APP-NAME.streamlit.app/oauth2callback"
cookie_secret = "REPLACE_WITH_A_LONG_RANDOM_SECRET"
client_id = "YOUR_OIDC_CLIENT_ID"
client_secret = "YOUR_OIDC_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

The provider's OAuth consent screen and redirect URI must be configured correctly. If using a provider other than Google, use that provider's OpenID Connect discovery URL.

### C. Configure AI provider secrets
Add at least one provider key in the same Streamlit Secrets editor, for example:

```toml
GROQ_API_KEY = "YOUR_GROQ_API_KEY"
GROQ_MODEL = "openai/gpt-oss-120b"

# Optional alternatives:
# GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
# GEMINI_MODEL = "gemini-2.5-flash"
# OPENROUTER_API_KEY = "YOUR_OPENROUTER_API_KEY"
# OPENROUTER_MODEL = "openrouter/free"
# NVIDIA_API_KEY = "YOUR_NVIDIA_API_KEY"
# NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# NVIDIA_MODEL = "MODEL_ID_AVAILABLE_TO_YOUR_KEY"
```

Save Secrets and reboot/redeploy the app. Test with two separate authenticated accounts: each should see a different empty library/profile at first.

## Existing data / database migration

The ZIP intentionally excludes `lecturegpt.db` because it contains personal data and the old schema has no user ownership. Do not upload that shared database to the public repository or copy it into a multi-user hosted app. Keep a private backup for local use. The new hosted OIDC mode creates a fresh database file per authenticated user.

## Supported source types
- Text-based PDF, TXT, MD and CSV
- YouTube video transcripts when captions are accessible, or transcripts pasted manually

Scanned-PDF OCR and direct audio/video transcription are not included. AI outputs can contain mistakes; verify important academic facts and answers.

## Troubleshooting
- **Sign-in screen / OIDC error:** check the `[auth]` secrets, OAuth redirect URL, client ID/secret and consent-screen configuration.
- **AI provider missing:** add the API key in Streamlit Secrets and confirm the model ID is available to that key.
- **AI quota/model error:** check the provider dashboard, quota, model availability and error displayed by LectureGPT.
- **YouTube caption error:** use the manual transcript fallback. Cloud IP blocking may not be fixable from the app.
- **Local startup error:** activate `.venv`, run `py -m pip install -r requirements.txt`, then `py -m streamlit run app.py`.
