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
from report.generate_report import load_report, render_business_report

load_dotenv()
ENABLE_LIVE_INGEST = os.environ.get("ENABLE_LIVE_INGEST", "False") == "True"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

st.set_page_config(page_title="Repo Due-Diligence Agent", layout="wide")
st.title("Is this repo actually good?")
st.caption("Evidence-based codebase due-diligence — baseline vs. agent, side by side.")


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
                st.markdown(render_business_report(agent_report, selected))
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
                logger = TrajectoryLogger()
                github_url = source if source_type == "GitHub URL" else None

                b_report = baseline_rate("live_repo", ingest_result, client)
                a_report = audit_repo(
                    "live_repo", ingest_result, client, logger,
                    github_url=github_url,
                    github_token=os.environ.get("GITHUB_TOKEN"),
                )

                if github_url:
                    save_audit_record("live_repo", github_url, a_report, SUPABASE_URL, SUPABASE_ANON_KEY)

            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Baseline")
                st.markdown(f"### Baseline rating: {b_report.get('score', '—')}/10\n\n"
                             f"{b_report.get('reasoning', '(no reasoning returned)')}")
            with col2:
                st.subheader("Agent")
                st.markdown(render_business_report(a_report, "live_repo"))
                _email_button(a_report, "live_repo", "live")

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
