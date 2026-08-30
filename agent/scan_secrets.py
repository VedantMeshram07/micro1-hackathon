"""
Two-layer secret/credential detection:
1. Known high-confidence patterns for major providers (AWS, GitHub, Slack,
   private key headers) — unambiguous when matched, essentially zero false
   positives, but only catches SPECIFIC known formats.
2. Generic Shannon-entropy detection on quoted string literals — catches
   ANY sufficiently random-looking secret regardless of provider, variable
   name, or code structure. This is the general-purpose approach real
   secret-scanners (TruffleHog, gitleaks, detect-secrets) use, since a
   fixed name/format list always has blind spots for anything novel.

Findings inside test directories are labeled as such rather than dropped —
real secrets are rarely deliberately committed in test fixtures (verified:
a signed-token test fixture in itsdangerous's own test suite was one false
positive found during calibration), so this is a legitimate signal
distinction, not a blind exclusion. Lock files (package-lock.json, etc.)
are excluded entirely — their hash-heavy content is structurally unsuited
to secret scanning, not a judgment call.

KNOWN LIMITATION: entropy detection cannot distinguish a random-looking
string used as a real secret from one used as a documentation example
(verified case: pydantic's own docs contain a base64 string demonstrating
its base64 type, which reads as high-entropy same as a real secret would).
No entropy-based scanner can fully solve this without deeper semantic
analysis — flagged here as a known, disclosed boundary, not a bug.

Never returns the actual matched secret text — only detection type, file,
and line number.
"""

import math
import os
import re
from collections import Counter

KNOWN_PATTERNS = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub Personal Access Token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("GitHub Fine-grained Token", re.compile(r"github_pat_[A-Za-z0-9_]{22,}")),
    ("Slack Token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Private Key Header", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
]

STRING_LITERAL = re.compile(r"['\"]([A-Za-z0-9+/_\-=]{20,})['\"]")

# Third detection layer: keyword-context matching. Entropy detection can
# ONLY catch machine-generated secrets — a human-chosen password like
# "admin123" or "CompanyPass2024" has low entropy (verified: 3.0 and 3.5
# respectively, both well under the 4.2 threshold) and will NEVER be
# caught by entropy alone, no matter how it's tuned. This layer catches
# that category instead: a value assigned to (or keyed by) a
# security-sensitive name, regardless of how random the value itself is.
# Combined with entropy via OR — each layer covers the other's blind spot.
KEYWORD_CONTEXT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|"
    r"access[_-]?key|auth[_-]?key|credential)\b['\"]?\s*[:=]\s*['\"]([^'\"]{3,})['\"]"
)

# Calibrated empirically against a real known secret (a hardcoded HL7 auth
# token) and a real clean repo (pallets/itsdangerous) — 4.2 is the lowest
# threshold that catches the true positive without adding false positives
# beyond the one legitimate test-fixture case (now handled separately, see
# TEST_DIR_HINTS below).
MIN_ENTROPY_BASE64 = 4.2
MIN_ENTROPY_HEX = 3.0
HEX_ONLY = re.compile(r"^[0-9a-fA-F]+$")

PLACEHOLDER_HINTS = ("example", "changeme", "your_", "xxxx", "placeholder", "dummy", "sample", "test_key")
TEST_DIR_HINTS = ("test", "tests", "spec", "specs", "__tests__", "fixtures")

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", "target"}
MAX_FILE_SIZE = 500_000

# Lock files are full of high-entropy package-integrity hashes by design —
# structurally unsuited to secret scanning, not a semantic judgment call
# like the test-dir/placeholder cases above. Verified: pdm.lock's revision
# hashes were the one clean false-positive category found during
# calibration against a real 489-file repo.
LOCK_FILE_NAMES = {
    "package-lock.json", "yarn.lock", "pdm.lock", "poetry.lock",
    "pipfile.lock", "cargo.lock", "uv.lock", "go.sum", "composer.lock",
}


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _looks_like_secret(candidate: str) -> bool:
    lower = candidate.lower()
    if any(hint in lower for hint in PLACEHOLDER_HINTS):
        return False
    if HEX_ONLY.match(candidate):
        return shannon_entropy(candidate) >= MIN_ENTROPY_HEX
    return shannon_entropy(candidate) >= MIN_ENTROPY_BASE64


def _looks_like_keyword_value(value: str) -> bool:
    """The keyword layer deliberately does NOT require high entropy — that
    would defeat its whole purpose, since it exists specifically to catch
    LOW-entropy human-chosen secrets. Only exclude clear non-secrets:
    placeholders, and references to environment/config lookups rather than
    literal values (e.g. os.environ.get('password') — 'password' there is
    a lookup KEY name, not the secret value, and won't match this pattern
    anyway since the regex requires the quoted string to directly follow
    ':' or '=', not '(')."""
    lower = value.lower()
    if any(hint in lower for hint in PLACEHOLDER_HINTS):
        return False
    if value.isupper() and "_" in value:
        return False  # looks like a CONSTANT_NAME reference, not a literal value
    return True


def _in_test_dir(rel_path: str) -> bool:
    parts = {p.lower() for p in rel_path.split(os.sep)}
    return bool(parts & set(TEST_DIR_HINTS))


def scan_for_secrets(repo_path: str, max_matches: int = 20) -> dict:
    findings = []
    files_scanned = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            if fname.lower() in LOCK_FILE_NAMES:
                continue
            fpath = os.path.join(root, fname)
            try:
                if os.path.getsize(fpath) > MAX_FILE_SIZE:
                    continue
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                files_scanned += 1
            except OSError:
                continue

            rel = os.path.relpath(fpath, repo_path)
            in_test = _in_test_dir(rel)

            for lineno, line in enumerate(lines, start=1):
                matched = False

                for label, pattern in KNOWN_PATTERNS:
                    if pattern.search(line):
                        findings.append({"file": rel, "line": lineno, "type": label, "in_test_dir": in_test})
                        matched = True
                        break
                if matched:
                    if len(findings) >= max_matches:
                        return {"files_scanned": files_scanned, "findings": findings, "truncated": True}
                    continue

                for candidate in STRING_LITERAL.findall(line):
                    if _looks_like_secret(candidate):
                        findings.append({
                            "file": rel, "line": lineno,
                            "type": "High-entropy string (possible secret)",
                            "in_test_dir": in_test,
                        })
                        if len(findings) >= max_matches:
                            return {"files_scanned": files_scanned, "findings": findings, "truncated": True}
                        matched = True
                        break
                if matched:
                    continue

                keyword_match = KEYWORD_CONTEXT.search(line)
                if keyword_match:
                    keyword, value = keyword_match.group(1), keyword_match.group(2)
                    if _looks_like_keyword_value(value):
                        findings.append({
                            "file": rel, "line": lineno,
                            "type": f"Hardcoded value assigned to '{keyword}' (low-entropy — not caught by randomness check)",
                            "in_test_dir": in_test,
                        })
                        if len(findings) >= max_matches:
                            return {"files_scanned": files_scanned, "findings": findings, "truncated": True}

    return {"files_scanned": files_scanned, "findings": findings, "truncated": False}
