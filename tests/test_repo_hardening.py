"""Repo-level security-hardening regression checks (no Streamlit needed).

Run:  python tests/test_repo_hardening.py   (from the repo root)

Covers the config-file fixes from the 2026-10-15 security audit:
  M1 — browser.gatherUsageStats = false  (telemetry off)
  M2 — server.address = "127.0.0.1"      (loopback-only bind)
in every .streamlit/config.toml in the repo.
"""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
passed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


def main() -> None:
    configs = sorted(ROOT.rglob(".streamlit/config.toml"))
    check("config.toml files found", len(configs) >= 1,
          f"(found {len(configs)})")
    for cfg in configs:
        rel = cfg.relative_to(ROOT)
        with open(cfg, "rb") as fh:
            data = tomllib.load(fh)
        check(f"M1 telemetry off [{rel}]",
              data.get("browser", {}).get("gatherUsageStats") is False)
        check(f"M2 loopback bind [{rel}]",
              data.get("server", {}).get("address") == "127.0.0.1")

    # L1 — .gitignore must block BI artifacts, secrets, and the local audit report.
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pat in ("*.tmdl", "*.bim", "*.pbix", ".env", "SECURITY_AUDIT_REPORT.md"):
        check(f"L1 gitignore blocks {pat}", pat in gi)

    print(f"\nAll {passed} checks passed.")


if __name__ == "__main__":
    main()
