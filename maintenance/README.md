# Upstream Watch

## Purpose

PyPSA-NorthAmerica contains custom workflow logic built on top of PyPSA-Earth.

Some custom rules:

* reuse upstream PyPSA-Earth rules (`use rule ... from pypsa_earth`)
* modify upstream rule inputs and outputs
* replace upstream scripts with custom implementations

As PyPSA-Earth evolves, changes in upstream files may require manual updates in the custom workflow.

The purpose of the upstream watch is to detect these potentially relevant upstream changes and notify developers that a review is needed.

The upstream watch **does not perform any automatic merge**.

---

## How it works

The watchlist is defined in:

```text
maintenance/upstream_watchlist.yaml
```

For each custom rule, the watchlist defines:

* the corresponding upstream rule
* the upstream script that should be monitored
* the files that should be reviewed if that upstream script changes

The check compares:

```text
origin/main
```

against:

```text
upstream/main
```

and reports any watched upstream files that changed.

The check is implemented in:

```text
scripts/dev/check_upstream_watchlist.py
```

and runs automatically through GitHub Actions:

```text
.github/workflows/upstream-watch.yml
```

---

## Running locally

Fetch the latest references:

```bash
git fetch origin main
git fetch upstream main
```

Run the check:

```bash
python scripts/dev/check_upstream_watchlist.py
```

---

## Understanding the output

Example:

```text
Watched upstream changes detected. Manual review required.

- Changed upstream file: scripts/prepare_sector_network.py
  Affected custom rule: prepare_sector_network_custom
  Parent upstream rule: prepare_sector_network
  Review target:
    - workflow/custom.smk
```

This means:

1. The upstream file `scripts/prepare_sector_network.py` changed.
2. The custom rule `prepare_sector_network_custom` depends on that upstream functionality.
3. A manual review is required.
4. The first file to inspect is `workflow/custom.smk`.

The warning **does not automatically imply that any code changes are needed**. It only means that the upstream change should be reviewed.

---

## What to do when the check fails

### Step 1 — Inspect the upstream change

For each reported file:

```bash
git diff origin/main..upstream/main -- <reported-file>
```

Example:

```bash
git diff origin/main..upstream/main -- scripts/prepare_sector_network.py
```

Read the upstream modification and understand what changed.

### Step 2 — Identify affected custom logic

Review the files listed under **Review target**.

Typical targets are:

```text
workflow/custom.smk
scripts/custom/*.py
```

Determine whether the upstream modification affects the corresponding custom implementation.

### Step 3 — Decide whether action is required

Possible outcomes:

#### No action required

The upstream change is unrelated to the North America custom workflow.

No code changes are needed.

#### Manual port required

The upstream change fixes a bug, adds functionality, changes inputs, or modifies behavior that should also be reflected in the custom workflow.

Manually implement the relevant change in the custom code.

### Step 4 — Create a synchronization branch

If changes are needed:

```bash
git checkout main
git pull origin main

git checkout -b sync/upstream-YYYYMMDD
```

Apply the required modifications.

Commit and open a pull request.

---

## Important

Do **not** blindly merge:

```bash
git merge upstream/main
```

PyPSA-NorthAmerica contains:

* custom workflow files
* custom scripts
* custom datasets
* custom configuration files

that do not exist in PyPSA-Earth.

A direct merge can create large numbers of irrelevant conflicts and misleading deletions.

The intended process is:

1. Detect upstream changes.
2. Review affected custom rules.
3. Manually port relevant modifications.
4. Open a dedicated synchronization PR.

---

## Updating the watchlist

When new custom rules are added, update:

```text
maintenance/upstream_watchlist.yaml
```

For each new custom rule, specify:

* upstream parent rule
* upstream parent script
* files that should be reviewed when upstream changes occur

The goal is to keep the mapping between custom functionality and upstream functionality explicit and maintainable.
