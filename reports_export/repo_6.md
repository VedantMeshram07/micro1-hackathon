# Due-Diligence Report: repo_6

⚠️ *Self-audit flagged 16 finding(s) present in the underlying evidence but not reflected below — see the full JSON report for details.*

## Verdict: 7/10 — Est. 20-36 engineer-hours to acquisition-ready

CoolReader is an active C++/Android e-book reader repository with GPL-2.0 licensing, but contains potential secret findings in production code and lacks automated unit test configuration. Remediation is estimated at 28 total hours (range 20-36h) to rotate hardcoded credentials and establish automated unit testing.

---

## 💰 Remediation Cost Estimate

| Item | Hours | Basis |
|---|---|---|
| Rotate 20 hardcoded credential(s) found in production code | 20 | 1h per finding (rotate + remove from code + wire to secrets manager) |
| Stand up a working automated test suite | 8 | Flat estimate — tests did not run successfully during audit |

**Total: 28 hours (range: 20-36h)**

> Heuristic estimate based on the stated per-item assumptions above, not a professional engineering quote. Presented as a range (20-36h) to avoid false precision. Does not include general code-quality improvements beyond the specific findings listed.

---

## ⚠️ Risks
- **Hardcoded secret and credential findings in non-test source files** — _Secret scan flagged High-entropy string and hardcoded password findings in android\app\build.gradle (line 40) and android\jni\cr3java.cpp (line 305) with in_test_dir: false_
- **Lack of deep automated build and test integration for C++ ecosystem** — _Build/test pipeline reported no automated test execution for detected C++ codebase_

## ✅ Strengths
- **Active open-source maintenance and pull request activity** — _GitHub activity reports 30 open issues sampled and 27 recent merges sampled_
- **Valid open source license compliance** — _Project LICENSE file found with valid GPL-2.0 license_

## 📄 License
- Project license: **GPL-2.0** (`LICENSE`)

## 👥 Ownership & Continuity Risk
- 45 contributor(s), top contributor: 43.7% of commits, last push: 31 days ago

## ❓ Could Not Verify
- Native C/C++ compilation and crash handling behavior across all target Android architectures

---
*Every claim above is backed by evidence in the full JSON report — this is a summary view, not a separate assessment.*