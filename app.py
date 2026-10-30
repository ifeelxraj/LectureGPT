import os, io, re, json, time, sqlite3, hashlib, mimetypes, html
from pathlib import Path
from datetime import datetime, date

import streamlit as st
import requests
from dotenv import load_dotenv

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception:
    YouTubeTranscriptApi = None

load_dotenv()
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "lecturegpt.db"  # Set after authentication below.
NOW = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")

st.set_page_config(page_title="LectureGPT", page_icon="🎓", layout="wide", initial_sidebar_state="expanded")


# -------------------- Authentication & per-user storage --------------------
def _read_secret(name, default=""):
    """Read a setting from environment/.env first, then Streamlit secrets."""
    value = os.getenv(name)
    if value not in (None, ""):
        return str(value).strip()
    try:
        value = st.secrets.get(name, default)
        return str(value).strip() if value not in (None, "") else default
    except Exception:
        return default

# Fail closed on hosted deployments: local single-user mode must be explicitly enabled.
AUTH_MODE = _read_secret("APP_AUTH_MODE", "oidc").lower()
if AUTH_MODE == "local":
    # Local development is intentionally single-user. Do not use this mode for a public app.
    DB_PATH = APP_DIR / "lecturegpt.db"
    ACTIVE_USER_ID = "local-single-user"
else:
    try:
        logged_in = bool(st.user.is_logged_in)
    except Exception:
        logged_in = False

    if not logged_in:
        st.title("🔐 Sign in to LectureGPT")
        st.write("Each learner gets a private workspace. Sign in to access your own lectures, chats and study progress.")
        st.info("For the app owner: configure Streamlit OIDC in the app's Secrets before using the hosted app.")
        try:
            st.login()
        except Exception as exc:
            # Show a useful diagnostic without printing secrets or credentials.
            detail = str(exc).replace("\\n", " ").strip()
            for secret_name in ("client_secret", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                                "GEMINI_API_KEY", "NVIDIA_API_KEY", "cookie_secret"):
                secret_value = _read_secret(secret_name, "")
                if secret_value:
                    detail = detail.replace(secret_value, "[REDACTED]")
            detail = detail[:500] if detail else "No additional error details were provided."
            st.error(f"Sign-in error ({type(exc).__name__}): {detail}")
            st.caption("Check Streamlit App settings → Secrets and the Google OAuth redirect URI. Do not share screenshots containing secret values.")
        st.stop()

    try:
        _claims = dict(st.user)
    except Exception:
        _claims = {}
    _subject = str(_claims.get("sub", "")).strip()
    if not _subject:
        st.error("Your identity provider did not return a stable subject ID. Access is blocked to protect user data.")
        st.stop()
    ACTIVE_USER_ID = _subject
    _user_folder = APP_DIR / ".lecturegpt_users"
    _user_folder.mkdir(parents=True, exist_ok=True)
    _user_key = hashlib.sha256(ACTIVE_USER_ID.encode("utf-8")).hexdigest()
    DB_PATH = _user_folder / f"{_user_key}.sqlite3"


# -------------------- Visual system --------------------
st.markdown(r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap');
:root{--bg:#070d19;--panel:#0d1728;--panel2:#101d32;--line:#1e2d47;--ink:#edf3ff;--muted:#9aaac5;--purple:#7047ff;--cyan:#18c9df;--green:#23d7a1;}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif}
.stApp,[data-testid="stAppViewContainer"]{background:radial-gradient(ellipse at 70% -10%,#1a2450 0,transparent 38%),linear-gradient(135deg,#070d19,#091222 55%,#07101d);color:var(--ink)}
[data-testid="stHeader"]{background:rgba(7,13,25,.88)} [data-testid="stToolbar"]{right:1rem}
.block-container{padding-top:1.1rem;padding-bottom:2.8rem;max-width:1600px}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#080f1c,#0b1424 55%,#0b1020);border-right:1px solid #1b2a43}
[data-testid="stSidebar"] *{color:#e8efff}
[data-testid="stSidebar"] [data-testid="stRadio"] label{border:1px solid transparent;border-radius:11px;padding:7px 10px;margin:2px 0;font-size:.91rem}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover{background:#17223c;border-color:#26395d}
.stApp h1,.stApp h2,.stApp h3,.stApp h4{font-family:'Plus Jakarta Sans',sans-serif!important;color:#f1f5ff;letter-spacing:-.025em}
.stApp p,.stApp label,.stApp [data-testid="stWidgetLabel"] p,.stApp .stMarkdown{color:#d4def1}
.stCaption,small,.muted{color:var(--muted)!important}
[data-testid="stMetric"]{background:linear-gradient(145deg,#101d32,#0b1525);border:1px solid var(--line);padding:15px 17px;border-radius:17px}
[data-testid="stMetricLabel"]{color:#9eafca!important}[data-testid="stMetricValue"]{color:#f4f7ff!important;font-family:'Plus Jakarta Sans',sans-serif}
div[data-baseweb="select"]>div,div[data-testid="stTextInput"] input,div[data-testid="stTextArea"] textarea,div[data-testid="stNumberInput"] input{background:#0b1628!important;color:#eef3ff!important;border:1px solid #2a3a56!important;border-radius:11px!important;-webkit-text-fill-color:#eef3ff!important}
input::placeholder,textarea::placeholder{color:#8192b0!important}
div[data-testid="stFileUploader"],div[data-testid="stFileUploader"] section{background:#0b1628!important;color:#dce6fa!important;border:1px dashed #344666!important;border-radius:14px!important}
div[data-testid="stFileUploader"] button{background:#172641!important;color:#edf3ff!important;border:1px solid #344666!important}
.stButton>button,.stDownloadButton>button{border-radius:11px;border:1px solid #2b3c59;background:#101d32;color:#eaf0ff;font-weight:700;min-height:2.55rem;transition:all .16s ease}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:#8064ff;color:#fff;transform:translateY(-1px)}
.stButton>button[kind="primary"]{background:linear-gradient(100deg,#6345f5,#8547ff);color:white;border:0;box-shadow:0 8px 24px #7047ff38}
.stTabs [data-baseweb="tab-list"]{gap:7px;background:#0b1525;border:1px solid #1d2c45;border-radius:13px;padding:6px}
.stTabs [data-baseweb="tab"]{border-radius:9px;color:#aebbd1;padding:0 13px;height:40px}
.stTabs [aria-selected="true"]{background:linear-gradient(100deg,#6243e9,#7647f4)!important;color:white!important}
[data-testid="stExpander"]{border:1px solid #243550!important;border-radius:14px!important;background:#0c1728!important}
[data-testid="stAlert"]{border-radius:13px}
hr{border-color:#1d2b43!important} footer{visibility:hidden}
.hero{position:relative;overflow:hidden;background:radial-gradient(circle at 88% 0%,#35235f 0,transparent 34%),linear-gradient(115deg,#111c33,#0b1525 75%);border:1px solid #283657;border-radius:23px;padding:26px 28px;margin-bottom:18px;box-shadow:0 18px 48px #0002}
.eyebrow{color:#a99bff;font-size:.76rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
.hero-title{font-family:'Plus Jakarta Sans',sans-serif;font-size:clamp(1.8rem,3vw,2.7rem);font-weight:800;letter-spacing:-.055em;color:#f6f7ff;margin:.4rem 0 .4rem;line-height:1.14}
.hero-title span{background:linear-gradient(90deg,#a998ff,#39d7ed);-webkit-background-clip:text;color:transparent}
.subtle{color:#a9b8d0!important;font-size:.96rem;line-height:1.6}
.panel{background:linear-gradient(145deg,#101c30,#0b1525);border:1px solid #21314c;border-radius:17px;padding:17px 18px;box-shadow:0 10px 28px #0001}
.panel-title{font-weight:800;font-size:1rem;color:#f0f4ff}.small-muted{color:#9bacc7!important;font-size:.82rem;line-height:1.5}
.tile{background:linear-gradient(145deg,#121f36,#0d1728);border:1px solid #253755;border-radius:16px;padding:16px;min-height:132px}
.tile-icon{font-size:1.45rem;margin-bottom:9px}.tile-title{font-weight:800;color:#f3f6ff;margin-bottom:5px}.tile-copy{color:#9eafca;font-size:.82rem;line-height:1.45}
.pill{display:inline-block;padding:4px 9px;border-radius:99px;background:#1a2d48;color:#b9c8e2;font-size:.75rem;border:1px solid #2a4063}
.progress-track{height:8px;background:#1b2a43;border-radius:20px;overflow:hidden}.progress-fill{height:100%;background:linear-gradient(90deg,#6d49ff,#1bc9dc);border-radius:20px}
.card-title{font-weight:800;color:#f0f4ff;font-size:1rem}.divider-label{font-size:.75rem;color:#8093b4;text-transform:uppercase;letter-spacing:.12em;font-weight:800}
.quiz-option{background:#0c182a;border:1px solid #293b59;border-radius:12px;padding:12px 14px;margin:8px 0}
.success-text{color:#36e2b0!important}.warning-text{color:#ffc46b!important}
.mm-root{display:inline-block;margin:14px 0 18px;padding:13px 22px;border-radius:14px;background:linear-gradient(110deg,#6243e9,#1a9db8);font-weight:800;color:white;border:1px solid #8773ff;box-shadow:0 10px 28px #0003}
.mm-branches{display:flex;flex-wrap:wrap;gap:12px;list-style:none;padding:0;margin:0;align-items:flex-start}
.mm-branches>li{flex:1 1 210px;min-width:180px;max-width:320px;list-style:none;background:#101d32;border:1px solid #314567;border-radius:13px;padding:13px;position:relative}
.mm-node{display:block;color:#eaf1ff;font-weight:700;line-height:1.45}
.mm-branches .mm-branches{display:block;margin:10px 0 0 8px;padding-left:12px;border-left:2px solid #6f59db}
.mm-branches .mm-branches>li{max-width:none;min-width:0;background:#0b1728;border:0;border-left:2px solid #1e9bb0;border-radius:0;padding:6px 8px;margin:5px 0}

</style>
""", unsafe_allow_html=True)

# -------------------- Database / migrations --------------------
def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS lectures(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,file_name TEXT NOT NULL,file_type TEXT NOT NULL,file_data BLOB NOT NULL,file_hash TEXT NOT NULL,created_at TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS study_packs(id INTEGER PRIMARY KEY AUTOINCREMENT,lecture_id INTEGER,title TEXT NOT NULL,provider TEXT NOT NULL,model TEXT NOT NULL,outputs TEXT NOT NULL,language TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(lecture_id) REFERENCES lectures(id))""")
        con.execute("""CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,lecture_id INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(lecture_id) REFERENCES lectures(id))""")
        con.execute("""CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE)""")
        con.execute("""CREATE TABLE IF NOT EXISTS study_progress(lecture_id INTEGER PRIMARY KEY,progress REAL NOT NULL DEFAULT 0,position INTEGER NOT NULL DEFAULT 0,total_units INTEGER NOT NULL DEFAULT 100,updated_at TEXT NOT NULL,FOREIGN KEY(lecture_id) REFERENCES lectures(id) ON DELETE CASCADE)""")
        con.execute("""CREATE TABLE IF NOT EXISTS study_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT NOT NULL,ended_at TEXT NOT NULL,seconds INTEGER NOT NULL,kind TEXT NOT NULL,lecture_id INTEGER)""")
        con.execute("""CREATE TABLE IF NOT EXISTS daily_goals(day TEXT PRIMARY KEY,goal_minutes INTEGER NOT NULL DEFAULT 120,completed_tasks TEXT NOT NULL DEFAULT '[]')""")
        # Existing databases may predate the chat / progress tables; CREATE IF NOT EXISTS is a safe migration.
        # Add persistent profile and per-message AI attribution to existing databases.
        con.execute("CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        cols={r[1] for r in con.execute("PRAGMA table_info(messages)").fetchall()}
        if "provider" not in cols: con.execute("ALTER TABLE messages ADD COLUMN provider TEXT")
        if "model" not in cols: con.execute("ALTER TABLE messages ADD COLUMN model TEXT")
        con.execute("PRAGMA foreign_keys=ON")
init_db()

def query_all(sql, params=()):
    with db() as con: return con.execute(sql, params).fetchall()
def query_one(sql, params=()):
    rows=query_all(sql,params); return rows[0] if rows else None
def execute(sql, params=()):
    with db() as con:
        cur=con.execute(sql,params); con.commit(); return cur.lastrowid

def setting_value(key,default=""):
    row=query_one("SELECT value FROM app_settings WHERE key=?",(key,))
    return row["value"] if row else default
def set_setting(key,value):
    execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value)))
def esc(x): return html.escape(str(x or ""))
def fmt_time(seconds):
    seconds=max(0,int(seconds)); h=seconds//3600; m=(seconds%3600)//60
    return f"{h}h {m:02d}m" if h else f"{m}m"
def progress_for(lecture_id):
    r=query_one("SELECT progress FROM study_progress WHERE lecture_id=?",(lecture_id,))
    return float(r["progress"]) if r else 0.0
def save_progress(lecture_id, progress, position=0, total_units=100):
    execute("INSERT INTO study_progress(lecture_id,progress,position,total_units,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(lecture_id) DO UPDATE SET progress=excluded.progress,position=excluded.position,total_units=excluded.total_units,updated_at=excluded.updated_at",(lecture_id,float(progress),int(position),int(total_units),NOW()))
def total_study_seconds(day=None):
    if day: r=query_one("SELECT COALESCE(SUM(seconds),0) n FROM study_sessions WHERE substr(started_at,1,10)=?",(day,))
    else: r=query_one("SELECT COALESCE(SUM(seconds),0) n FROM study_sessions")
    return int(r["n"] or 0)

# -------------------- AI provider router --------------------
def env(key, default=""): return _read_secret(key, default)
def provider_config():
    return {
        "Groq":{"key":env("GROQ_API_KEY"),"base":"https://api.groq.com/openai/v1","model":env("GROQ_MODEL","openai/gpt-oss-120b")},
        "NVIDIA":{"key":env("NVIDIA_API_KEY"),"base":env("NVIDIA_BASE_URL","https://integrate.api.nvidia.com/v1"),"model":setting_value("nvidia_model_override",env("NVIDIA_MODEL",""))},
        "OpenRouter":{"key":env("OPENROUTER_API_KEY"),"base":"https://openrouter.ai/api/v1","model":env("OPENROUTER_MODEL","openrouter/free")},
        "Gemini":{"key":env("GEMINI_API_KEY"),"base":"https://generativelanguage.googleapis.com/v1beta/openai","model":env("GEMINI_MODEL","gemini-2.5-flash")}}
def available_providers(): return [name for name,cfg in provider_config().items() if cfg["key"]]
def call_chat(provider,model,prompt,source_text):
    cfg=provider_config()[provider]
    if not cfg["key"]: raise RuntimeError(f"{provider} API key is not configured in .env.")
    headers={"Authorization":f"Bearer {cfg['key']}","Content-Type":"application/json"}
    if provider=="OpenRouter": headers.update({"HTTP-Referer":"http://localhost:8501","X-Title":"LectureGPT"})
    payload={"model":model,"messages":[{"role":"system","content":"You are LectureGPT, an accurate academic learning assistant. Stay grounded in provided source material, explain uncertainty, and use clean Markdown. For quiz requests, return valid JSON only when explicitly asked for JSON."},{"role":"user","content":prompt+"\n\nSOURCE MATERIAL:\n"+source_text}],"temperature":0.25}
    # NVIDIA hosted endpoints can cold-start; keep the wait bounded so a slow
    # backup never stalls the whole study workflow. Other providers retain a
    # slightly longer read window for large study packs.
    timeout=(5,18) if provider=="NVIDIA" else (6,35)
    response=requests.post(cfg["base"].rstrip("/")+"/chat/completions",headers=headers,json=payload,timeout=timeout)
    if response.status_code>=400: raise RuntimeError(f"{provider} returned HTTP {response.status_code}: {response.text[:700]}")
    try: return response.json()["choices"][0]["message"]["content"]
    except Exception: raise RuntimeError(f"{provider} returned an unexpected response format.")
def nvidia_available_models():
    """Return model IDs currently exposed by this NVIDIA API key."""
    cfg=provider_config()["NVIDIA"]
    if not cfg["key"]: raise RuntimeError("NVIDIA_API_KEY is not configured in .env.")
    response=requests.get(cfg["base"].rstrip("/")+"/models",headers={"Authorization":f"Bearer {cfg['key']}"},timeout=(5,12))
    if response.status_code>=400:
        raise RuntimeError(f"NVIDIA model discovery returned HTTP {response.status_code}: {response.text[:500]}")
    payload=response.json()
    models=payload.get("data",[]) if isinstance(payload,dict) else []
    return sorted({str(m.get("id")) for m in models if isinstance(m,dict) and m.get("id")})

def test_nvidia_connection(model=None):
    """Check model-list availability, then make a tiny real chat completion."""
    cfg=provider_config()["NVIDIA"]
    models=nvidia_available_models()
    chosen=(model or cfg["model"]).strip()
    if not chosen: raise RuntimeError("No NVIDIA model selected. Choose one from the discovered model list.")
    if models and chosen not in models:
        raise RuntimeError(f"Configured model '{chosen}' is not listed by NVIDIA for this key. Choose an available model in Settings.")
    reply=call_chat("NVIDIA",chosen,"Reply with exactly: LectureGPT NVIDIA connection successful.","No additional source material.")
    return chosen,reply,models

def run_router(prompt,source_text,preferred):
    cfgs=provider_config(); names=list(cfgs); preferred=preferred if preferred in cfgs else names[0]
    order=[preferred]+[p for p in names if p!=preferred]; errors=[]
    cooldowns=st.session_state.setdefault("provider_cooldowns",{})
    now=time.time()
    for provider in order:
        cfg=cfgs[provider]
        if not cfg["key"]: errors.append(f"{provider}: API key missing"); continue
        if not cfg["model"]: errors.append(f"{provider}: no model selected; choose one in Settings"); continue
        retry_after=float(cooldowns.get(provider,0) or 0)
        if retry_after>now:
            errors.append(f"{provider}: temporarily skipped after a recent timeout; retry in {max(1,int(retry_after-now))}s")
            continue
        try:
            answer=call_chat(provider,cfg["model"],prompt,source_text)
            cooldowns.pop(provider,None)
            return answer,provider,cfg["model"],errors
        except requests.exceptions.Timeout:
            cooldowns[provider]=time.time()+(90 if provider=="NVIDIA" else 45)
            errors.append(f"{provider}: request timed out; temporarily paused for this session and moved to the next provider")
        except requests.exceptions.ConnectionError:
            cooldowns[provider]=time.time()+60
            errors.append(f"{provider}: connection failed; temporarily paused for this session and moved to the next provider")
        except Exception as exc:
            message=str(exc)
            if "HTTP 410" in message or "HTTP 404" in message:
                cooldowns[provider]=time.time()+300
            errors.append(f"{provider}: {message[:500]}")
    raise RuntimeError("All configured providers failed.\n"+"\n".join(errors[-6:]))
def ai_attribution(provider,model):
    st.caption(f"✦ Response generated by **{provider} · {model}**")

# -------------------- Source extraction / prompts --------------------
def extract_source(file_name,file_type,data):
    suffix=Path(file_name).suffix.lower()
    if suffix==".pdf":
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data)); pages=[]
            for i,page in enumerate(reader.pages):
                txt=page.extract_text() or ""
                if txt.strip(): pages.append(f"[Page {i+1}]\n{txt}")
            if not pages: raise RuntimeError("No selectable text found. This may be a scanned PDF; OCR is not enabled yet.")
            return "\n\n".join(pages),f"PDF · {len(reader.pages)} pages",len(reader.pages)
        except ImportError: raise RuntimeError("PDF support missing. Run py -m pip install -r requirements.txt")
    if suffix in [".txt",".md",".csv"]:
        text=data.decode("utf-8",errors="replace"); return text,suffix[1:].upper()+" text",max(1,len(text.splitlines()))
    raise RuntimeError("Supported upload types: text-based PDF, TXT, MD and CSV.")
def youtube_id(url):
    m=re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))([A-Za-z0-9_-]{11})",url or "")
    return m.group(1) if m else None
def youtube_transcript(url, preferred_language="Auto"):
    """Fetch captions across manual/generated tracks, preferring English then Hindi.
    Supports youtube-transcript-api v1 and the older list_transcripts interface.
    """
    vid=youtube_id(url)
    if not vid: raise RuntimeError("Please enter a valid YouTube video URL.")
    if YouTubeTranscriptApi is None: raise RuntimeError("YouTube transcript package missing. Install requirements with py -m pip install -r requirements.txt")
    api=YouTubeTranscriptApi()
    try:
        if hasattr(api, "list"):
            transcript_list=api.list(vid)
        elif hasattr(YouTubeTranscriptApi, "list_transcripts"):
            transcript_list=YouTubeTranscriptApi.list_transcripts(vid)
        else:
            raise RuntimeError("Your youtube-transcript-api version does not support listing available caption tracks. Upgrade it with: py -m pip install --upgrade youtube-transcript-api")
        tracks=list(transcript_list)
        if not tracks:
            raise RuntimeError("No caption tracks are available for this video.")
        # Prefer the user's explicit choice, then common study languages, then any available track.
        pref=(preferred_language or "Auto").lower()
        def lang_code(t): return str(getattr(t,"language_code","") or "").lower()
        def rank(t):
            code=lang_code(t); generated=bool(getattr(t,"is_generated",False))
            if pref.startswith("hindi"):
                return (0 if code.startswith("hi") else 1 if code.startswith("en") else 3, 1 if generated else 0)
            if pref.startswith("english"):
                return (0 if code.startswith("en") else 1 if code.startswith("hi") else 3, 1 if generated else 0)
            # Auto: English first, Hindi second; manual tracks before generated within language.
            return (0 if code=="en" else 1 if code.startswith("en-") else 2 if code=="hi" else 3 if code.startswith("hi-") else 4, 1 if generated else 0)
        ordered=sorted(tracks,key=rank)
        errors=[]
        for track in ordered:
            try:
                if hasattr(track,"fetch"):
                    fetched=track.fetch()
                else:
                    fetched=api.fetch(vid, languages=[lang_code(track)])
                snippets=list(fetched)
                parts=[]
                for item in snippets:
                    value=getattr(item,"text",None)
                    if value is None and isinstance(item,dict): value=item.get("text","")
                    if value: parts.append(str(value))
                text="\n".join(parts).strip()
                if text:
                    label=str(getattr(track,"language",lang_code(track)) or lang_code(track))
                    if bool(getattr(track,"is_generated",False)): label += " (auto-generated)"
                    return text,vid,label
                errors.append(f"{lang_code(track)}: empty captions")
            except Exception as e:
                errors.append(f"{lang_code(track)}: {e}")
        available=", ".join(f"{getattr(t,'language','caption')} [{lang_code(t)}]{' auto-generated' if getattr(t,'is_generated',False) else ''}" for t in tracks)
        raise RuntimeError(f"Caption tracks were found but could not be downloaded. Available tracks: {available}. YouTube may be blocking caption requests. Try another video or paste its transcript manually.")
    except Exception as e:
        msg=str(e)
        if "Caption tracks were found" in msg or "No caption tracks" in msg or "does not support listing" in msg:
            raise RuntimeError(msg)
        raise RuntimeError(f"Could not fetch captions. YouTube may block transcript requests or the video may restrict access. Details: {msg}")

def make_prompt(outputs,language,summary_length,notes_style,difficulty,mcq_count,instructions):
    desc={"AI Summary":f"Write a {summary_length.lower()} summary, key concepts and takeaways.","Study Notes":f"Create structured {notes_style.lower()} study notes with definitions and examples.","MCQs":f"Create exactly {mcq_count} MCQs. Include four options A-D, one correct answer and a short explanation. In a fenced JSON block use schema {{\"questions\":[{{\"question\":\"...\",\"options\":{{\"A\":\"...\",\"B\":\"...\",\"C\":\"...\",\"D\":\"...\"}},\"answer\":\"A\",\"explanation\":\"...\"}}]}}. Set answer to exactly A, B, C, or D. Ensure valid JSON, double quotes, no trailing commas, and close every bracket. Do not put answers in the visible question text.","Flashcards":"Create exactly 12 concise flashcards. Return exactly one valid JSON object and no Markdown fences, using schema {\"flashcards\":[{\"front\":\"question or term\",\"back\":\"concise answer\"}]}. Ensure valid JSON, double quotes, no trailing commas, and close every bracket. No introductory essay.","Mind Map":"Create a clear hierarchical outline for a visual mind map. First line exactly **CENTRAL TOPIC: [topic]**. Then 4-7 top-level bullets, each with 2-4 indented sub-bullets. Keep each node short (2-8 words). Do not use tables, prose paragraphs, Mermaid or code fences.","Question Bank":f"Create short-answer and long-answer questions with model answers at {difficulty.lower()} difficulty. Separate questions from model answers clearly.","Revision Sheet":"Create an exam-ready last-minute revision sheet with headings: Must-Know Concepts, Definitions, Formulas/Rules, Important Examples, Common Mistakes, and 5-Minute Recall Checklist. Use concise bullets and tables where useful."}
    extra="\nAdditional instructions: "+instructions.strip() if instructions.strip() else ""
    return f"Create all requested study materials in {language}. Use clean Markdown, meaningful headings, short paragraphs and tables only when helpful. Stay grounded in source.\n"+"\n".join("### "+o+"\n"+desc[o] for o in outputs)+extra

def _json_candidates(content):
    """Yield JSON payloads from fenced, prefixed, suffixed or embedded output."""
    if not isinstance(content, str):
        return
    seen=set()
    for m in re.finditer(r"```(?:json|javascript|js)?\s*(.*?)\s*```", content, re.S | re.I):
        candidate=m.group(1).strip()
        if candidate and candidate not in seen:
            seen.add(candidate); yield candidate
    decoder=json.JSONDecoder()
    for m in re.finditer(r"[\[{]", content):
        try:
            obj, consumed=decoder.raw_decode(content[m.start():])
            if isinstance(obj,(dict,list)):
                candidate=json.dumps(obj,ensure_ascii=False)
                if candidate not in seen:
                    seen.add(candidate); yield candidate
        except Exception:
            continue
    # Salvage individually valid objects from a malformed/truncated outer array.
    # This handles models that emit a valid first card/question but omit a final ]}.
    for m in re.finditer(r"\{\s*\"(?:front|question|prompt|stem)\"\s*:", content, re.I):
        try:
            obj, consumed=decoder.raw_decode(content[m.start():])
            if isinstance(obj,dict):
                candidate=json.dumps(obj,ensure_ascii=False)
                if candidate not in seen:
                    seen.add(candidate); yield candidate
        except Exception:
            # Recover a minimal front/back pair from a cut-off JSON object.
            fragment=content[m.start():m.start()+1800]
            fm=re.search(r'"(?:front|question|prompt|stem)"\s*:\s*"((?:\\.|[^"\\])*)"',fragment,re.I)
            bm=re.search(r'"(?:back|answer|definition|response)"\s*:\s*"((?:\\.|[^"\\])*)"',fragment,re.I)
            if fm and bm:
                try:
                    candidate=json.dumps({'front':json.loads('"'+fm.group(1)+'"'),'back':json.loads('"'+bm.group(1)+'"')},ensure_ascii=False)
                    if candidate not in seen:
                        seen.add(candidate); yield candidate
                except Exception: pass


def _normalize_options(opts):
    if isinstance(opts, list):
        normalized={}
        for i,item in enumerate(opts[:4]):
            key=chr(65+i)
            if isinstance(item,dict):
                rawkey=item.get('value',item.get('key',item.get('label',key)))
                match=re.search(r'[ABCD]',str(rawkey).upper())
                key=match.group(0) if match else key
                value=item.get('text',item.get('label',item.get('value','')))
            else: value=item
            if key in 'ABCD': normalized[key]=str(value).strip()
        return normalized
    if isinstance(opts, dict):
        normalized={}
        for k,v in opts.items():
            key=str(k).strip().upper().rstrip('.) ')
            if key in 'ABCD' and len(key)==1:
                if isinstance(v,dict): v=v.get('text',v.get('label',v.get('value','')))
                normalized[key]=str(v).strip()
        return normalized
    return {}


def _normalize_answer(q, options):
    raw=None
    for key in ('answer','correct_answer','correctAnswer','correct_option','correctOption','correct','correct_choice','correctChoice','answer_key','answerKey','key','correct_answer_letter','correctAnswerLetter'):
        if q.get(key) not in (None,''):
            raw=q.get(key); break
    if raw is None:
        for key in ('correct_index','correctIndex','answer_index','answerIndex','correctOptionIndex'):
            if q.get(key) is not None:
                try: raw=chr(65+int(q[key]))
                except Exception: pass
                break
    if isinstance(raw,dict): raw=raw.get('value',raw.get('label',raw.get('text',raw.get('option',''))))
    ans=str(raw or '').strip()
    m=re.match(r'(?i)^\s*(?:option\s*)?\(?([ABCD])\)?(?:[.)\s:\-]|$)',ans)
    if m: return m.group(1).upper()
    exact=[k for k,v in options.items() if ans.casefold()==v.casefold()]
    if len(exact)==1: return exact[0]
    m=re.search(r'(?i)\b(?:answer|option|correct)\s*(?:is|:)?\s*([ABCD])\b',ans)
    return m.group(1).upper() if m else ''


def _question_rows(data):
    if isinstance(data,list): return data
    if not isinstance(data,dict): return []
    for key in ('questions','mcqs','quiz','items','mcq','data'):
        value=data.get(key)
        if isinstance(value,list): return value
        if isinstance(value,dict): return list(value.values())
    if any(k in data for k in ('question','prompt','stem')): return [data]
    return []


def parse_quiz(content):
    """Normalize common and partially malformed LLM MCQ JSON into one schema."""
    if not isinstance(content,str): return []
    valid=[]; seen=set()
    for raw in _json_candidates(content):
        try: data=json.loads(raw)
        except Exception: continue
        for q in _question_rows(data):
            if not isinstance(q,dict): continue
            question=str(q.get('question') or q.get('prompt') or q.get('stem') or q.get('text') or '').strip()
            opts=_normalize_options(q.get('options',q.get('choices',q.get('answers',q.get('option')))))
            if not question or not all(k in opts and opts[k] for k in 'ABCD'): continue
            ans=_normalize_answer(q,opts)
            if ans not in 'ABCD': continue
            explanation=str(q.get('explanation',q.get('rationale',q.get('solution',q.get('feedback','Review the source material for the reasoning.'))))).strip()
            signature=(question,tuple(opts.items()))
            if signature not in seen:
                seen.add(signature); valid.append({'question':question,'options':{k:opts[k] for k in 'ABCD'},'answer':ans,'explanation':explanation or 'Review the relevant lecture section.'})
    if valid: return valid
    # Fallback for numbered Markdown MCQs.
    blocks=re.split(r'(?m)(?=^\s*(?:Q(?:uestion)?\s*)?\d+[.)])',content)
    for b in blocks:
        qm=re.search(r'(?:Q(?:uestion)?\s*)?\d+[.)]\s*(.+?)(?=\n|$)',b,re.I)
        opts={k:re.search(rf'(?m)^\s*{k}[.)]\s*(.+)$',b) for k in 'ABCD'}
        am=re.search(r'(?im)(?:correct answer|answer|correct option)\s*[:\-]?\s*([ABCD])',b)
        if qm and all(opts.values()) and am:
            valid.append({'question':qm.group(1).strip(),'options':{k:opts[k].group(1).strip() for k in 'ABCD'},'answer':am.group(1).upper(),'explanation':'Review the generated study notes for the explanation.'})
    return valid


def parse_flashcards(content):
    """Parse valid JSON, malformed JSON fragments, Markdown, and simple Q/A pairs."""
    if not isinstance(content,str): return []
    cards=[]; seen=set()
    for raw in _json_candidates(content):
        try: data=json.loads(raw)
        except Exception: continue
        if isinstance(data,list): rows=data
        elif isinstance(data,dict):
            rows=[]
            for key in ('flashcards','cards','items','data'):
                if isinstance(data.get(key),list): rows=data[key]; break
            if not rows and any(k in data for k in ('front','question','term','prompt')): rows=[data]
        else: rows=[]
        if isinstance(rows,dict): rows=list(rows.values())
        for row in rows if isinstance(rows,list) else []:
            if not isinstance(row,dict): continue
            lower={str(k).strip().lower().replace(' ','_'):v for k,v in row.items()}
            front=lower.get('front',lower.get('question',lower.get('term',lower.get('prompt',''))))
            back=lower.get('back',lower.get('answer',lower.get('definition',lower.get('response',''))))
            if isinstance(front,(dict,list)): front=json.dumps(front,ensure_ascii=False)
            if isinstance(back,(dict,list)): back=json.dumps(back,ensure_ascii=False)
            if str(front).strip() and str(back).strip():
                pair=(str(front).strip(),str(back).strip())
                if pair not in seen: seen.add(pair); cards.append(pair)
    if cards: return cards
    # Markdown cards and label pairs.
    blocks=re.split(r'(?im)(?=^\s*(?:#{1,4}\s*)?(?:card|flashcard)\s*#?\s*\d+)',content)
    for block in blocks:
        fm=re.search(r'(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:front|question|term):?(?:\*\*)?\s*[:\-]?\s*(.+)$',block)
        bm=re.search(r'(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:back|answer|definition):?(?:\*\*)?\s*[:\-]?\s*(.+)$',block)
        if fm and bm:
            pair=(fm.group(1).strip().strip('*'),bm.group(1).strip().strip('*'))
            if all(pair) and pair not in seen: seen.add(pair); cards.append(pair)
    if cards: return cards
    # Salvage flat JSON-like pairs even when the enclosing array/object is truncated.
    pattern=r'(?is)"(?:front|question|term|prompt)"\s*:\s*"((?:\\.|[^"\\])*)"\s*,\s*"(?:back|answer|definition|response)"\s*:\s*"((?:\\.|[^"\\])*)"'
    for m in re.finditer(pattern,content):
        try: pair=(json.loads('"'+m.group(1)+'"').strip(),json.loads('"'+m.group(2)+'"').strip())
        except Exception: continue
        if all(pair) and pair not in seen: seen.add(pair); cards.append(pair)
    return cards


def clean_study_output(content):
    """Hide machine-readable quiz/card payloads even when a model adds fences or prose."""
    if not isinstance(content,str): return str(content or '')
    cleaned=content
    def is_study_json(raw):
        low=raw.lower()
        return any(k in low for k in ('"flashcards"','"questions"','"mcqs"','"correct_answer"')) and (parse_quiz(raw) or parse_flashcards(raw) or '"flashcards"' in low or '"questions"' in low or '"mcqs"' in low)
    def replace_fence(match):
        body=match.group(1)
        return '\n' if is_study_json(body) else match.group(0)
    cleaned=re.sub(r'```(?:json|javascript|js)?\s*(.*?)\s*```',replace_fence,cleaned,flags=re.S|re.I)
    # Remove balanced JSON objects/arrays that carry quiz or flashcard payloads.
    decoder=json.JSONDecoder(); spans=[]
    for m in re.finditer(r'[\[{]',cleaned):
        try:
            obj,end=decoder.raw_decode(cleaned[m.start():])
            raw=cleaned[m.start():m.start()+end]
            if is_study_json(raw): spans.append((m.start(),m.start()+end))
        except Exception: continue
    for a,b in reversed(spans): cleaned=cleaned[:a]+cleaned[b:]
    # Remove a malformed/truncated JSON section beginning with a known top-level key.
    cleaned=re.sub(r'(?is)\{\s*"(?:flashcards|questions|mcqs)"\s*:\s*\[.*?(?=\n\s*#{1,3}\s|\Z)', '', cleaned)
    return re.sub(r'\n{3,}','\n\n',cleaned).strip()


def parse_mindmap(content):
    """Convert a Markdown outline into a nested tree for a visual mind map."""
    lines=[ln.rstrip() for ln in str(content or '').splitlines()]
    nodes=[]; stack=[]
    for line in lines:
        m=re.match(r'^(\s*)(?:[-*+]\s+|\d+[.)]\s+)(.+)$',line)
        if not m: continue
        depth=len(m.group(1).expandtabs(2))//2
        label=re.sub(r'[*`_]', '', m.group(2)).strip()
        if not label: continue
        node={'label':label,'children':[]}
        while stack and stack[-1][0]>=depth: stack.pop()
        if stack: stack[-1][1]['children'].append(node)
        else: nodes.append(node)
        stack.append((depth,node))
    title=re.search(r'(?im)^\s*(?:\*\*)?CENTRAL TOPIC\s*:\s*(.+?)(?:\*\*)?\s*$',str(content or ''))
    return (title.group(1).strip('* ') if title else 'Central topic'),nodes


def _mindmap_html(nodes):
    if not nodes: return ''
    items=[]
    for node in nodes:
        children=_mindmap_html(node['children'])
        items.append(f"<li><span class='mm-node'>{esc(node['label'])}</span>{children}</li>")
    return '<ul class="mm-branches">'+''.join(items)+'</ul>'


def render_flashcards(cards,pack_id):
    st.markdown('### 🗂️ Review flashcards')
    st.caption(f'{len(cards)} cards · Flip each card to reveal the answer.')
    key=f'flashcard_index_{pack_id}'; flipkey=f'flashcard_flip_{pack_id}'
    st.session_state.setdefault(key,0); st.session_state.setdefault(flipkey,False)
    idx=max(0,min(st.session_state[key],len(cards)-1)); front,back=cards[idx]
    label='ANSWER' if st.session_state[flipkey] else 'QUESTION'
    value=back if st.session_state[flipkey] else front
    st.markdown(f"<div class='panel' style='min-height:180px;display:flex;flex-direction:column;justify-content:center;text-align:center'><div class='eyebrow'>{label} · CARD {idx+1}/{len(cards)}</div><div style='font-size:1.25rem;font-weight:700;margin-top:16px;color:#f4f7ff'>{esc(value)}</div></div>",unsafe_allow_html=True)
    a,b,c=st.columns([1,1,1])
    with a:
        if st.button('← Previous',key=f'fc_prev_{pack_id}',disabled=idx==0,use_container_width=True): st.session_state[key]=idx-1; st.session_state[flipkey]=False; st.rerun()
    with b:
        if st.button('↻ Flip card',key=f'fc_flip_{pack_id}',type='primary',use_container_width=True): st.session_state[flipkey]=not st.session_state[flipkey]; st.rerun()
    with c:
        if st.button('Next →',key=f'fc_next_{pack_id}',disabled=idx>=len(cards)-1,use_container_width=True): st.session_state[key]=idx+1; st.session_state[flipkey]=False; st.rerun()
    st.progress((idx+1)/len(cards),text=f'Card {idx+1} of {len(cards)}')


def render_study_output(content, pack_id=None, title='Interactive quiz', outputs=None):
    qs=parse_quiz(content); cards=parse_flashcards(content)
    visible=clean_study_output(content)
    selected=outputs or []
    if visible: st.markdown(visible)
    if 'Mind Map' in selected:
        topic,nodes=parse_mindmap(content)
        if nodes:
            st.markdown('### 🧠 Visual mind map')
            st.markdown(f"<div class='mm-root'>{esc(topic)}</div>{_mindmap_html(nodes)}",unsafe_allow_html=True)
        else: st.info('Mind map outline was not detected. Regenerate Mind Map with a structured outline.')
    if cards:
        render_flashcards(cards,pack_id or 'unsaved')
    elif 'Flashcards' in selected:
        st.warning('The AI response did not contain readable front/back cards. The original response remains saved; try regenerating Flashcards.')
    if qs:
        st.markdown('### 🧠 Interactive quiz')
        st.caption(f'{len(qs)} questions · Answers stay hidden until you submit.')
        if pack_id:
            st.session_state.quiz_pack_id=pack_id
            render_interactive_quiz_pack(pack_id)
        else: st.info('Save this study pack to start its quiz.')
    elif 'MCQs' in selected:
        st.warning('The AI response did not contain a complete interactive quiz. The original response remains saved; regenerate MCQs or use Question Bank for extra practice.')

def render_interactive_quiz_pack(pack_id):
    """Render a saved structured quiz inline on whichever study page is active."""
    qp=query_one("SELECT * FROM study_packs WHERE id=?",(pack_id,)) if pack_id else None
    if not qp: return
    questions=parse_quiz(qp["content"])
    if not questions:
        st.warning("This saved quiz could not be parsed. Regenerate it from Study Workspace; the original content remains saved in your Library.")
        return
    if not questions: return
    st.markdown("### 🧠 Take the quiz")
    st.caption(f"Generated by {qp['provider']} · {qp['model']} — answers remain hidden until submission.")
    answered=len(st.session_state.quiz_answers); pct=int(answered/max(1,len(questions))*100)
    st.markdown(f"<div style='display:flex;justify-content:space-between;margin:14px 0 7px'><b>Progress</b><span>{answered}/{len(questions)} answered</span></div><div class='progress-track'><div class='progress-fill' style='width:{pct}%'></div></div>",unsafe_allow_html=True)
    with st.form(f"quiz_form_{qp['id']}"):
        answers={}
        for i,q in enumerate(questions):
            st.markdown(f"<div class='panel' style='margin:15px 0 8px;padding:16px'><div class='eyebrow'>QUESTION {i+1} OF {len(questions)}</div><div style='font-size:1.05rem;font-weight:700;color:#f0f4ff;margin-top:8px'>{esc(q['question'])}</div></div>",unsafe_allow_html=True)
            keys=list(q["options"].keys()); current=st.session_state.quiz_answers.get(str(i))
            answers[str(i)]=st.radio(f"Choose one answer · Q{i+1}",keys,format_func=lambda k,q=q:f"{k}. {q['options'][k]}",index=keys.index(current) if current in keys else None,key=f"quiz_{qp['id']}_{i}",label_visibility="collapsed",disabled=st.session_state.quiz_submitted)
        submit=st.form_submit_button("Submit answers & calculate score",type="primary",use_container_width=True,disabled=st.session_state.quiz_submitted)
    if submit:
        st.session_state.quiz_answers={k:v for k,v in answers.items() if v}; st.session_state.quiz_submitted=True; st.rerun()
    if st.session_state.quiz_submitted:
        answers=st.session_state.quiz_answers; correct=sum(1 for i,q in enumerate(questions) if answers.get(str(i))==q["answer"]); score=round(correct/max(1,len(questions))*100)
        st.markdown(f"<div class='hero' style='text-align:center'><div class='eyebrow'>QUIZ COMPLETE</div><div class='hero-title' style='font-size:2.5rem'>{score}%</div><div class='subtle'>{correct} correct out of {len(questions)} questions</div><div class='progress-track' style='margin:16px auto;max-width:440px'><div class='progress-fill' style='width:{score}%'></div></div></div>",unsafe_allow_html=True)
        for i,q in enumerate(questions):
            chosen_answer=answers.get(str(i)); iscorrect=chosen_answer==q["answer"]
            with st.expander(f"{'✅' if iscorrect else '❌'} Q{i+1}. {q['question']}",expanded=not iscorrect):
                st.markdown(f"**Your answer:** {chosen_answer or 'Not answered'} · **Correct answer:** {q['answer']}. {q['options'][q['answer']]}")
                st.markdown("**Explanation**  "+q.get("explanation","Review the relevant lecture section."))
        x,y=st.columns(2)
        with x:
            if st.button("↻ Try again",key=f"retry_inline_{qp['id']}",type="primary",use_container_width=True): st.session_state.quiz_answers={}; st.session_state.quiz_submitted=False; st.rerun()
        with y:
            if st.button("＋ New quiz",key=f"new_inline_{qp['id']}",use_container_width=True): st.session_state.quiz_pack_id=None; st.session_state.quiz_answers={}; st.session_state.quiz_submitted=False; st.rerun()


def new_chat(title="New study chat",lecture_id=None):
    cid=execute("INSERT INTO chats(title,lecture_id,created_at,updated_at) VALUES(?,?,?,?)",(title,lecture_id,NOW(),NOW()))
    st.session_state.chat_id=cid; return cid
def chat_messages(cid): return query_all("SELECT role,content,created_at,provider,model FROM messages WHERE chat_id=? ORDER BY id",(cid,))
def save_message(cid,role,content,provider=None,model=None):
    execute("INSERT INTO messages(chat_id,role,content,created_at,provider,model) VALUES(?,?,?,?,?,?)",(cid,role,content,NOW(),provider,model))
    if role=="user":
        first=query_one("SELECT content FROM messages WHERE chat_id=? AND role='user' ORDER BY id LIMIT 1",(cid,))
        if first: execute("UPDATE chats SET title=?,updated_at=? WHERE id=?",(first["content"][:48]+("…" if len(first["content"])>48 else ""),NOW(),cid))
    else: execute("UPDATE chats SET updated_at=? WHERE id=?",(NOW(),cid))

# -------------------- Session state --------------------
DEFAULTS={"page":"Home","current_lecture_id":None,"current_pack_id":None,"chat_id":None,"quiz_pack_id":None,"quiz_answers":{},"quiz_submitted":False,"focus_running":False,"focus_start":None,"focus_kind":"Study session","focus_lecture_id":None}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k]=v

# -------------------- Sidebar --------------------
NAV=["Home","Library","Saved Chats","Study Workspace","Question Bank","YouTube Learning","Analytics","Focus Mode","Achievements","Settings"]
ICONS={"Home":"⌂","Library":"▤","Saved Chats":"▣","Study Workspace":"✦","Question Bank":"☷","YouTube Learning":"▶","Analytics":"▥","Focus Mode":"◷","Achievements":"♛","Settings":"⚙"}
with st.sidebar:
    st.markdown("<div style='display:flex;gap:10px;align-items:center;padding:5px 0 12px'><div style='font-size:1.8rem'>🎓</div><div><div style='font-weight:800;font-size:1.12rem;color:#f5f7ff'>LectureGPT</div><div style='font-size:.75rem;color:#96a9c9'>Your AI study partner</div></div></div>",unsafe_allow_html=True)
    if AUTH_MODE != "local":
        _display_user = str(_claims.get("name") or _claims.get("email") or "Learner")
        st.caption("Signed in · " + _display_user[:48])
        if st.button("Log out", use_container_width=True):
            st.logout()
    if st.button("＋  New Chat",type="primary",use_container_width=True):
        new_chat(); st.session_state.page="Saved Chats"; st.rerun()
    current=st.session_state.page if st.session_state.page in NAV else "Home"
    st.session_state.page=st.radio("Navigation",NAV,index=NAV.index(current),format_func=lambda x:f"{ICONS[x]}   {x}",label_visibility="collapsed")
    st.markdown("<div style='height:1px;background:#1e2e49;margin:12px 0'></div><div class='divider-label'>Recent conversations</div>",unsafe_allow_html=True)
    recent=query_all("SELECT id,title,updated_at FROM chats ORDER BY updated_at DESC LIMIT 5")
    if recent:
        for c in recent:
            if st.button("▣  "+c["title"][:27],key=f"sidechat_{c['id']}",use_container_width=True):
                st.session_state.chat_id=c["id"]; st.session_state.page="Saved Chats"; st.rerun()
    else: st.caption("Your saved chats will appear here.")
    st.markdown("<div style='height:1px;background:#1e2e49;margin:12px 0'></div>",unsafe_allow_html=True)
    today=date.today().isoformat(); seconds=total_study_seconds(today); goalrow=query_one("SELECT goal_minutes FROM daily_goals WHERE day=?",(today,)); goal=int(goalrow["goal_minutes"] if goalrow else 120)
    pct=min(100,int(seconds/max(1,goal*60)*100))
    st.markdown(f"<div class='panel' style='padding:14px'><div style='font-weight:800'>◷  Today's study</div><div style='font-size:1.5rem;font-weight:800;margin:6px 0'>{fmt_time(seconds)}</div><div class='progress-track'><div class='progress-fill' style='width:{pct}%'></div></div><div class='small-muted' style='margin-top:7px'>{pct}% of {goal}-minute goal</div></div>",unsafe_allow_html=True)
    st.markdown("<div style='padding:13px 2px 2px;color:#7f91b0;font-size:.72rem'>Local SQLite · Groq · NVIDIA · OpenRouter · Gemini</div>",unsafe_allow_html=True)

# -------------------- Shared helpers --------------------
def heading(eyebrow,title,subtitle=""):
    st.markdown(f"<div class='eyebrow'>{esc(eyebrow)}</div><div class='hero-title' style='font-size:2rem;margin-top:5px'>{title}</div><div class='subtle'>{esc(subtitle)}</div>",unsafe_allow_html=True)
def get_lecture(lecture_id): return query_one("SELECT * FROM lectures WHERE id=?",(lecture_id,)) if lecture_id else None
def save_uploaded_lecture(uploaded,title_override=""):
    raw=uploaded.getvalue(); sha=hashlib.sha256(raw).hexdigest(); old=query_one("SELECT id,title FROM lectures WHERE file_hash=?",(sha,))
    if old: return old["id"],old["title"],False
    _,_,units=extract_source(uploaded.name,uploaded.type or "",raw); title=title_override.strip() or Path(uploaded.name).stem
    lid=execute("INSERT INTO lectures(title,file_name,file_type,file_data,file_hash,created_at) VALUES(?,?,?,?,?,?)",(title,uploaded.name,uploaded.type or mimetypes.guess_type(uploaded.name)[0] or "application/octet-stream",raw,sha,NOW()))
    save_progress(lid,0,0,units)
    return lid,title,True
def study_minutes_by_day(days=7):
    rows=query_all("SELECT substr(started_at,1,10) day, SUM(seconds) seconds FROM study_sessions WHERE started_at>=? GROUP BY substr(started_at,1,10)",(date.today().replace(day=max(1,date.today().day-days+1)).isoformat(),))
    return {r["day"]:int(r["seconds"] or 0) for r in rows}

# -------------------- Home --------------------
if st.session_state.page=="Home":
    user_name=setting_value('user_name','Raj')
    st.markdown(f"<div class='hero'><div class='eyebrow'>✦ YOUR PERSONAL AI STUDY WORKSPACE</div><div class='hero-title'>Good to see you, {esc(user_name)} 👋<br><span>Make every study session count.</span></div><div class='subtle'>Upload a lecture, continue where you left off, and track your learning progress — automatically saved on this computer.</div></div>",unsafe_allow_html=True)
    qcol,btncol=st.columns([5,1])
    with qcol: quickq=st.text_input("Ask about your lectures",placeholder="Ask anything about your saved lectures…",label_visibility="collapsed",key="home_question")
    with btncol:
        if st.button("Ask AI ↗",type="primary",use_container_width=True):
            if quickq.strip():
                cid=st.session_state.chat_id or new_chat(quickq[:48],st.session_state.current_lecture_id); save_message(cid,"user",quickq.strip()); st.session_state.pending_chat_answer=True; st.session_state.page="Saved Chats"; st.rerun()
    cols=st.columns(4)
    tiles=[("📤","Upload lecture","PDF, TXT, MD or CSV · auto-saved","Study Workspace"),("▶️","YouTube learning","Fetch captions and track watch progress","YouTube Learning"),("🧠","Question bank","Practice questions and exam prep","Question Bank"),("💬","Ask anything","Chat with your saved lecture library","Saved Chats")]
    for col,(ic,title,copy,page) in zip(cols,tiles):
        with col:
            st.markdown(f"<div class='tile'><div class='tile-icon'>{ic}</div><div class='tile-title'>{title}</div><div class='tile-copy'>{copy}</div></div>",unsafe_allow_html=True)
            if st.button("Open →",key="tile_"+page,use_container_width=True): st.session_state.page=page; st.rerun()
    today=date.today().isoformat(); seconds=total_study_seconds(today); goalrow=query_one("SELECT goal_minutes FROM daily_goals WHERE day=?",(today,)); goal=int(goalrow["goal_minutes"] if goalrow else 120)
    n_lectures=query_one("SELECT COUNT(*) n FROM lectures")["n"]; avg=query_one("SELECT AVG(progress) n FROM study_progress")["n"] or 0; active=query_one("SELECT COUNT(*) n FROM chats")["n"]
    st.markdown("### Your study pulse")
    a,b,c,d=st.columns(4)
    a.metric("Study time today",fmt_time(seconds)); b.metric("Daily goal",f"{min(100,int(seconds/max(1,goal*60)*100))}%",f"{goal} min target"); c.metric("Saved lectures",n_lectures); d.metric("Avg. completion",f"{int(avg)}%",f"{active} saved chats")
    left,right=st.columns([1.15,.85],gap="large")
    with left:
        st.markdown("<div class='panel'><div class='panel-title'>📚 Continue learning</div><div class='small-muted'>Pick up where you left off.</div>",unsafe_allow_html=True)
        lectures=query_all("SELECT l.id,l.title,l.file_name,l.created_at,COALESCE(p.progress,0) progress FROM lectures l LEFT JOIN study_progress p ON p.lecture_id=l.id ORDER BY COALESCE(p.updated_at,l.created_at) DESC LIMIT 6")
        if not lectures: st.info("Upload a lecture to see your progress here.")
        for lec in lectures:
            p=int(lec["progress"]); st.markdown(f"<div style='padding:13px 0;border-bottom:1px solid #1c2b43'><div style='display:flex;justify-content:space-between;gap:10px'><b>{esc(lec['title'])}</b><span class='pill'>{p}%</span></div><div class='progress-track' style='margin:9px 0'><div class='progress-fill' style='width:{p}%'></div></div><div class='small-muted'>{esc(lec['file_name'])}</div></div>",unsafe_allow_html=True)
            if st.button("Continue",key=f"continue_{lec['id']}"):
                st.session_state.current_lecture_id=lec["id"]; st.session_state.page="Study Workspace"; st.rerun()
        st.markdown("</div>",unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'><div class='panel-title'>🎯 Weekly consistency</div><div class='small-muted'>Your study time, saved locally on this device.</div>",unsafe_allow_html=True)
        daily=[]
        for i in range(6,-1,-1):
            day=(date.today()).fromordinal(date.today().toordinal()-i); sec=total_study_seconds(day.isoformat()); daily.append((day.strftime("%a"),sec//60))
        maxm=max([x[1] for x in daily]+[1]); bars="".join(f"<div style='flex:1;text-align:center'><div style='height:95px;display:flex;align-items:end;justify-content:center'><div title='{m} minutes' style='width:22px;height:{max(5,int(m/maxm*95))}px;border-radius:7px 7px 3px 3px;background:linear-gradient(180deg,#24d1dc,#7650ff)'></div></div><div class='small-muted' style='font-size:.72rem;margin-top:7px'>{day}</div></div>" for day,m in daily)
        st.markdown(f"<div style='display:flex;gap:9px;align-items:end;margin:22px 0 10px'>{bars}</div><div class='small-muted'>Small consistent sessions beat occasional all-nighters. Set a realistic daily target in Analytics.</div></div>",unsafe_allow_html=True)
        st.markdown("<div class='panel' style='margin-top:14px'><div class='panel-title'>⚡ Quick revision tools</div><div class='small-muted'>Create focused study material from a saved lecture.</div></div>",unsafe_allow_html=True)
        toolcols=st.columns(2)
        for col,label,page in [(toolcols[0],"Generate notes","Study Workspace"),(toolcols[1],"Practice MCQs","Question Bank")]:
            with col:
                if st.button(label,key="quick_"+label,use_container_width=True): st.session_state.page=page; st.rerun()

# -------------------- Study Workspace / upload + generate --------------------
elif st.session_state.page=="Study Workspace":
    heading("LECTURE WORKSPACE","Upload once. Learn your way.","Your source is automatically saved to the library as soon as it is validated.")
    up_tab,existing_tab=st.tabs(["＋ Upload a lecture","📚 Use saved lecture"])
    with up_tab:
        title_override=st.text_input("Lecture title (optional)",placeholder="e.g. Data Structures — Unit 1",key="upload_title")
        up=st.file_uploader("Drop a lecture PDF or text document",type=["pdf","txt","md","csv"],key="source_upload")
        if up:
            try:
                lid,title,created=save_uploaded_lecture(up,title_override)
                st.session_state.current_lecture_id=lid
                st.success(("Automatically saved" if created else "Already in your library")+f": {title}")
            except Exception as e: st.error(str(e))
    with existing_tab:
        lectures=query_all("SELECT id,title,file_name,created_at FROM lectures ORDER BY id DESC")
        if lectures:
            opts={f"{r['title']} · {r['file_name']}":r["id"] for r in lectures}; labels=list(opts)
            default=next((i for i,l in enumerate(labels) if opts[l]==st.session_state.current_lecture_id),0)
            chosen=st.selectbox("Choose from your library",labels,index=default)
            if st.button("Open selected lecture",type="primary"): st.session_state.current_lecture_id=opts[chosen]; st.rerun()
        else: st.info("Your library is empty. Upload a lecture first.")
    lec=get_lecture(st.session_state.current_lecture_id)
    if lec:
        st.markdown(f"<div class='panel'><div class='panel-title'>📖 {esc(lec['title'])}</div><div class='small-muted'>{esc(lec['file_name'])} · Auto-saved in your library</div></div>",unsafe_allow_html=True)
        tabs=st.tabs(["Generate material","Read & track progress","Ask this lecture"])
        with tabs[0]:
            outs=st.multiselect("What should LectureGPT create?",["AI Summary","Study Notes","MCQs","Flashcards","Mind Map","Question Bank","Revision Sheet"],default=["AI Summary","Study Notes","MCQs"])
            a,b,c=st.columns(3)
            with a: lang=st.selectbox("Language",["English","Hindi","Hinglish"]); summ=st.selectbox("Summary detail",["Short","Medium","Detailed"],index=1)
            with b: style=st.selectbox("Notes style",["Concept-wise","Exam-focused","Bullet points","Detailed with examples"]); diff=st.selectbox("Question difficulty",["Easy","Medium","Hard"],index=1)
            with c: count=st.selectbox("MCQ count",[5,10,15,20,30],index=1); pref=st.selectbox("Preferred AI",list(provider_config()))
            instr=st.text_area("Extra instructions (optional)",placeholder="Focus on definitions, formulas and likely exam questions…",height=80)
            if st.button("✨ Generate study material",type="primary",use_container_width=True):
                if not outs: st.warning("Choose at least one output type.")
                else:
                    try:
                        source,_,_=extract_source(lec["file_name"],lec["file_type"],lec["file_data"])
                        if len(source)>42000: source=source[:42000]+"\n[Source shortened to fit model context.]"
                        prompt=make_prompt(outs,lang,summ,style,diff,count,instr)
                        with st.spinner("Creating your study pack…"):
                            answer,provider,model,errors=run_router(prompt,source,pref)
                        pid=execute("INSERT INTO study_packs(lecture_id,title,provider,model,outputs,language,content,created_at) VALUES(?,?,?,?,?,?,?,?)",(lec["id"],f"{lec['title']} — {', '.join(outs)}",provider,model,json.dumps(outs),lang,answer,NOW()))
                        st.session_state.current_pack_id=pid
                        if "MCQs" in outs:
                            # Keep the quiz attached to this generated pack. Combined notes+quiz
                            # must be playable directly below the notes, without Question Bank.
                            st.session_state.quiz_pack_id=pid
                            st.session_state.quiz_answers={}; st.session_state.quiz_submitted=False
                        st.success(f"Saved to Library · {provider} / {model}")
                        if errors:
                            st.info(f"LectureGPT successfully generated your material using {provider}. One or more backup providers were unavailable; this did not affect the saved result.")
                            with st.expander("Provider fallback details"): st.write("\n".join(errors))
                    except Exception as e: st.error(str(e))
            # Persistently show the latest generated material after reruns, including quiz submissions.
            active_pack=query_one("SELECT * FROM study_packs WHERE id=? AND lecture_id=?",(st.session_state.current_pack_id,lec["id"])) if st.session_state.current_pack_id else None
            if active_pack:
                st.divider(); st.markdown("## Your generated study material")
                ai_attribution(active_pack["provider"],active_pack["model"])
                try: active_outputs=json.loads(active_pack["outputs"])
                except Exception: active_outputs=[]
                quiz_only=(active_outputs == ["MCQs"] or active_outputs == ["Interactive Quiz"])
                if quiz_only:
                    render_interactive_quiz_pack(active_pack["id"])
                else:
                    render_study_output(active_pack["content"],active_pack["id"],f"{lec['title']} quiz",active_outputs)
                st.download_button("⬇ Download study pack",clean_study_output(active_pack["content"]),file_name=f"lecturegpt_pack_{active_pack['id']}.md",mime="text/markdown",key=f"download_pack_{active_pack['id']}")

        with tabs[1]:
            try:
                source,info,units=extract_source(lec["file_name"],lec["file_type"],lec["file_data"])
                saved=query_one("SELECT * FROM study_progress WHERE lecture_id=?",(lec["id"],)); current=int(saved["position"] if saved else 0); pct=int(saved["progress"] if saved else 0)
                st.markdown(f"**Reading progress · {pct}%**")
                st.markdown(f"<div class='progress-track'><div class='progress-fill' style='width:{pct}%'></div></div><div class='small-muted' style='margin-top:6px'>{info} · Adjust the position as you read. Progress is saved automatically.</div>",unsafe_allow_html=True)
                pos=st.slider("Reading position",0,units,min(current,units),key=f"readpos_{lec['id']}")
                if pos!=current:
                    save_progress(lec["id"],round(pos/units*100,1),pos,units)
                    st.rerun()
                chunk_size=max(1,len(source)//units); start=max(0,min(len(source)-1,int((pos/units)*len(source))))
                if pos>=units: start=max(0,len(source)-chunk_size)
                snippet=source[start:start+max(1200,chunk_size+3000)]
                st.text_area("Lecture text",snippet,height=340,key=f"snippet_{lec['id']}_{pos}",help="Text preview for studying. For PDFs, the slider approximates reading position across pages.")
                if st.button("Mark lecture completed",type="primary"): save_progress(lec["id"],100,units,units); st.success("Lecture marked complete."); st.rerun()
            except Exception as e: st.error(str(e))
        with tabs[2]:
            st.caption("Questions are answered using the selected lecture as context.")
            question=st.text_area("Ask a question",placeholder="Explain this concept with an example…",height=90,key="lecture_question")
            pref2=st.selectbox("Preferred AI provider",list(provider_config()),index=list(provider_config()).index(st.session_state.get("lecture_chat_provider","Groq")) if st.session_state.get("lecture_chat_provider","Groq") in provider_config() else 0,key="lecture_chat_provider")
            if st.button("Ask about this lecture",type="primary"):
                if question.strip():
                    try:
                        source,_,_=extract_source(lec["file_name"],lec["file_type"],lec["file_data"])
                        answer,provider,model,errs=run_router("Answer the student's question clearly and pedagogically, with examples when helpful. If the source does not contain the answer, say so.\nQUESTION: "+question,source[:42000],pref2)
                        cid=st.session_state.chat_id or new_chat(question[:45],lec["id"]); save_message(cid,"user",question); save_message(cid,"assistant",answer,provider,model); st.session_state.chat_id=cid
                        st.markdown(answer); ai_attribution(provider,model)
                    except Exception as e: st.error(str(e))

# -------------------- YouTube learning --------------------
elif st.session_state.page=="YouTube Learning":
    heading("VIDEO LEARNING","Turn videos into active study sessions.","Add a captioned YouTube video once. Track your watch progress and save notes alongside it.")
    st.selectbox("Caption language preference",["Auto (English, then Hindi)","Hindi first","English first"],key="caption_language")
    url=st.text_input("YouTube video URL",placeholder="https://www.youtube.com/watch?v=…",key="youtube_url")
    yt_title=st.text_input("Video title (optional)",placeholder="e.g. Binary Search — Full Explanation")
    if st.button("Fetch captions & save video",type="primary",use_container_width=True):
        try:
            with st.spinner("Fetching available captions…"):
                transcript,vid,caption_language=youtube_transcript(url, st.session_state.get("caption_language", "Auto"))
            sha=hashlib.sha256(("youtube:"+vid).encode()).hexdigest(); old=query_one("SELECT id,title FROM lectures WHERE file_hash=?",(sha,))
            if old: lid=old["id"]; st.info("This video is already saved in your library.")
            else:
                title=yt_title.strip() or f"YouTube lecture {vid}"
                lid=execute("INSERT INTO lectures(title,file_name,file_type,file_data,file_hash,created_at) VALUES(?,?,?,?,?,?)",(title,f"youtube_{vid}.txt","text/youtube",transcript.encode(),sha,NOW()))
                save_progress(lid,0,0,100); st.success(f"Video transcript saved automatically to your library · Captions: {caption_language}")
            st.session_state.current_lecture_id=lid; st.session_state.youtube_saved_url=url; st.session_state.youtube_caption_language=caption_language; st.rerun()
        except Exception as e:
            st.error(str(e))
            st.warning("YouTube may block caption requests from cloud-hosting IP addresses. This is an upstream restriction, not something LectureGPT can reliably fix. Paste a transcript below instead.")
    st.markdown("#### Caption fallback · paste transcript")
    st.caption("If automatic captions are blocked, copy the transcript from YouTube and paste it here. This avoids depending on the Streamlit server's IP.")
    pasted_transcript = st.text_area("Paste video transcript", height=170, placeholder="Paste the lecture transcript here…", key="youtube_manual_transcript")
    if st.button("Save pasted transcript to my library", use_container_width=True):
        if not pasted_transcript.strip():
            st.warning("Paste a transcript first.")
        else:
            vid = youtube_id(url)
            transcript_text = pasted_transcript.strip()
            transcript_hash = hashlib.sha256(transcript_text.encode("utf-8")).hexdigest()
            file_hash = hashlib.sha256(("youtube-manual:" + (vid or "") + ":" + transcript_hash).encode()).hexdigest()
            old = query_one("SELECT id,title FROM lectures WHERE file_hash=?", (file_hash,))
            if old:
                lid = old["id"]
                st.info("This transcript is already saved in your private library.")
            else:
                title = yt_title.strip() or (f"YouTube lecture {vid}" if vid else "Pasted lecture transcript")
                file_name = f"youtube_{vid}.txt" if vid else f"transcript_{transcript_hash[:12]}.txt"
                lid = execute("INSERT INTO lectures(title,file_name,file_type,file_data,file_hash,created_at) VALUES(?,?,?,?,?,?)",
                              (title, file_name, "text/plain", transcript_text.encode("utf-8"), file_hash, NOW()))
                save_progress(lid, 0, 0, 100)
                st.success("Transcript saved to your private library.")
            st.session_state.current_lecture_id = lid
            st.rerun()
    lec=get_lecture(st.session_state.current_lecture_id)
    if lec and lec["file_name"].startswith("youtube_"):
        vid=lec["file_name"][8:-4]
        st.markdown(f"<div class='panel'><div class='panel-title'>▶️ {esc(lec['title'])}</div><div class='small-muted'>Transcript available · automatically saved</div></div>",unsafe_allow_html=True)
        st.components.v1.iframe(f"https://www.youtube-nocookie.com/embed/{vid}",height=380,scrolling=False)
        saved=query_one("SELECT * FROM study_progress WHERE lecture_id=?",(lec["id"],)); pct=int(saved["progress"] if saved else 0)
        newpct=st.slider("How much of this video have you watched?",0,100,pct,key=f"ytprogress_{lec['id']}")
        if newpct!=pct:
            save_progress(lec["id"],newpct,newpct,100)
            st.rerun()
        st.markdown(f"<div class='progress-track'><div class='progress-fill' style='width:{newpct}%'></div></div><div class='small-muted' style='margin-top:6px'>{newpct}% watched · update this as you watch. Playback progress is not read automatically from the embedded player.</div>",unsafe_allow_html=True)
        if st.button("Generate notes & MCQs from transcript",type="primary"):
            try:
                transcript=lec["file_data"].decode("utf-8",errors="replace")[:42000]
                prompt=make_prompt(["AI Summary","Study Notes","MCQs"],"English","Medium","Exam-focused","Medium",10,"")
                with st.spinner("Generating video study pack…"): answer,provider,model,errs=run_router(prompt,transcript,"Groq")
                pid=execute("INSERT INTO study_packs(lecture_id,title,provider,model,outputs,language,content,created_at) VALUES(?,?,?,?,?,?,?,?)",(lec["id"],lec["title"]+" — Video notes & MCQs",provider,model,json.dumps(["AI Summary","Study Notes","MCQs"]),"English",answer,NOW()))
                st.session_state.current_pack_id=pid; st.success("Saved study pack to library."); ai_attribution(provider,model); render_study_output(answer,pid,f"{lec['title']} video quiz",["AI Summary","Study Notes","MCQs"])
            except Exception as e: st.error(str(e))

# -------------------- Saved chats --------------------
elif st.session_state.page=="Saved Chats":
    heading("YOUR CONVERSATIONS","Saved chats","Every message is saved automatically. Open any chat and continue right where you stopped.")
    left,right=st.columns([.85,1.6],gap="large")
    with left:
        if st.button("＋ Start a new chat",type="primary",use_container_width=True): new_chat(); st.rerun()
        chats=query_all("SELECT c.id,c.title,c.updated_at,COUNT(m.id) n FROM chats c LEFT JOIN messages m ON m.chat_id=c.id GROUP BY c.id ORDER BY c.updated_at DESC")
        if not chats: st.info("No saved chats yet. Start a chat from the button above.")
        for c in chats:
            st.markdown(f"<div class='panel' style='padding:12px;margin:7px 0'><div class='card-title'>{esc(c['title'])}</div><div class='small-muted'>{c['n']} messages · {esc(c['updated_at'])}</div></div>",unsafe_allow_html=True)
            x,y=st.columns([3,1])
            with x:
                if st.button("Open chat",key=f"openchat_{c['id']}",use_container_width=True): st.session_state.chat_id=c["id"]; st.rerun()
            with y:
                if st.button("✕",key=f"deletechat_{c['id']}",help="Delete chat"): execute("DELETE FROM messages WHERE chat_id=?",(c["id"],)); execute("DELETE FROM chats WHERE id=?",(c["id"],)); st.rerun()
    with right:
        cid=st.session_state.chat_id
        if cid and query_one("SELECT id FROM chats WHERE id=?",(cid,)):
            ch=query_one("SELECT * FROM chats WHERE id=?",(cid,)); st.markdown(f"<div class='panel'><div class='panel-title'>💬 {esc(ch['title'])}</div><div class='small-muted'>Auto-saved conversation</div></div>",unsafe_allow_html=True)
            if st.session_state.get("pending_chat_answer"):
                try:
                    last_user=query_one("SELECT content FROM messages WHERE chat_id=? AND role='user' ORDER BY id DESC LIMIT 1",(cid,))
                    source=""
                    linked=get_lecture(ch["lecture_id"])
                    if linked: source=extract_source(linked["file_name"],linked["file_type"],linked["file_data"])[0][:35000]
                    with st.spinner("Preparing your answer…"):
                        answer,provider,model,errs=run_router("Answer the latest user question as a clear, supportive academic tutor.\nQUESTION: "+(last_user["content"] if last_user else ""),source,"Groq")
                    save_message(cid,"assistant",answer,provider,model)
                except Exception as e:
                    save_message(cid,"assistant",f"I couldn't reach the configured AI providers. {e}")
                st.session_state.pending_chat_answer=False
                st.rerun()
            for m in chat_messages(cid):
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
                    if m["role"]=="assistant" and m["provider"]: ai_attribution(m["provider"],m["model"] or "")
            with st.form("chat_form",clear_on_submit=True):
                msg=st.text_area("Message",placeholder="Ask a question or request an explanation…",height=85,label_visibility="collapsed")
                send=st.form_submit_button("Send message ↗",type="primary",use_container_width=True)
            if send and msg.strip():
                save_message(cid,"user",msg.strip()); chlec=get_lecture(ch["lecture_id"])
                source=""
                if chlec:
                    try: source=extract_source(chlec["file_name"],chlec["file_type"],chlec["file_data"])[0][:35000]
                    except Exception: source=""
                context="\n\nLECTURE SOURCE:\n"+source if source else "\nNo specific lecture source is attached. Answer general academic questions accurately."
                history=chat_messages(cid)[-12:]
                prompt="Continue this tutoring conversation. Be clear and helpful. Use the attached lecture source if present.\n\nConversation:\n"+"\n".join(f"{m['role']}: {m['content']}" for m in history)+"\n\nRespond to the latest user message."
                try:
                    with st.spinner("Thinking…"): answer,provider,model,errs=run_router(prompt,context,"Groq")
                    save_message(cid,"assistant",answer,provider,model); st.rerun()
                except Exception as e: save_message(cid,"assistant",f"I couldn't reach the configured AI providers. {e}"); st.rerun()
        else: st.info("Select a saved conversation on the left, or start a new one. Chats stay on this computer.")

# -------------------- Question bank / interactive quiz --------------------
elif st.session_state.page=="Question Bank":
    heading("PRACTICE & TEST","Question bank","Generate a quiz from a lecture, answer without seeing the key, and get a score when you submit.")
    lectures=query_all("SELECT id,title FROM lectures ORDER BY id DESC")
    if not lectures: st.info("Upload a PDF/text lecture or add a captioned YouTube lecture first.")
    else:
        opts={r["title"]:r["id"] for r in lectures}; chosen=st.selectbox("Choose a source",list(opts),key="qb_source"); lec=get_lecture(opts[chosen])
        col1,col2=st.columns([1,1]);
        with col1: n=st.select_slider("Number of questions",options=[5,10,15,20],value=10)
        with col2: diff=st.selectbox("Difficulty",["Easy","Medium","Hard"],index=1,key="qb_diff")
        packs=query_all("SELECT id,title,content,created_at FROM study_packs WHERE lecture_id=? AND (outputs LIKE '%MCQs%' OR title LIKE '%MCQ%' OR title LIKE '%Question Bank%') ORDER BY id DESC",(lec["id"],))
        if packs:
            st.markdown("#### Saved quizzes")
            for p in packs:
                a,b=st.columns([4,1])
                with a: st.markdown(f"**{esc(p['title'])}** <span class='small-muted'>· {esc(p['created_at'])}</span>",unsafe_allow_html=True)
                with b:
                    if st.button("Take quiz",key=f"takequiz_{p['id']}",use_container_width=True): st.session_state.quiz_pack_id=p["id"]; st.session_state.quiz_answers={}; st.session_state.quiz_submitted=False; st.rerun()
        if st.button("✨ Generate a fresh interactive quiz",type="primary",use_container_width=True):
            try:
                source,_,_=extract_source(lec["file_name"],lec["file_type"],lec["file_data"]); prompt=f"Generate exactly {n} objective multiple-choice questions at {diff} difficulty based only on source. Return ONLY valid JSON, no markdown, with schema {{\"questions\":[{{\"question\":\"...\",\"options\":{{\"A\":\"...\",\"B\":\"...\",\"C\":\"...\",\"D\":\"...\"}},\"answer\":\"A\",\"explanation\":\"...\"}}]}}. Each question must have exactly one correct answer and four plausible options. Keep all answers/explanations in JSON fields, never inside question or option text."
                with st.spinner("Building your quiz…"): answer,provider,model,errs=run_router(prompt,source[:42000],"Groq")
                qs=parse_quiz(answer)
                if not qs: st.error("The model did not return a valid structured quiz. Please retry or switch provider.")
                else:
                    payload=json.dumps({"questions":qs},ensure_ascii=False)
                    pid=execute("INSERT INTO study_packs(lecture_id,title,provider,model,outputs,language,content,created_at) VALUES(?,?,?,?,?,?,?,?)",(lec["id"],f"{lec['title']} — Interactive Quiz ({len(qs)} questions)",provider,model,json.dumps(["MCQs","Interactive Quiz"]),"English",payload,NOW()))
                    st.session_state.quiz_pack_id=pid; st.session_state.quiz_answers={}; st.session_state.quiz_submitted=False; st.success(f"Quiz created · {len(qs)} questions · answers locked until submit."); st.session_state.last_quiz_ai=f"{provider} · {model}"; st.rerun()
            except Exception as e:
                st.error(str(e))
        if st.session_state.quiz_pack_id:
            render_interactive_quiz_pack(st.session_state.quiz_pack_id)

# -------------------- Analytics / digital wellbeing --------------------
elif st.session_state.page=="Analytics":
    heading("DIGITAL WELLBEING","Study with awareness, not burnout.","Track focused study time, daily goals and how far you have progressed through every saved lecture.")
    today=date.today().isoformat(); existing=query_one("SELECT * FROM daily_goals WHERE day=?",(today,)); goal=int(existing["goal_minutes"] if existing else 120); done=total_study_seconds(today); pct=min(100,int(done/max(1,goal*60)*100))
    c1,c2,c3=st.columns(3); c1.metric("Today's focused time",fmt_time(done)); c2.metric("Daily target",f"{goal} min"); c3.metric("Goal completion",f"{pct}%")
    st.markdown("### Daily goal")
    newgoal=st.slider("Minutes of focused study per day",15,600,goal,step=15)
    if st.button("Save daily goal",type="primary"): execute("INSERT INTO daily_goals(day,goal_minutes) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET goal_minutes=excluded.goal_minutes",(today,newgoal)); st.success("Daily goal saved."); st.rerun()
    st.markdown("### Study time this week")
    vals=[]
    for i in range(6,-1,-1):
        day=date.fromordinal(date.today().toordinal()-i); vals.append({"Day":day.strftime("%a %d"),"Minutes":total_study_seconds(day.isoformat())//60})
    st.bar_chart(vals,x="Day",y="Minutes",use_container_width=True)
    st.markdown("### Learning progress by source")
    rows=query_all("SELECT l.id,l.title,l.file_name,COALESCE(p.progress,0) progress,p.updated_at FROM lectures l LEFT JOIN study_progress p ON p.lecture_id=l.id ORDER BY p.updated_at DESC")
    if not rows: st.info("Add a lecture or YouTube video to begin tracking progress.")
    for r in rows:
        pct=int(r["progress"]); st.markdown(f"**{esc(r['title'])}** <span class='small-muted'>· {pct}%</span>",unsafe_allow_html=True)
        st.markdown(f"<div class='progress-track' style='margin:7px 0 12px'><div class='progress-fill' style='width:{pct}%'></div></div>",unsafe_allow_html=True)
    st.markdown("### Recent focus sessions")
    sessions=query_all("SELECT started_at,seconds,kind FROM study_sessions ORDER BY id DESC LIMIT 10")
    if sessions: st.dataframe([{"Started":s["started_at"],"Duration":fmt_time(s["seconds"]),"Mode":s["kind"]} for s in sessions],hide_index=True,use_container_width=True)
    else: st.caption("Your completed focus sessions will show here.")
    st.info("Study time counts completed focus-timer sessions, not passive time with the app open. YouTube playback progress is manually updated because browser embeds do not expose reliable watch progress to Streamlit.")

# -------------------- Focus mode --------------------
elif st.session_state.page=="Focus Mode":
    heading("FOCUS MODE","One session. One goal.","Use a focused timer, keep distractions low, and save completed study time to your wellbeing dashboard.")
    a,b=st.columns([1,1],gap="large")
    with a:
        st.markdown("<div class='panel'><div class='panel-title'>◷ Focus timer</div><div class='small-muted'>Start a session and stop it when you're done. Only completed sessions count toward study time.</div>",unsafe_allow_html=True)
        kind=st.selectbox("Session type",["Pomodoro · 25 min","Deep work · 50 min","Custom session"])
        mins=st.slider("Custom duration (minutes)",5,180,30,step=5,disabled=kind!="Custom session")
        lects=query_all("SELECT id,title FROM lectures ORDER BY id DESC"); lop={"General study session":None}; lop.update({r["title"]:r["id"] for r in lects}); ltitle=st.selectbox("What are you studying?",list(lop))
        duration=25 if kind.startswith("Pomodoro") else 50 if kind.startswith("Deep") else mins
        if not st.session_state.focus_running:
            if st.button("▶ Start focus session",type="primary",use_container_width=True): st.session_state.focus_running=True; st.session_state.focus_start=time.time(); st.session_state.focus_duration=duration*60; st.session_state.focus_kind=kind; st.session_state.focus_lecture_id=lop[ltitle]; st.rerun()
        else:
            elapsed=int(time.time()-st.session_state.focus_start); remain=max(0,int(st.session_state.focus_duration)-elapsed)
            st.markdown(f"<div style='text-align:center;padding:25px 5px'><div class='eyebrow'>FOCUS IN PROGRESS</div><div style='font-size:3.5rem;font-weight:800;color:#f6f7ff;font-family:Plus Jakarta Sans'>{remain//60:02d}:{remain%60:02d}</div><div class='progress-track'><div class='progress-fill' style='width:{min(100,elapsed/max(1,st.session_state.focus_duration)*100)}%'></div></div><div class='small-muted' style='margin-top:8px'>Keep this tab open. Timer updates when the page refreshes.</div></div>",unsafe_allow_html=True)
            if st.button("✓ Complete session",type="primary",use_container_width=True):
                seconds=min(int(st.session_state.focus_duration),max(60,elapsed)); execute("INSERT INTO study_sessions(started_at,ended_at,seconds,kind,lecture_id) VALUES(?,?,?,?,?)",(datetime.fromtimestamp(st.session_state.focus_start).strftime("%Y-%m-%d %H:%M:%S"),NOW(),seconds,st.session_state.focus_kind,st.session_state.focus_lecture_id))
                st.session_state.focus_running=False; st.session_state.focus_start=None; st.success(f"Nice work — {fmt_time(seconds)} added to your study time."); st.rerun()
            if st.button("End without saving",use_container_width=True): st.session_state.focus_running=False; st.session_state.focus_start=None; st.rerun()
        st.markdown("</div>",unsafe_allow_html=True)
    with b:
        st.markdown("<div class='panel'><div class='panel-title'>🧘 Healthy study reminders</div><div style='margin-top:15px;line-height:2.0;color:#b7c7e0'>• Take a short break every 25–50 minutes.<br>• Stand up, stretch and drink water.<br>• Set a realistic goal, not a punishment.<br>• Protect sleep — it helps memory consolidate.<br>• End the session when focus has genuinely faded.</div></div>",unsafe_allow_html=True)
        st.markdown("<div class='panel' style='margin-top:14px'><div class='panel-title'>Today's progress</div>",unsafe_allow_html=True)
        seconds=total_study_seconds(date.today().isoformat()); goalrow=query_one("SELECT goal_minutes FROM daily_goals WHERE day=?",(date.today().isoformat(),)); goal=int(goalrow["goal_minutes"] if goalrow else 120); pct=min(100,int(seconds/max(1,goal*60)*100))
        st.markdown(f"<div style='font-size:1.8rem;font-weight:800;margin:8px 0'>{fmt_time(seconds)}</div><div class='progress-track'><div class='progress-fill' style='width:{pct}%'></div></div><div class='small-muted' style='margin-top:8px'>{pct}% of daily goal</div></div>",unsafe_allow_html=True)

# -------------------- Library --------------------
elif st.session_state.page=="Library":
    heading("YOUR KNOWLEDGE BASE","My lecture library","Everything you upload is automatically saved here. Open, continue, revise or remove a source.")
    search=st.text_input("Search your library",placeholder="Search lectures, PDFs, videos…")
    lectures=query_all("SELECT l.id,l.title,l.file_name,l.file_type,l.created_at,COALESCE(p.progress,0) progress FROM lectures l LEFT JOIN study_progress p ON p.lecture_id=l.id ORDER BY l.id DESC")
    if search.strip(): lectures=[r for r in lectures if search.lower() in (r["title"]+r["file_name"]).lower()]
    if not lectures: st.info("No matching lectures. Add one in Study Workspace or YouTube Learning.")
    for lec in lectures:
        p=int(lec["progress"]); st.markdown(f"<div class='panel' style='margin:10px 0'><div style='display:flex;justify-content:space-between;gap:10px;align-items:center'><div><div class='card-title'>📘 {esc(lec['title'])}</div><div class='small-muted'>{esc(lec['file_name'])} · {esc(lec['created_at'])}</div></div><span class='pill'>{p}% complete</span></div><div class='progress-track' style='margin:12px 0'><div class='progress-fill' style='width:{p}%'></div></div></div>",unsafe_allow_html=True)
        a,b,c=st.columns([1,1,1])
        with a:
            if st.button("Open & study",key=f"lib_open_{lec['id']}",type="primary",use_container_width=True): st.session_state.current_lecture_id=lec["id"]; st.session_state.page="Study Workspace"; st.rerun()
        with b:
            if st.button("Generate quiz",key=f"lib_quiz_{lec['id']}",use_container_width=True): st.session_state.current_lecture_id=lec["id"]; st.session_state.page="Question Bank"; st.rerun()
        with c:
            if st.button("Delete source",key=f"lib_del_{lec['id']}",use_container_width=True):
                execute("DELETE FROM study_packs WHERE lecture_id=?",(lec["id"],)); execute("DELETE FROM study_progress WHERE lecture_id=?",(lec["id"],)); execute("DELETE FROM lectures WHERE id=?",(lec["id"],)); st.rerun()
    st.markdown("### Generated study packs")
    packs=query_all("SELECT id,title,provider,model,created_at,content FROM study_packs ORDER BY id DESC LIMIT 40")
    for p in packs:
        with st.expander(f"{p['title']} · {p['created_at']}"):
            st.caption(f"Generated with {p['provider']} / {p['model']}")
            if "Interactive Quiz" in p["title"] or '"questions"' in p["content"][:100:]:
                if st.button("Take interactive quiz",key=f"lib_take_{p['id']}"): st.session_state.quiz_pack_id=p["id"]; st.session_state.quiz_answers={}; st.session_state.quiz_submitted=False; st.session_state.page="Question Bank"; st.rerun()
            else: st.markdown(p["content"])
            st.download_button("Download Markdown",p["content"],file_name=f"lecturegpt_{p['id']}.md",mime="text/markdown",key=f"lib_dl_{p['id']}")

# -------------------- Achievements --------------------
elif st.session_state.page=="Achievements":
    heading("MILESTONES","Consistency is an achievement.","Celebrate progress, not just perfect scores.")
    total=total_study_seconds(); sessions=query_one("SELECT COUNT(*) n FROM study_sessions")["n"]; lectures=query_one("SELECT COUNT(*) n FROM lectures")["n"]; completed=query_one("SELECT COUNT(*) n FROM study_progress WHERE progress>=100")["n"]
    a,b,c,d=st.columns(4); a.metric("Total focused time",fmt_time(total)); b.metric("Focus sessions",sessions); c.metric("Lectures added",lectures); d.metric("Lectures completed",completed)
    milestones=[("First session",sessions>=1,"Complete one focus session."),("One hour focused",total>=3600,"Reach 60 minutes of recorded focus time."),("First lecture complete",completed>=1,"Finish a lecture and mark it complete."),("Five lectures",lectures>=5,"Add five sources to your library."),("Ten focus sessions",sessions>=10,"Build a steady focus routine.")]
    for title,earned,desc in milestones:
        st.markdown(f"<div class='panel' style='margin:9px 0;display:flex;gap:14px;align-items:center'><div style='font-size:1.7rem'>{'🏆' if earned else '🔒'}</div><div><div class='card-title'>{title} {'· Unlocked' if earned else '· In progress'}</div><div class='small-muted'>{desc}</div></div></div>",unsafe_allow_html=True)

# -------------------- Settings --------------------
elif st.session_state.page=="Settings":
    heading("WORKSPACE SETTINGS","Make LectureGPT yours.","Personalize your profile and review the AI providers connected through your local .env file.")
    st.markdown("### Your profile")
    with st.form("profile_settings"):
        current_name=setting_value("user_name","Raj")
        new_name=st.text_input("What should LectureGPT call you?",value=current_name,max_chars=40,placeholder="Enter your preferred name")
        saved=st.form_submit_button("Save profile",type="primary")
        if saved:
            if new_name.strip():
                set_setting("user_name",new_name.strip()); st.success("Profile name updated."); st.rerun()
            else: st.warning("Please enter a name.")
    st.markdown("### AI providers")
    cfgs=provider_config()
    for provider,cfg in cfgs.items(): st.markdown(f"<div class='panel' style='margin:9px 0'><div class='card-title'>{'🟢' if cfg['key'] else '⚪'} {provider}</div><div class='small-muted'>API key {'configured' if cfg['key'] else 'not configured'} · Default model: {esc(cfg['model'])}</div></div>",unsafe_allow_html=True)
    st.caption("Every generated answer and saved assistant chat message shows the provider and model that actually responded, including when fallback routing is used.")
    st.markdown("### NVIDIA live connection check")
    ncfg=provider_config()["NVIDIA"]
    if ncfg["key"]:
        if st.button("Discover currently available NVIDIA models",key="discover_nvidia_models",use_container_width=True):
            try:
                with st.spinner("Fetching the live NVIDIA model catalog for your API key…"):
                    st.session_state.nvidia_live_models=nvidia_available_models()
                st.success(f"Found {len(st.session_state.nvidia_live_models)} models available to this API key.")
            except Exception as exc: st.error(str(exc))
        live_models=st.session_state.get("nvidia_live_models",[])
        if live_models:
            current=ncfg["model"]
            default_index=live_models.index(current) if current in live_models else 0
            selected_model=st.selectbox("NVIDIA model (live catalog)",live_models,index=default_index,key="nvidia_live_model_choice")
            if st.button("Use selected NVIDIA model",key="save_nvidia_model",use_container_width=True):
                set_setting("nvidia_model_override",selected_model)
                st.success(f"Saved NVIDIA model: {selected_model}")
                st.rerun()
        if st.button("Test NVIDIA model & API",key="test_nvidia_live",type="primary",use_container_width=True):
            try:
                with st.spinner("Checking NVIDIA model availability and sending a real test request…"):
                    chosen,reply,models=test_nvidia_connection()
                st.success(f"Connected · {chosen}")
                st.caption("Live chat response: "+reply[:240])
            except Exception as exc: st.error(str(exc))
    else:
        st.info("Add NVIDIA_API_KEY to your local .env file to discover models and test live availability.")
    st.markdown("### .env configuration")
    st.code("GROQ_API_KEY=\nGROQ_MODEL=openai/gpt-oss-120b\n\nNVIDIA_API_KEY=\nNVIDIA_MODEL=\nNVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1\n\nOPENROUTER_API_KEY=\nOPENROUTER_MODEL=openrouter/free\n\nGEMINI_API_KEY=\nGEMINI_MODEL=gemini-2.5-flash",language="dotenv")
    st.markdown("### Data & privacy")
    st.markdown(f"- Authentication mode: **{esc(AUTH_MODE)}**. Hosted OIDC mode creates a separate SQLite database file for each authenticated subject ID.\n- Local mode is single-user only. Never deploy with `APP_AUTH_MODE=local` on a public multi-user app.\n- Hosted SQLite files are stored on the app filesystem, which may be ephemeral on Streamlit Community Cloud. Use an external persistent database/object store for durable production storage.\n- Uploaded text is sent to the AI provider you use when you request generation or answers.\n- This app supports text-based PDFs, TXT, MD, CSV and accessible YouTube captions. If YouTube blocks cloud captions, paste the transcript manually. Scanned-PDF OCR and audio transcription are not included.\n- YouTube watch progress is manually updated; embedded player progress is not automatically detected.")

st.markdown("<div style='text-align:center;color:#6f82a2;font-size:.75rem;padding-top:30px'>LectureGPT · Study intentionally · Private learner workspace · OIDC sign-in</div>",unsafe_allow_html=True)
