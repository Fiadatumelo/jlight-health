#!/usr/bin/env python3
"""Validate JLIGHT's synthetic staging manifest without contacting any service.

This intentionally does not create users, write to a database, or call Supabase.
Provisioning requires controlled staging Auth/admin credentials and an explicit,
reviewed setup path; this tool only catches manifest mistakes before that step.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "staging_synthetic_manifest.json"
ALLOWED_DOMAINS = {"hospital", "laboratory", "bioinformatics", "clinical_trials"}
REQUIRED_SECRETS = {
    "JLIGHT_STAGING_BASE_URL",
    "JLIGHT_STAGING_USER_A_TOKEN",
    "JLIGHT_STAGING_USER_B_TOKEN",
    "JLIGHT_STAGING_ORG_A",
    "JLIGHT_STAGING_ORG_B",
}


def validate(manifest: dict) -> list[str]:
    errors: list[str] = []
    if manifest.get("classification") != "synthetic_only":
        errors.append("manifest classification must be synthetic_only")
    if manifest.get("never_use_production") is not True:
        errors.append("never_use_production must be true")
    orgs = {item.get("key"): item for item in manifest.get("organizations", [])}
    if set(orgs) != {"org_a", "org_b"}:
        errors.append("exactly org_a and org_b must be defined")
    elif orgs["org_a"].get("label") == orgs["org_b"].get("label"):
        errors.append("organization labels must differ")

    users = {item.get("key"): item for item in manifest.get("users", [])}
    if set(users) != {"user_a", "user_b"}:
        errors.append("exactly user_a and user_b must be defined")
    else:
        if users["user_a"].get("organization") != "org_a":
            errors.append("user_a must belong only to org_a")
        if users["user_b"].get("organization") != "org_b":
            errors.append("user_b must belong only to org_b")
        for user in users.values():
            if user.get("membership") != "active":
                errors.append(f"{user.get('key')} membership must be active")
            for domain, grants in user.get("domain_permissions", {}).items():
                if domain not in ALLOWED_DOMAINS:
                    errors.append(f"unsupported domain {domain}")
                if grants.get("can_write") and not grants.get("can_read"):
                    errors.append(f"{user.get('key')} {domain}: write requires read")
                if grants.get("can_report") and not grants.get("can_read"):
                    errors.append(f"{user.get('key')} {domain}: report requires read")
            if user.get("domain_permissions", {}).get("clinical_trials", {}).get("can_report"):
                errors.append("clinical_trials must not be included in operational patient-journey reporting")

    actual_secrets = set(manifest.get("secrets", {}).get("github_actions_secret_names", []))
    if actual_secrets != REQUIRED_SECRETS:
        errors.append("GitHub Actions secret names do not match the live authorization workflow")
    if manifest.get("secrets", {}).get("stored_in_git") is not False:
        errors.append("credentials must never be stored in Git")
    return errors


def main() -> int:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read synthetic manifest: {exc}")
        return 1
    errors = validate(manifest)
    if errors:
        print("FAIL: synthetic staging manifest validation")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS: synthetic manifest is internally consistent.")
    print("SAFE MODE: no network calls, credentials, user creation, or database writes performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
