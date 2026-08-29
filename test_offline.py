"""
Offline Test Suite for Repo Due-Diligence Agent.
Validates:
1. parse_json_response edge cases (clean JSON, fenced JSON, prose, <think> tags, preamble, cut-off reasoning, truncated JSON).
2. LLMClient.complete_json model-pool failover on unparseable reasoning output and clean error on pool exhaustion.
3. Full audit_repo pipeline execution against local repo (repos/JavaScript-Snake) using mock provider.

Usage:
    python test_offline.py
"""

import json
import os
import pytest
from llm.client import LLMClient, parse_json_response
from ingest.ingest import ingest
from agent.audit_repo import audit_repo
from agent.trajectory_logger import TrajectoryLogger


def test_parse_json_response_cases():
    print("[1/3] Testing parse_json_response edge cases...")

    # Case 1: Clean JSON
    res1 = parse_json_response('{"score": 8, "reasoning": "Clean"}')
    assert res1 == {"score": 8, "reasoning": "Clean"}

    # Case 2: Markdown fenced JSON
    res2 = parse_json_response('```json\n{"score": 8, "reasoning": "Fenced"}\n```')
    assert res2 == {"score": 8, "reasoning": "Fenced"}

    # Case 3: Leading/trailing prose
    res3 = parse_json_response('Sure, here is your answer: {"score": 8, "reasoning": "Prose"} Hope this helps!')
    assert res3 == {"score": 8, "reasoning": "Prose"}

    # Case 4: Explicit <think>...</think> block before JSON
    res4 = parse_json_response('<think>\nAnalyzing code structure...\nSelected score 8.\n</think>{"score": 8, "reasoning": "Think tags"}')
    assert res4 == {"score": 8, "reasoning": "Think tags"}

    # Case 5: Preamble before JSON
    res5 = parse_json_response("Here's a thinking process: 1. Read README 2. Form score\n{\"score\": 8, \"reasoning\": \"Preamble\"}")
    assert res5 == {"score": 8, "reasoning": "Preamble"}

    # Case 6: Pure reasoning trace cut off before any '{'
    try:
        parse_json_response("<think>Thinking process cut off before producing any JSON...")
        assert False, "Should have raised ValueError on cut-off reasoning trace"
    except ValueError as e:
        assert "Could not find JSON object" in str(e) or "reasoning trace" in str(e)

    # Case 7: Truncated JSON object
    try:
        parse_json_response('{"score": 8, "reasoning": "Truncated...')
        assert False, "Should have raised ValueError on truncated JSON"
    except ValueError as e:
        assert "Could not parse JSON" in str(e) or "Could not find JSON" in str(e)

    print("  [OK] All 7 parse_json_response test cases passed.")


def test_complete_json_pool_failover():
    print("\n[2/3] Testing complete_json automatic model pool failover & exhaustion...")
    
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["MOCK_MODEL"] = "bad-model-1,mock-model-2"

    client = LLMClient()
    assert client.get_active_model() == "bad-model-1"

    # bad-model-1 returns unparseable reasoning output without JSON;
    # complete_json should automatically advance to mock-model-2 and return valid parsed JSON.
    res = client.complete_json("Review this source file main.js")
    assert res["readability"] == "Good modular structure."
    assert client.get_active_model() == "mock-model-2"
    print("  [OK] Model pool successfully advanced from bad-model-1 to mock-model-2 on unparseable output.")

    # Test complete pool exhaustion clean error
    os.environ["MOCK_MODEL"] = "bad-model-1,bad-model-2"
    client_exhaust = LLMClient()
    try:
        client_exhaust.complete_json("Review this source file main.js")
        assert False, "Should have raised ValueError on complete pool exhaustion"
    except ValueError as e:
        assert "All pooled models exhausted without producing valid JSON" in str(e)
    print("  [OK] Clean error raised when all models in pool are exhausted.")


def test_offline_agent_pipeline():
    print("\n[3/3] Testing full agent audit pipeline offline against repos/JavaScript-Snake...")
    
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["MOCK_MODEL"] = "mock-model-1"

    repo_dir = os.path.join("repos", "JavaScript-Snake")
    if not os.path.exists(repo_dir):
        print("  ⚠ Skipping pipeline test: repos/JavaScript-Snake directory not found.")
        return

    ingest_result = ingest(repo_dir)
    client = LLMClient()
    logger = TrajectoryLogger(run_id="test_snake_offline")

    report = audit_repo("JavaScript-Snake", ingest_result, client, logger)
    assert report["score"] == 7
    assert report["method"] == "agent"
    assert "build_test" in report["raw_evidence"]
    assert "dependencies" in report["raw_evidence"]

    # Verify trajectory file created and contains steps
    assert os.path.exists(logger.path)
    steps = logger.read_all()
    assert len(steps) >= 4
    for step in steps:
        if step["step_type"] in ("llm_file_review", "synthesize_report"):
            assert "active_model" in step["tool_input"]

    print(f"  [OK] Full agent audit pipeline completed offline cleanly! Trajectory logged to {logger.path}")


if __name__ == "__main__":
    test_parse_json_response_cases()
    test_complete_json_pool_failover()
    test_offline_agent_pipeline()
    print("\n=== ALL OFFLINE TESTS PASSED SUCCESSFULLY ===")
