"""
Hosted report browser. Two modes:

1. Browse precomputed reports for the fixed eval-set repos (the default,
   always fast, never fails live during judging).
2. "Analyze a new repo" — live ingest + audit on a GitHub URL or zip upload.
   Gated behind ENABLE_LIVE_INGEST because it means running a stranger's
   code; keep this False on any public deployment (see README).

Run: streamlit run app.py
"""

import os
import tempfile
import time
import concurrent.futures

import streamlit as st
import yaml
from dotenv import load_dotenv

from agent.audit_repo import audit_repo
from agent.audit_history import save_audit_record, get_recent_audits
from agent.send_report_email import send_report_email
from agent.trajectory_logger import TrajectoryLogger
from baseline.rate_repo import baseline_rate
from ingest.ingest import ingest
from llm.client import LLMClient
from report.generate_report import load_report, render_business_report, save_report
from report.generate_pdf import render_pdf_report

load_dotenv()
ENABLE_LIVE_INGEST = os.environ.get("ENABLE_LIVE_INGEST", "False").strip().lower() == "true"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

# Live ingest runs arbitrary strangers' repos on a public endpoint — these
# two caps exist specifically to bound that exposure. BUILD_TIMEOUT_SEC in
# audit_repo.py only bounds the build/test subprocess; this bounds the
# ENTIRE flow (ingest + every scan + every LLM call), since none of those
# individually-reasonable steps have a combined ceiling otherwise.
LIVE_ANALYSIS_TIMEOUT_SEC = 300
MAX_FILE_COUNT_FOR_LIVE_ANALYSIS = 3000

st.set_page_config(page_title="Repo Due-Diligence Agent", layout="wide", page_icon="🔎")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

/* Hide Streamlit's own default chrome so nothing reads as "generic template" */
#MainMenu, header[data-testid="stHeader"], footer {visibility: hidden;}

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, sans-serif;
}

h1, h2, h3 {
    font-family: 'Fraunces', Georgia, serif !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
}

/* Evidence citations (the "— evidence: ..." lines) read as technical/forensic data,
   not prose — monospace makes that distinction visible, not just stated */
.stMarkdown em {
    font-family: 'IBM Plex Mono', monospace;
    font-style: normal;
    color: #9B9891;
    font-size: 0.92em;
}

.stMarkdown hr {
    border-color: #2A2E38;
    margin: 1.5rem 0;
}

.stMarkdown table {
    border: 1px solid #2A2E38;
    border-radius: 6px;
    overflow: hidden;
}
.stMarkdown table th {
    background-color: #1A1D24;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #9B9891;
}

/* The certification stamp — the one deliberate signature element,
   everything else stays quiet by design */
.verdict-stamp {
    display: inline-block;
    border: 3px solid var(--stamp-color, #C9A227);
    border-radius: 50%;
    color: var(--stamp-color, #C9A227);
    font-family: 'Fraunces', serif;
    font-weight: 700;
    padding: 1.1rem 0.4rem;
    width: 118px;
    height: 118px;
    text-align: center;
    transform: rotate(-4deg);
    box-shadow: 0 0 0 1px var(--stamp-color, #C9A227) inset;
    margin: 0.5rem 0 1rem 0;
}
.verdict-stamp .score-num {
    font-size: 2.6rem;
    line-height: 1;
    display: block;
}
.verdict-stamp .score-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    display: block;
    margin-top: 2px;
}
</style>
""", unsafe_allow_html=True)


def _verdict_stamp(score) -> str:
    """The signature visual element — an inspection-stamp treatment for the
    score, colored by actual risk level so color carries real meaning
    rather than decoration. Rendered separately from render_business_report()
    on purpose: that function's plain-markdown output stays clean and
    portable for the .md exports and email attachments; this HTML-only
    enhancement is display-layer-only, live-app-only."""
    if score is None:
        return ""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    color = "#4A7C6F" if s >= 8 else ("#C9A227" if s >= 5 else "#B0413E")
    return (
        f'<div class="verdict-stamp" style="--stamp-color: {color}">'
        f'<span class="score-num">{score}</span>'
        f'<span class="score-label">/ 10</span>'
        f'</div>'
    )


st.title("Is this repo actually good?")
st.caption("Evidence-based codebase due-diligence — baseline vs. agent, side by side.")


def _pdf_download_button(report: dict, repo_label: str, key_suffix: str):
    """Small reusable widget: download this report as a PDF. Kept as
    plain text (no emoji) deliberately — new UI elements shouldn't
    introduce fresh styling decisions outside the ongoing design pass."""
    tmp_path = os.path.join(tempfile.gettempdir(), f"{repo_label}_report_{key_suffix}.pdf")
    render_pdf_report(report, repo_label, tmp_path)
    with open(tmp_path, "rb") as f:
        pdf_bytes = f.read()
    st.download_button(
        label=f"Download PDF report ({repo_label})",
        data=pdf_bytes,
        file_name=f"{repo_label}_due_diligence_report.pdf",
        mime="application/pdf",
        key=f"pdf_dl_{key_suffix}",
    )


def _email_button(report: dict, repo_label: str, key_suffix: str):
    """Small reusable widget: email this report as a .md attachment. Only
    rendered functional if Gmail credentials are configured — otherwise
    shows nothing rather than silently failing on click."""
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD):
        return
    with st.expander(f"📧 Email this report ({repo_label})"):
        to_addr = st.text_input("Send to", key=f"email_to_{key_suffix}")
        if st.button("Send", key=f"email_btn_{key_suffix}") and to_addr:
            md_content = render_business_report(report, repo_label)
            tmp_path = os.path.join(tempfile.gettempdir(), f"{repo_label}_report.md")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            result = send_report_email(
                to_addr,
                f"Due-Diligence Report: {repo_label}",
                f"Attached: due-diligence report for {repo_label}.\n\n{md_content[:300]}...",
                tmp_path, GMAIL_ADDRESS, GMAIL_APP_PASSWORD,
            )
            if result.get("sent"):
                st.success("Sent.")
            else:
                st.error(f"Failed: {result.get('error', result.get('reason'))}")


tab_browse, tab_live, tab_history = st.tabs(
    ["Browse eval-set reports", "Analyze a new repo", "📜 Audit history"]
)

with tab_browse:
    try:
        with open("repos_manifest.yaml") as fh:
            manifest = yaml.safe_load(fh)["repos"]
    except FileNotFoundError:
        manifest = []

    repo_ids = [r["id"] for r in manifest if r.get("github_url")]
    if not repo_ids:
        st.info("No repos configured yet — fill in repos_manifest.yaml and run eval/run_eval.py first.")
    else:
        selected = st.selectbox("Pick a repo from the eval set", repo_ids)
        col1, col2 = st.columns(2)

        baseline_report = load_report(selected, "baseline")
        agent_report = load_report(selected, "agent")

        with col1:
            st.subheader("Baseline (surface-level)")
            if baseline_report:
                st.markdown(f"### Baseline rating: {baseline_report.get('score', '—')}/10\n\n"
                             f"{baseline_report.get('reasoning', '(no reasoning returned)')}")
            else:
                st.warning("No cached baseline report — run eval/run_eval.py first.")

        with col2:
            st.subheader("Agent (evidence-based)")
            if agent_report:
                st.markdown(_verdict_stamp(agent_report.get("score")), unsafe_allow_html=True)
                st.markdown(render_business_report(agent_report, selected))
                _pdf_download_button(agent_report, selected, "browse")
                _email_button(agent_report, selected, "browse")
            else:
                st.warning("No cached agent report — run eval/run_eval.py first.")

with tab_live:
    if not ENABLE_LIVE_INGEST:
        st.warning(
            "Live analysis of arbitrary repos is disabled on this deployment. "
            "Running strangers' code needs sandboxing (timeouts, ephemeral dirs, "
            "no persisted secrets) that goes beyond what a public demo endpoint "
            "should expose. See the reproduction guide to run this mode locally."
        )
    else:
        st.caption("This clones/unpacks and may execute code from the input you give it. Local/private use only.")
        source_type = st.radio("Input type", ["GitHub URL", "Upload .zip"])

        source = None
        if source_type == "GitHub URL":
            url = st.text_input("GitHub repo URL")
            if url:
                source = url
        else:
            uploaded = st.file_uploader("Upload a .zip of the repo", type="zip")
            if uploaded:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
                tmp.write(uploaded.read())
                tmp.close()
                source = tmp.name

        if source and st.button("Run analysis"):
            with st.spinner("Ingesting and auditing — this runs build/tests and several LLM calls, may take a minute..."):
                client = LLMClient()
                ingest_result = ingest(source)

                if len(ingest_result.file_tree) > MAX_FILE_COUNT_FOR_LIVE_ANALYSIS:
                    st.error(
                        f"This repo has {len(ingest_result.file_tree)} files, over the "
                        f"{MAX_FILE_COUNT_FOR_LIVE_ANALYSIS} limit for live analysis on this "
                        f"public demo. Try a smaller repo, or run this locally (see reproduction guide)."
                    )
                    st.stop()

                logger = TrajectoryLogger()
                github_url = source if source_type == "GitHub URL" else None

                # Derive a stable per-repo ID so different repos don't
                # overwrite each other's saved reports — "live_repo" alone
                # would silently clobber the previous run's file every time.
                if github_url:
                    repo_id = "live_" + github_url.rstrip("/").split("/")[-1].replace(".git", "")
                else:
                    repo_id = f"live_upload_{int(time.time())}"

                def _run_full_analysis():
                    b = baseline_rate(repo_id, ingest_result, client)
                    a = audit_repo(
                        repo_id, ingest_result, client, logger,
                        github_url=github_url,
                        github_token=os.environ.get("GITHUB_TOKEN"),
                    )
                    return b, a

                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_run_full_analysis)
                        b_report, a_report = future.result(timeout=LIVE_ANALYSIS_TIMEOUT_SEC)
                except concurrent.futures.TimeoutError:
                    st.error(
                        f"Analysis exceeded the {LIVE_ANALYSIS_TIMEOUT_SEC}s limit for this "
                        f"public demo and was stopped. Try a smaller repo, or run this locally."
                    )
                    st.stop()

                if github_url:
                    save_audit_record(repo_id, github_url, a_report, SUPABASE_URL, SUPABASE_ANON_KEY)

                save_report(b_report, repo_id, "baseline")
                save_report(a_report, repo_id, "agent")

            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Baseline")
                st.markdown(f"### Baseline rating: {b_report.get('score', '—')}/10\n\n"
                             f"{b_report.get('reasoning', '(no reasoning returned)')}")
            with col2:
                st.subheader("Agent")
                st.markdown(_verdict_stamp(a_report.get("score")), unsafe_allow_html=True)
                st.markdown(render_business_report(a_report, repo_id))
                _pdf_download_button(a_report, repo_id, "live")
                _email_button(a_report, repo_id, "live")
                st.caption(f"Saved as `data/reports/{repo_id}__agent.json` for later inspection.")

with tab_history:
    if not (SUPABASE_URL and SUPABASE_ANON_KEY):
        st.info(
            "Audit history isn't configured on this deployment. Set SUPABASE_URL "
            "and SUPABASE_ANON_KEY to persist and browse past runs across sessions."
        )
    else:
        records = get_recent_audits(SUPABASE_URL, SUPABASE_ANON_KEY, limit=20)
        if not records:
            st.info("No audits recorded yet — run a live analysis above to populate this.")
        else:
            for r in records:
                badge = "✅" if r.get("integrity_passed") else "⚠️"
                st.write(
                    f"{badge} **{r.get('repo_name')}** — score {r.get('score')}/10, "
                    f"~{r.get('remediation_hours')}h to acquisition-ready "
                    f"— {r.get('created_at', '')[:19].replace('T', ' ')}"
                )
