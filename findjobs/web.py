"""Local web UI: `python -m findjobs ui`. Binds to 127.0.0.1 only.

Settings (API keys, Apify actor), the student profile, uploads and results live in a
workspace folder on this machine. Nothing is sent anywhere except Claude, Apify and Upwork.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .profile import Profile, read_dossier_text

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = ("anthropic_api_key", "apify_token")
SETTING_KEYS = SECRET_KEYS + ("apify_actor", "apify_input", "chromium", "max_results")
DEFAULT_SETTINGS = {"apify_actor": "", "apify_input": json.dumps({"query": "{query}", "maxItems": 30}, indent=1),
                    "chromium": "", "max_results": 10}
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class State:
    def __init__(self, ws: Path):
        self.ws = ws
        self.out = ws / "out"
        self.uploads = ws / "uploads"
        for d in (ws, self.out, self.uploads):
            d.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.task: str | None = None
        self.log: list[str] = []
        self.error: str | None = None
        self.finished_at: float | None = None

    # ---- settings ----
    @property
    def settings_path(self) -> Path:
        return self.ws / "settings.json"

    def settings(self) -> dict:
        s = dict(DEFAULT_SETTINGS)
        if self.settings_path.exists():
            s.update(json.loads(self.settings_path.read_text()))
        return s

    def save_settings(self, new: dict) -> None:
        cur = self.settings()
        for k in SETTING_KEYS:
            if k not in new:
                continue
            if k in SECRET_KEYS and (new[k] or "").startswith("••"):
                continue  # masked value sent back unchanged
            cur[k] = new[k]
        if cur.get("apify_input"):
            json.loads(cur["apify_input"])  # validate
        self.settings_path.write_text(json.dumps(cur, indent=1))
        try:
            os.chmod(self.settings_path, 0o600)
        except OSError:
            pass

    def public_settings(self) -> dict:
        s = self.settings()
        for k in SECRET_KEYS:
            v = s.get(k) or ""
            s[k] = ("••••" + v[-4:]) if v else ""
        s["upwork_session"] = (self.ws / "upwork_state.json").exists()
        s["have_profile"] = (self.ws / "profile.json").exists()
        return s

    def apply_env(self) -> None:
        s = self.settings()
        for key, env in (("anthropic_api_key", "ANTHROPIC_API_KEY"), ("apify_token", "APIFY_TOKEN"),
                         ("apify_actor", "APIFY_ACTOR")):
            if s.get(key):
                os.environ[env] = s[key]
        if s.get("chromium"):
            os.environ["FINDJOBS_CHROMIUM"] = s["chromium"]

    # ---- background tasks ----
    def start(self, name: str, fn) -> bool:
        with self.lock:
            if self.task:
                return False
            self.task, self.log, self.error, self.finished_at = name, [], None, None

        def runner():
            try:
                fn(self.say)
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                self.say(traceback.format_exc(limit=3))
            finally:
                self.finished_at = time.time()
                with self.lock:
                    self.task = None

        threading.Thread(target=runner, daemon=True).start()
        return True

    def say(self, msg: str) -> None:
        for k in SECRET_KEYS:  # never echo secrets into the log
            v = self.settings().get(k)
            if v:
                msg = msg.replace(v, "••••")
        self.log.append(msg)


def _run_args(st: State, body: dict) -> argparse.Namespace:
    s = st.settings()
    jobs = []
    for f in body.get("job_files") or []:
        p = st.uploads / Path(f).name
        if p.exists():
            jobs.append(str(p))
    if body.get("reuse_verified") and (st.out / "jobs.verified.json").exists():
        jobs.append(str(st.out / "jobs.verified.json"))
    apify_input = None
    if body.get("use_apify"):
        apify_input = st.ws / "apify_input.json"
        apify_input.write_text(s.get("apify_input") or DEFAULT_SETTINGS["apify_input"])
    queries = [q.strip() for q in (body.get("queries") or "").splitlines() if q.strip()]
    judgments = st.ws / "judgments.json"
    return argparse.Namespace(
        profile=str(st.ws / "profile.json"), dossier=None, jobs=jobs, apify=bool(body.get("use_apify")),
        apify_input=str(apify_input) if apify_input else None, query=queries or None,
        state=str(st.ws / "upwork_state.json") if (st.ws / "upwork_state.json").exists() else None,
        chromium=s.get("chromium") or None, headed=bool(body.get("headed")), no_verify=bool(body.get("no_verify")),
        show_unverified=bool(body.get("show_unverified")),
        judgments=str(judgments) if body.get("use_judgments") and judgments.exists() else None,
        api=False, max_age_hours=float(body.get("max_age_hours") or 24), max=int(body.get("max_results") or s.get("max_results") or 10), audit=bool(body.get("audit", True)),
        out_dir=str(st.out),
    )


def make_handler(st: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _ok_origin(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return False
            origin = self.headers.get("Origin")
            return not origin or urlparse(origin).hostname in ("127.0.0.1", "localhost")

        def _send(self, code: int, body: bytes | str, ctype: str = "application/json") -> None:
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            if not self._ok_origin():
                return self._send(403, "forbidden", "text/plain")
            path = urlparse(self.path).path
            if path == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if path == "/api/settings":
                return self._json(st.public_settings())
            if path == "/api/profile":
                p = st.ws / "profile.json"
                return self._json({"profile": p.read_text() if p.exists() else ""})
            if path == "/api/examples":
                ex = sorted(x.name for x in (ROOT / "examples").glob("profile.*.json")) if (ROOT / "examples").exists() else []
                return self._json({"examples": ex})
            if path == "/api/status":
                outs = {n: (st.out / n).exists() for n in ("report.html", "report.md", "results.json",
                                                            "judge_requests.json", "jobs.verified.json")}
                summary = None
                if (st.out / "results.json").exists():
                    r = json.loads((st.out / "results.json").read_text())
                    summary = {"stats": r.get("stats"), "shortlisted": len(r.get("shortlist", [])),
                               "unverified": len(r.get("unverified", [])), "excluded": len(r.get("excluded", [])),
                               "run_at": r.get("run_at")}
                return self._json({"task": st.task, "log": st.log[-400:], "error": st.error, "outputs": outs,
                                   "summary": summary, "judgments": (st.ws / "judgments.json").exists(),
                                   "finished_at": st.finished_at})
            if path.startswith("/out/"):
                name = path[5:]
                f = st.out / name
                if not SAFE_NAME.match(name) or not f.exists():
                    return self._send(404, "not found", "text/plain")
                ctype = {"html": "text/html; charset=utf-8", "md": "text/markdown; charset=utf-8"}.get(
                    name.rsplit(".", 1)[-1], "application/json")
                return self._send(200, f.read_bytes(), ctype)
            return self._send(404, "not found", "text/plain")

        def do_POST(self):
            if not self._ok_origin():
                return self._send(403, "forbidden", "text/plain")
            path = urlparse(self.path).path
            try:
                b = self._body()
                if path == "/api/settings":
                    st.save_settings(b)
                    return self._json(st.public_settings())
                if path == "/api/profile":
                    p = Profile.from_dict(json.loads(b["profile"]))  # validates
                    if not p.name or not p.country:
                        raise ValueError("profile needs at least name and country")
                    p.save(st.ws / "profile.json")
                    return self._json({"ok": True})
                if path == "/api/profile/example":
                    name = Path(b["name"]).name
                    src = ROOT / "examples" / name
                    if not SAFE_NAME.match(name) or not src.exists():
                        raise ValueError("unknown example")
                    (st.ws / "profile.json").write_text(src.read_text())
                    return self._json({"ok": True})
                if path == "/api/upload":
                    name = Path(b["name"]).name
                    if not SAFE_NAME.match(name):
                        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
                    data = base64.b64decode(b["data"])
                    if len(data) > 25_000_000:
                        raise ValueError("file over 25 MB")
                    dest = (st.ws / "judgments.json") if b.get("kind") == "judgments" else (st.uploads / name)
                    dest.write_bytes(data)
                    if b.get("kind") == "judgments":
                        json.loads(data)
                    return self._json({"ok": True, "name": dest.name})
                if path == "/api/extract":
                    dossier = st.uploads / Path(b["name"]).name
                    if not dossier.exists():
                        raise ValueError("upload the dossier first")
                    st.apply_env()
                    if not os.environ.get("ANTHROPIC_API_KEY"):
                        raise ValueError("Profile extraction needs an Anthropic API key (Settings). "
                                         "Or pick/paste a profile JSON instead.")

                    def job(log):
                        from .judge import extract_profile

                        log(f"Reading {dossier.name}...")
                        text = read_dossier_text(dossier)
                        log(f"{len(text):,} characters. Asking Claude to extract the profile...")
                        extract_profile(text).save(st.ws / "profile.json")
                        log("Profile extracted. Review it: evidence and weak_or_unproven control what gets claimed.")

                    return self._json({"started": st.start("extract", job)})
                if path == "/api/login":
                    st.apply_env()

                    def job(log):
                        from .verify import save_login_state

                        log("A browser window is opening. Log in to Upwork there; it closes by itself once you're in.")
                        ok = save_login_state(str(st.ws / "upwork_state.json"), st.settings().get("chromium") or None,
                                              interactive=False)
                        log("Session saved." if ok else "Login not completed (window closed or timed out).")

                    return self._json({"started": st.start("login", job)})
                if path == "/api/run":
                    if not (st.ws / "profile.json").exists():
                        raise ValueError("Save a student profile first.")
                    st.apply_env()
                    args = _run_args(st, b)
                    if not args.jobs and not args.apify:
                        raise ValueError("Pick a job source: Apify and/or an uploaded jobs file.")
                    if args.apify and not (os.environ.get("APIFY_TOKEN") and os.environ.get("APIFY_ACTOR")):
                        raise ValueError("Apify needs a token and actor ID (Settings).")

                    def job(log):
                        from .cli import execute_run

                        execute_run(args, log)

                    return self._json({"started": st.start("run", job)})
            except (ValueError, KeyError, json.JSONDecodeError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            return self._send(404, "not found", "text/plain")

    return H


def serve(port: int = 8765, workspace: str = "workspace", open_browser: bool = True) -> None:
    st = State(Path(workspace).resolve())
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(st))
    url = f"http://127.0.0.1:{port}/"
    print(f"FindJobs UI running at {url}  (workspace: {st.ws})  Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>FindJobs</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--fg:#1b1b1a;--mute:#6b6a66;--line:#e2e0da;--acc:#14804a;--acc-fg:#fff;--warn:#a85a00;--bad:#b42318;--code:#f1efe9}
@media (prefers-color-scheme:dark){:root{--bg:#121211;--card:#1c1c1b;--fg:#ecebe7;--mute:#a19f99;--line:#333230;--acc:#3ccf7f;--acc-fg:#0d1f15;--warn:#f0a040;--bad:#ff7a6b;--code:#262624}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:20px 16px 4px;max-width:1100px;margin:0 auto}h1{font-size:20px;margin:0}header p{margin:2px 0 0;color:var(--mute)}
main{max-width:1100px;margin:0 auto;padding:12px 16px 40px;display:grid;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h2{font-size:15px;margin:0 0 10px;display:flex;align-items:center;gap:8px}
.n{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--acc);color:var(--acc-fg);font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px 14px}
label{display:block;font-size:12px;color:var(--mute);margin-bottom:3px}
input[type=text],input[type=password],input[type=number],textarea,select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);font:inherit}
textarea{font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;resize:vertical}
button{padding:8px 14px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;cursor:pointer}
button.primary{background:var(--acc);color:var(--acc-fg);border-color:var(--acc);font-weight:600}
button:disabled{opacity:.5;cursor:default}.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
.checks{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:8px}.checks label{display:flex;gap:6px;align-items:center;color:var(--fg);font-size:13px;margin:0}
.pill{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mute)}.pill.ok{color:var(--acc);border-color:var(--acc)}
.hint{color:var(--mute);font-size:12px;margin:6px 0 0}.err{color:var(--bad);font-size:13px;margin-top:8px;white-space:pre-wrap}
#log{background:var(--code);border-radius:8px;padding:10px;height:180px;overflow:auto;font:12px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;margin:0}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}.stat{background:var(--code);border-radius:8px;padding:8px 12px;min-width:110px}
.stat b{display:block;font-size:20px}.stat span{font-size:12px;color:var(--mute)}
iframe{width:100%;height:720px;border:1px solid var(--line);border-radius:8px;background:#fff}
a{color:var(--acc)}details summary{cursor:pointer;color:var(--mute);font-size:13px}
</style></head><body>
<header><h1>FindJobs</h1><p>Dossier in, live-verified Upwork shortlist out. Runs on this computer.</p></header>
<main>
<section class="card"><h2><span class="n">1</span>Settings <span id="sessPill" class="pill">Upwork: not logged in</span></h2>
 <div class="grid">
  <div><label>Anthropic API key (fit judgment, dossier extraction)</label><input id="anthropic_api_key" type="password" autocomplete="off" placeholder="sk-ant-..."></div>
  <div><label>Apify API token</label><input id="apify_token" type="password" autocomplete="off" placeholder="apify_api_..."></div>
  <div><label>Apify actor ID</label><input id="apify_actor" type="text" placeholder="username~upwork-jobs-scraper"></div>
  <div><label>Chromium path (optional)</label><input id="chromium" type="text" placeholder="leave blank for Playwright's"></div>
 </div>
 <details style="margin-top:10px"><summary>Apify actor input template</summary>
  <p class="hint">Every "{query}" is replaced with each search query. Match the input your actor expects.</p>
  <textarea id="apify_input" rows="5"></textarea></details>
 <div class="row"><button onclick="saveSettings()">Save settings</button><button onclick="login()">Log in to Upwork</button>
  <span class="hint">Keys stay in workspace/settings.json on this machine.</span></div>
 <div id="setErr" class="err"></div>
</section>

<section class="card"><h2><span class="n">2</span>Student profile <span id="profPill" class="pill">none</span></h2>
 <div class="grid">
  <div><label>Upload dossier (PDF, DOCX, MD, TXT) and extract with Claude</label><input id="dossier" type="file" accept=".pdf,.docx,.md,.txt"></div>
  <div><label>Or start from an example</label><select id="examples"><option value="">Choose...</option></select></div>
 </div>
 <div class="row"><button onclick="extract()">Extract profile from dossier</button></div>
 <label style="margin-top:12px">Profile JSON. Check it: <b>evidence</b> is what may be claimed, <b>weak_or_unproven</b> is what never will be.</label>
 <textarea id="profile" rows="14" spellcheck="false"></textarea>
 <div class="row"><button class="primary" onclick="saveProfile()">Save profile</button></div>
 <div id="profErr" class="err"></div>
</section>

<section class="card"><h2><span class="n">3</span>Find jobs</h2>
 <div class="grid">
  <div><label>Search queries (one per line; blank = profile's search_queries)</label><textarea id="queries" rows="7"></textarea></div>
  <div>
   <label>Job sources</label>
   <div class="checks"><label><input type="checkbox" id="use_apify" checked> Search live via Apify</label></div>
   <label style="margin-top:10px">Also screen jobs from a file (JSON/CSV export)</label><input id="jobsfile" type="file" accept=".json,.csv">
   <label style="margin-top:10px">Max jobs in shortlist</label><input id="max_results" type="number" min="1" max="30" value="10">
  </div>
 </div>
 <div class="checks">
  <label><input type="checkbox" id="audit" checked> Show why each job was excluded</label>
  <label><input type="checkbox" id="show_unverified"> List good jobs that couldn't be verified</label>
  <label><input type="checkbox" id="headed"> Show browser while verifying</label>
  <label><input type="checkbox" id="no_verify"> Skip live verification (nothing gets recommended)</label>
 </div>
 <div class="row"><button class="primary" id="runBtn" onclick="run()">Run</button><span id="taskPill" class="pill">idle</span></div>
 <div id="runErr" class="err"></div>
</section>

<section class="card"><h2><span class="n">4</span>Progress and results</h2>
 <pre id="log">Nothing running yet.</pre>
 <div id="summary"></div>
 <div id="judgeBox" style="display:none" class="card">
  <b>No Claude API key, so fit judgment is pending.</b>
  <p class="hint">Download judge_requests.json, have Claude Code (the findjobs skill) fill judgments.json, upload it, re-run. Already-verified jobs are reused, not reopened.</p>
  <div class="row"><a href="/out/judge_requests.json" download>Download judge_requests.json</a>
   <input id="judgfile" type="file" accept=".json"><button onclick="rerunJudged()">Upload judgments and re-run</button></div>
 </div>
 <div id="links" class="row"></div>
 <div id="reportWrap" style="margin-top:10px"></div>
</section>
</main>
<script>
const $=id=>document.getElementById(id);
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const j=await r.json().catch(()=>({error:'bad response'}));if(!r.ok||j.error)throw new Error(j.error||r.statusText);return j}
function b64(file){return new Promise((res,rej)=>{const fr=new FileReader();fr.onload=()=>res(fr.result.split(',')[1]);fr.onerror=rej;fr.readAsDataURL(file)})}
async function upload(file,kind){return api('/api/upload',{name:file.name,data:await b64(file),kind})}
async function loadSettings(){const s=await api('/api/settings');
 for(const k of ['anthropic_api_key','apify_token','apify_actor','chromium','apify_input'])$(k).value=s[k]||'';
 $('max_results').value=s.max_results||10;
 $('sessPill').textContent=s.upwork_session?'Upwork: session saved':'Upwork: not logged in';$('sessPill').className='pill'+(s.upwork_session?' ok':'')}
async function saveSettings(){$('setErr').textContent='';try{await api('/api/settings',{anthropic_api_key:$('anthropic_api_key').value,
 apify_token:$('apify_token').value,apify_actor:$('apify_actor').value.trim(),chromium:$('chromium').value.trim(),apify_input:$('apify_input').value,
 max_results:+$('max_results').value});await loadSettings();$('setErr').textContent=''}catch(e){$('setErr').textContent=e.message}}
async function login(){$('setErr').textContent='';try{await saveSettings();await api('/api/login',{});poll()}catch(e){$('setErr').textContent=e.message}}
async function loadProfile(){const p=await api('/api/profile');$('profile').value=p.profile;
 let name='none';try{name=JSON.parse(p.profile).name||'unnamed'}catch{} $('profPill').textContent=name;$('profPill').className='pill'+(p.profile?' ok':'');
 if(!$('queries').value&&p.profile){try{$('queries').placeholder=(JSON.parse(p.profile).search_queries||[]).join('\n')}catch{}}}
async function loadExamples(){const e=await api('/api/examples');for(const n of e.examples){const o=document.createElement('option');o.value=n;o.textContent=n;$('examples').appendChild(o)}}
$('examples').onchange=async e=>{if(!e.target.value)return;await api('/api/profile/example',{name:e.target.value});loadProfile()};
async function saveProfile(){$('profErr').textContent='';try{await api('/api/profile',{profile:$('profile').value});loadProfile()}catch(e){$('profErr').textContent=e.message}}
async function extract(){$('profErr').textContent='';const f=$('dossier').files[0];if(!f){$('profErr').textContent='Choose a dossier file first.';return}
 try{await saveSettings();const u=await upload(f);await api('/api/extract',{name:u.name});poll()}catch(e){$('profErr').textContent=e.message}}
async function run(extra={}){$('runErr').textContent='';try{await saveSettings();
 const body={use_apify:$('use_apify').checked,queries:$('queries').value,audit:$('audit').checked,show_unverified:$('show_unverified').checked,
  headed:$('headed').checked,no_verify:$('no_verify').checked,max_results:+$('max_results').value,job_files:[],...extra};
 if($('jobsfile').files[0]&&!extra.reuse_verified){const u=await upload($('jobsfile').files[0]);body.job_files.push(u.name)}
 await api('/api/run',body);poll()}catch(e){$('runErr').textContent=e.message}}
async function rerunJudged(){const f=$('judgfile').files[0];if(!f){$('runErr').textContent='Choose judgments.json first.';return}
 try{await upload(f,'judgments');run({use_apify:false,reuse_verified:true,use_judgments:true})}catch(e){$('runErr').textContent=e.message}}
let timer=null,lastFinished=null;
async function poll(){clearTimeout(timer);const s=await api('/api/status');
 $('log').textContent=s.log.length?s.log.join('\n'):'Nothing running yet.';$('log').scrollTop=1e9;
 $('taskPill').textContent=s.task?('running: '+s.task):(s.error?'failed':'idle');$('taskPill').className='pill'+(s.task?' ok':'');
 $('runBtn').disabled=!!s.task;if(s.error)$('runErr').textContent=s.error;
 if(!s.task&&s.finished_at!==lastFinished){lastFinished=s.finished_at;loadSettings();loadProfile();showResults(s)}
 if(s.task)timer=setTimeout(poll,1000)}
function showResults(s){const m=s.summary;if(m){const st=m.stats||{};
 $('summary').innerHTML=`<div class="stats"><div class="stat"><b>${st.discovered??0}</b><span>discovered</span></div>
 <div class="stat"><b>${st.passed_deterministic??0}</b><span>passed hard gates</span></div>
 <div class="stat"><b>${m.shortlisted}</b><span>actionable</span></div><div class="stat"><b>${m.unverified}</b><span>unverified</span></div>
 <div class="stat"><b>${m.excluded}</b><span>excluded</span></div></div>`}
 $('judgeBox').style.display=s.outputs['judge_requests.json']&&m&&m.shortlisted===0?'block':'none';
 $('links').innerHTML=['report.html','report.md','results.json'].filter(n=>s.outputs[n]).map(n=>`<a href="/out/${n}" target="_blank" rel="noopener">${n}</a>`).join(' · ');
 $('reportWrap').innerHTML=s.outputs['report.html']?`<iframe src="/out/report.html?t=${Date.now()}" title="Report"></iframe>`:''}
(async()=>{await loadSettings();await loadProfile();await loadExamples();const s=await api('/api/status');lastFinished=s.finished_at;showResults(s);if(s.task)poll()})();
</script></body></html>"""
