"""
Logs every step the product agent takes: what it was asked to do, what tool/
call it made, what came back, and what it decided next. This is the raw
material for the "Agent trajectories" submission deliverable — representative,
readable traces from agent instructions through to final result.

One JSONL file per repo run, written incrementally so a crash mid-run still
leaves a readable partial trajectory rather than losing everything.
"""

import json
import os
import time
import uuid


class TrajectoryLogger:
    def __init__(self, run_id: str | None = None, out_dir: str = "trajectories"):
        os.makedirs(out_dir, exist_ok=True)
        self.run_id = run_id or str(uuid.uuid4())[:8]
        self.path = os.path.join(out_dir, f"{self.run_id}.jsonl")
        self._step_num = 0

    def log_step(self, step_type: str, instruction: str, tool_input: dict | None,
                 tool_output: str, decision: str = "") -> None:
        """
        step_type: short label, e.g. 'gather_structure', 'run_tests', 'llm_review'
        instruction: what the agent was trying to do at this step, in plain language
        tool_input: what was actually sent to the tool/LLM (kept short — truncate upstream)
        tool_output: what came back (also keep this bounded before logging)
        decision: what the agent decided to do next / how this fed the next step
        """
        self._step_num += 1
        entry = {
            "run_id": self.run_id,
            "step": self._step_num,
            "timestamp": time.time(),
            "step_type": step_type,
            "instruction": instruction,
            "tool_input": tool_input,
            "tool_output": _truncate(tool_output, 4000),
            "decision": decision,
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def read_all(self) -> list:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


def _truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated, {len(text)} chars total]"
