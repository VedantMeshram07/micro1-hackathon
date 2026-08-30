# Due-Diligence Report: repo_1

✅ *Self-audit passed: every finding this report gathered is cited below — nothing was dropped.*

## Verdict: 6/10 — Est. 6-10 engineer-hours to acquisition-ready

JavaScript Snake is a browser game repository with clean package installation and zero detected security vulnerabilities, but lacks an automated test suite. Remediation is estimated at 8 total hours (range 6-10h) to stand up proper automated testing.

---

## 💰 Remediation Cost Estimate

| Item | Hours | Basis |
|---|---|---|
| Stand up a working automated test suite | 8 | Flat estimate — tests did not run successfully during audit |

**Total: 8 hours (range: 6-10h)**

> Heuristic estimate based on the stated per-item assumptions above, not a professional engineering quote. Presented as a range (6-10h) to avoid false precision. Does not include general code-quality improvements beyond the specific findings listed.

---

## ⚠️ Risks
- **Lack of configured automated test suite** — _npm test failed with default stub error ('Error: no test specified')_
- **Declared dependencies are unpinned** — _Dependency evidence reports 2 unpinned dependencies out of 2 total declared in package.json_
- **Global namespace mutation in core scripts** — _File review for src\js\snake.js notes direct mutation of window.SNAKE global namespace and legacy attachEvent fallback_

## ✅ Strengths
- **Clean package installation and open source license compliance** — _npm install succeeded with valid MIT license and zero dependency license conflicts_
- **No credential leaks or known dependency vulnerabilities** — _Secret scan and OSV vulnerability scan found zero findings across all scanned files and packages_
- **Active repository maintenance history** — _GitHub activity shows 35 days since last push with 28 contributors_

## 📄 License
- Project license: **MIT** (`LICENSE`)
- Dependencies checked: 2, conflicts: 0, unknown license: 0

## 👥 Ownership & Continuity Risk
- 28 contributor(s), top contributor: 51.2% of commits, last push: 35 days ago

## ❓ Could Not Verify
- Containerized runtime execution as no Dockerfile or Docker Compose configuration was present

---
*Every claim above is backed by evidence in the full JSON report — this is a summary view, not a separate assessment.*