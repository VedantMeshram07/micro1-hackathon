"""
Baseline: what a person skimming an unfamiliar repo for two minutes would do —
read the README, glance at the file tree, form a gut impression. One prompt,
no build/test execution, no dependency or PR/issue mining. This is the thing
your agent needs to beat, so keep it honestly weak, not a strawman.
"""

import json
import os

import anthropic

from ingest.ingest import IngestResult

BASELINE_PROMPT = """You are quickly skimming an unfamiliar code repository to \
form a first impression of its quality — the way a busy person glancing at it \
for two minutes would. You only have the README and the file tree. You have \
NOT run the code, the tests, or checked dependencies.

Repository: {repo_name}

README:
---
{readme}
---

File tree ({file_count} files{truncated_note}):
{file_tree}

Rate this repository's likely quality from 1 (poor) to 10 (excellent), based \
only on this surface-level impression. Respond ONLY with valid JSON, no other \
text, in exactly this shape:
{{"score": <int 1-10>, "reasoning": "<2-3 sentence gut-impression explanation>"}}
"""


def baseline_rate(repo_name: str, ingest_result: IngestResult, client: anthropic.Anthropic) -> dict:
    file_tree_preview = "\n".join(ingest_result.file_tree[:200])
    truncated_note = " — truncated" if ingest_result.truncated else ""

    prompt = BASELINE_PROMPT.format(
        repo_name=repo_name,
        readme=ingest_result.readme_text[:6000] or "(no README found)",
        file_count=len(ingest_result.file_tree),
        truncated_note=truncated_note,
        file_tree=file_tree_preview,
    )

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    resp = client.messages.create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Model didn't return clean JSON — don't crash the eval run over it,
        # surface it as a low-confidence result instead.
        result = {"score": None, "reasoning": f"Could not parse model output: {text[:200]}"}

    result["method"] = "baseline"
    result["repo"] = repo_name
    return result
