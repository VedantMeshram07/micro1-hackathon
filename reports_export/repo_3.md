# Due-Diligence Report: repo_3

## Verdict: 5/10 — Est. 6-10 engineer-hours to acquisition-ready

Process-Scheduler provides basic C++ CPU scheduling algorithm implementations, but lacks build/test integration, dependency manifests, and project licensing. Remediation is estimated at 8 total hours (range 6-10h) to establish automated testing.

---

## 💰 Remediation Cost Estimate

| Item | Hours | Basis |
|---|---|---|
| Stand up a working automated test suite | 8 | Flat estimate — tests did not run successfully during audit |

**Total: 8 hours (range: 6-10h)**

> Heuristic estimate based on the stated per-item assumptions above, not a professional engineering quote. Presented as a range (6-10h) to avoid false precision. Does not include general code-quality improvements beyond the specific findings listed.

---

## ⚠️ Risks
- **Lack of automated test runner or build system** — _Build/test pipeline reported no test runner configured for detected C++ files_
- **Buffer overflow and non-standard syntax risks in source code** — _File reviews for scheduler.cpp and priority.cpp note fixed array bounds (bt[10]) buffer overflow risks and non-standard C-style variable length arrays_
- **Missing project license specification** — _License check found no local LICENSE file in the repository_

## ✅ Strengths
- **Demonstrates multiple CPU scheduling algorithms** — _Source files implement Round Robin, FCFS, Priority, and Shortest Job First scheduling models with clear tabular output_
- **Zero external dependency footprint** — _Uses standard C++ libraries without third-party library dependencies_

## 📄 License
- Project license: **not found**

## ❓ Could Not Verify
- Automated test coverage and compilation behavior as no C++ build configuration (CMake/Makefile) was detected

---
*Every claim above is backed by evidence in the full JSON report — this is a summary view, not a separate assessment.*