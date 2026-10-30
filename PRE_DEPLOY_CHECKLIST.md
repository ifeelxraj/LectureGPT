# Pre-deploy checklist

- [ ] Do not upload `.env`, `lecturegpt.db`, `.lecturegpt_users/`, or credentials to GitHub.
- [ ] Configure Streamlit OIDC `[auth]` secrets and `APP_AUTH_MODE = "oidc"`.
- [ ] Add at least one valid AI provider key and model to Streamlit Secrets.
- [ ] Deploy, sign in with account A, create a lecture and save a chat.
- [ ] Sign out, sign in with account B, verify account A's lecture/chat/profile are not visible.
- [ ] Test AI generation and verify provider/model attribution.
- [ ] Test YouTube with a caption-accessible video; also test manual transcript fallback.
- [ ] Back up any local `lecturegpt.db` privately before replacing old files.
- [ ] For production durability, use managed persistent storage instead of Streamlit Cloud local SQLite files.
