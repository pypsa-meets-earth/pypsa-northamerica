# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Check whether watched PyPSA-Earth upstream files changed."""

import os
import subprocess
import sys
from pathlib import Path

import yaml

WATCHLIST = Path("maintenance/upstream_watchlist.yaml")


def git(*args: str) -> str:
    """Run git and return stdout."""
    return subprocess.check_output(["git", *args], text=True).strip()


def commits_touching_file(base_ref: str, upstream_ref: str, path: str) -> list[str]:
    """Return upstream commits that touched a file between refs."""
    output = git(
        "log",
        "--oneline",
        f"{base_ref}..{upstream_ref}",
        "--",
        path,
    )
    return output.splitlines() if output else []


def main() -> int:
    """Fail when watched upstream files changed."""
    if not WATCHLIST.exists():
        print(f"Missing watchlist: {WATCHLIST}")
        return 2

    with WATCHLIST.open() as f:
        config = yaml.safe_load(f)

    base_ref = os.environ.get(
        "UPSTREAM_WATCH_BASE_REF",
        config["base_ref"],
    )

    upstream_ref = os.environ.get(
        "UPSTREAM_WATCH_UPSTREAM_REF",
        config["upstream_ref"],
    )

    diff_output = git("diff", "--name-only", f"{base_ref}..{upstream_ref}")
    changed = set(diff_output.splitlines()) if diff_output else set()

    alerts = []

    for review_target, parent_files in config["watch"].items():
        if review_target == "rules":
            continue

        for parent_file in parent_files:
            if parent_file in changed:
                alerts.append(
                    {
                        "changed": parent_file,
                        "review": [review_target],
                        "parent_rule": None,
                        "custom_rule": None,
                    }
                )

    for custom_rule, rule_info in config["watch"].get("rules", {}).items():
        parent_script = rule_info["parent_script"]

        if parent_script in changed:
            alerts.append(
                {
                    "changed": parent_script,
                    "review": rule_info.get("review", []),
                    "parent_rule": rule_info.get("parent_rule"),
                    "custom_rule": custom_rule,
                }
            )

    if not alerts:
        print("No watched upstream files changed.")
        return 0

    print("Watched upstream changes detected. Manual review required.\n")

    for alert in alerts:
        print(f"- Changed upstream file: {alert['changed']}")

        if alert["custom_rule"]:
            print(f"  Affected custom rule: {alert['custom_rule']}")

        if alert["parent_rule"]:
            print(f"  Parent upstream rule: {alert['parent_rule']}")

        print("  Review target:")
        for target in alert["review"]:
            print(f"    - {target}")

        print(f"  Compare manually:")
        print(f"    git diff {base_ref}..{upstream_ref} -- {alert['changed']}")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
