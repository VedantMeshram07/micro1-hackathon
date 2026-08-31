"""
Unified LLM client so the pipeline isn't locked to one provider. Select via
LLM_PROVIDER in .env — "anthropic", "gemini", "openrouter", "groq", "mock",
or "agent_queue". Default: anthropic.

MODEL POOLING: the *_MODEL env var for any provider can be a comma-separated
list, e.g. GROQ_MODEL=openai/gpt-oss-120b,openai/gpt-oss-20b. Free-tier
quotas are almost always per-model, not per-account — so listing several
models effectively stacks their daily budgets into one combined pool. When
the currently active model hits what looks like a *daily* cap, the client
automatically advances to the next model in the list rather than failing
the whole run. A single model (no comma) still works exactly as before.

Using Gemini's free tier? Stick to Flash or Flash-Lite, not Pro — Pro's free
quota is far too tight (roughly 5 requests/minute, 50/day as of mid-2026)
for a pipeline that makes ~7 calls per repo. Flash gives much more headroom
(~15 RPM, 1,000-1,500/day). Check ai.google.dev for current numbers before
you rely on this — free tier limits shift.

Using OpenRouter's free tier? Free (:free) models are capped at 20 RPM and
only 50 requests/day on an account with no credit history — jumping to
1,000/day permanently once you've ever added $10 in credits (that higher
limit sticks even if your balance later drops to $0). Failed attempts count
against the daily quota too, so a few retries eat into it fast.

Using Groq's free tier? Generally the most comfortable of the three — no
card needed, 30 RPM, and per-model daily caps in the hundreds to low
thousands of requests. The real constraint is often tokens/day (TPD), not
requests/day. Check console.groq.com for current per-model limits — the
free model catalogue and its limits both shift over time.

LLM_PROVIDER=mock returns canned responses for offline testing — no network,
no API key needed. See test_offline.py.

LLM_PROVIDER=agent_queue writes prompts to llm_queue/pending/ instead of
calling an API, and reads answers back from llm_queue/done/ — for having a
coding agent (e.g. Antigravity) generate responses directly instead of an
HTTP call. Workflow: run once to enqueue every prompt needed (repos will
come back with "_pending": true placeholders — expected), have the coding
agent process every file in llm_queue/pending/ and write matching answers
to llm_queue/done/, then clear data/reports/*.json and run again to pick up
the real answers.
"""

import hashlib
import json
import os
import re
import time


def parse_json_response(text: str) -> dict:
    """LLM responses that are supposed to be JSON-only aren't always clean —
    some models wrap output in markdown code fences or add a stray sentence,
    or emit reasoning traces like <think>...</think> or "Here's a thinking process:".
    Try progressively looser parsing before giving up, so a wrapped-but-valid
    JSON object doesn't get thrown away as unparseable."""
    text = text.strip()

    # Step 0: Strip explicit <think>...</think> blocks (clean non-greedy regex)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Step 0b: Strip leading preamble if reasoning text is present before first '{'
    if not text.startswith("{") and "{" in text:
        first_brace = text.find("{")
        text = text[first_brace:]

    # If after stripping there's no '{' at all (e.g. cut off during reasoning block), fail fast.
    if "{" not in text:
        raise ValueError(f"Could not find JSON object in model output (response may have been cut off during reasoning trace): {text[:300]}")

    # Attempt 1: parse as-is.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: strip markdown code fences (```json ... ``` or ``` ... ```).
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass

    # Attempt 3: grab the first {...} block, in case of leading/trailing prose.
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from model output: {text[:300]}")


class LLMClient:
    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

        if self.provider == "mock":
            self._client = None
            raw_models = os.environ.get("MOCK_MODEL", "mock-model-1,mock-model-2")

        elif self.provider == "agent_queue":
            # No API client at all — complete() writes prompts to a file
            # queue and reads answers back from another. See module docstring.
            self._client = None
            raw_models = os.environ.get("AGENT_QUEUE_MODEL", "antigravity-agent")

        elif self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
            raw_models = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

        elif self.provider == "gemini":
            from google import genai
            self._client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
            raw_models = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

        elif self.provider == "openrouter":
            from openai import OpenAI
            self._client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.environ.get("OPENROUTER_API_KEY"),
            )
            raw_models = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free")

        elif self.provider == "groq":
            from openai import OpenAI
            self._client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=os.environ.get("GROQ_API_KEY"),
            )
            # gpt-oss-120b's 200K TPD is the highest of the common free
            # models — listed first so it's tried before smaller-budget
            # models. Drop qwen models from default pool as gpt-oss models are well-behaved.
            raw_models = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b,openai/gpt-oss-20b")

        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider!r} (expected 'anthropic', 'gemini', 'openrouter', 'groq', 'mock', or 'agent_queue')")

        self._models = [m.strip() for m in raw_models.split(",") if m.strip()]
        self._model_index = 0

    def get_active_model(self) -> str:
        if self._model_index < len(self._models):
            return self._models[self._model_index]
        return "exhausted"

    def complete(self, prompt: str, max_tokens: int = 1000, retries: int = 4) -> str:
        """Returns the model's raw text response. Retries with backoff on
        transient errors within the current model. If an error looks like a
        *daily* quota cap, retrying that same model is pointless — instead,
        permanently advance to the next model in the pool (if any) for the
        rest of this run, since failed attempts often still count against
        the exhausted model's quota."""

        if self.provider == "agent_queue":
            os.makedirs("llm_queue/pending", exist_ok=True)
            os.makedirs("llm_queue/done", exist_ok=True)

            # Normalize transient test collection timing (e.g. "in 0.16s") before hashing
            normalized_prompt = re.sub(r"in \d+\.\d+s", "in 0.00s", prompt)
            prompt_id = hashlib.sha256(normalized_prompt.encode()).hexdigest()[:16]
            done_path = os.path.join("llm_queue/done", f"{prompt_id}.txt")
            pending_path = os.path.join("llm_queue/pending", f"{prompt_id}.txt")

            if os.path.exists(done_path):
                with open(done_path, "r", encoding="utf-8") as f:
                    return f.read()

            # Also check if any existing done file exists for this prompt hash without normalized timing
            raw_id = hashlib.sha256(prompt.encode()).hexdigest()[:16]
            raw_done = os.path.join("llm_queue/done", f"{raw_id}.txt")
            if os.path.exists(raw_done):
                with open(raw_done, "r", encoding="utf-8") as f:
                    return f.read()

            if not os.path.exists(pending_path):
                with open(pending_path, "w", encoding="utf-8") as f:
                    f.write(prompt)

            # Not answered yet — return a valid-JSON pending sentinel so
            # nothing downstream crashes; this call just needs to be
            # re-run once the coding agent has filled in llm_queue/done/.
            return f'{{"_pending": true, "prompt_id": "{prompt_id}"}}'

        last_err = None

        while self._model_index < len(self._models):
            model = self._models[self._model_index]
            exhausted_this_model = False

            for attempt in range(retries):
                try:
                    if self.provider == "mock":
                        return self._mock_response(prompt, model)
                    elif self.provider == "anthropic":
                        resp = self._client.messages.create(
                            model=model,
                            max_tokens=max_tokens,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        return resp.content[0].text.strip()
                    elif self.provider == "gemini":
                        resp = self._client.models.generate_content(
                            model=model,
                            contents=prompt,
                        )
                        return resp.text.strip()
                    else:  # openrouter or groq — both OpenAI-compatible, same call shape
                        resp = self._client.chat.completions.create(
                            model=model,
                            max_tokens=max_tokens,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        content = resp.choices[0].message.content
                        if content is None:
                            raise ValueError("Provider returned empty/null content — likely no model was actually available for this request despite a 200 response")
                        return content.strip()
                except Exception as e:
                    last_err = e
                    if "day" in str(e).lower():
                        exhausted_this_model = True
                        break  # stop retrying this model — won't recover within a backoff window
                    if attempt < retries - 1:
                        time.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s...
                        continue

            if not exhausted_this_model:
                raise last_err

            self._model_index += 1
            if self._model_index < len(self._models):
                print(f"[llm] {model} hit its daily quota — switching to {self._models[self._model_index]}")

        raise last_err

    def complete_json(self, prompt: str, max_tokens: int = 1000, retries: int = 2) -> dict:
        """Requests a completion and parses it as JSON. Retries the SAME
        model up to `retries` times before giving up on it — a malformed or
        truncated response is often a one-off stochastic issue, not a
        permanent model property, so moving to the next pooled model after
        just one bad response wastes good capacity for no reason. Only
        permanently advances self._model_index after the current model has
        failed to produce valid JSON `retries` times in a row. (Quota-driven
        advancement inside complete() is separate and unaffected by this.)

        BUG FIX (found live, reproduced empirically): if the pool was
        ALREADY fully exhausted by earlier complete_json() calls sharing
        this same client instance (e.g. the 5 file-review calls burning
        through both models before the final synthesis call even runs),
        the while loop below never executes even once, `last_err` stays
        at its initial None, and the function used to fall through to
        `raise ValueError(f"...: {last_err}")` — producing the literal,
        useless text "...without producing valid JSON: None". Confirmed
        via a controlled reproduction: setting self._model_index to the
        end of the pool before calling complete_json() reproduces this
        exact string. The check below catches that case up front with an
        actionable message instead."""
        if self._model_index >= len(self._models):
            raise ValueError(
                f"LLM pool already exhausted — all {len(self._models)} model(s) configured "
                f"for this session ({', '.join(self._models)}) were used up by earlier calls "
                f"in this same run (daily quota and/or repeated JSON-parse failures). No "
                f"models remain for this call; this repo's audit cannot complete on this "
                f"provider until quotas reset or a different provider/model is configured."
            )

        last_err = None

        while self._model_index < len(self._models):
            model = self._models[self._model_index]
            parse_failures = 0

            while parse_failures < retries:
                try:
                    raw = self.complete(prompt, max_tokens=max_tokens, retries=2)
                    return parse_json_response(raw)
                except ValueError as e:
                    last_err = e
                    parse_failures += 1
                    print(f"[llm] {model} produced unparseable JSON (attempt {parse_failures}/{retries}) — retrying same model")

            print(f"[llm] {model} failed to produce valid JSON after {retries} attempts — advancing to next pooled model")
            self._model_index += 1

        raise ValueError(f"All pooled models exhausted without producing valid JSON: {last_err}")

    def _mock_response(self, prompt: str, model: str) -> str:
        """Generates realistic mock LLM responses for offline testing."""
        if "bad-model" in model:
            # Deliberately malformed output with no JSON to test pool advancement
            return "Here's a thinking process: 1. I need to audit this repo. 2. Thinking..."
        if "rate this repository" in prompt.lower():
            return json.dumps({"score": 7, "reasoning": "Mock baseline gut impression: clean file tree and standard README."})
        elif "review this source file" in prompt.lower():
            return json.dumps({
                "readability": "Good modular structure.",
                "error_handling": "Basic try-catch blocks present.",
                "concerns": ["Potential unhandled exception on invalid config."],
                "notable_strengths": ["Clean separation of concerns."]
            })
        else:
            return json.dumps({
                "score": 7,
                "summary": "Mock synthesis report: solid project structure with passing tests.",
                "strengths": [{"point": "Dependencies defined", "evidence": "package.json found"}],
                "risks": [{"point": "Unpinned dependencies", "evidence": "package.json caret dependencies"}],
                "unverifiable": ["Live deployment performance"]
            })
