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

import anthropic
import streamlit as st
import yaml
from dotenv import load_dotenv

from agent.audit_repo import audit_repo
from agent.trajectory_logger import TrajectoryLogger
from baseline.rate_repo import baseline_rate
from ingest.ingest import ingest
from report.generate_report import load_report, render_markdown

load_dotenv()
ENABLE_LIVE_INGEST = os.environ.get("ENABLE_LIVE_INGEST", "False") == "True"

st.set_page_config(page_title="Repo Due-Diligence Agent", layout="wide")
st.title("Is this repo actually good?")
st.caption("Evidence-based codebase due-diligence — baseline vs. agent, side by side.")

tab_browse, tab_live = st.tabs(["Browse eval-set reports", "Analyze a new repo"])

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
                st.markdown(render_markdown(baseline_report))
            else:
                st.warning("No cached baseline report — run eval/run_eval.py first.")

        with col2:
            st.subheader("Agent (evidence-based)")
            if agent_report:
                st.markdown(render_markdown(agent_report))
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
                client = anthropic.Anthropic()
                ingest_result = ingest(source)
                logger = TrajectoryLogger()

                b_report = baseline_rate("live_repo", ingest_result, client)
                a_report = audit_repo(
                    "live_repo", ingest_result, client, logger,
                    github_url=source if source_type == "GitHub URL" else None,
                    github_token=os.environ.get("GITHUB_TOKEN"),
                )

            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Baseline")
                st.markdown(render_markdown(b_report))
            with col2:
                st.subheader("Agent")
                st.markdown(render_markdown(a_report))
