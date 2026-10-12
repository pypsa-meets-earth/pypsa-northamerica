Watched upstream changes detected. Manual review required.

- Changed upstream file: Snakefile
  Review target:
    - workflow/custom.smk
  Compare manually:
    git diff origin/main..upstream/main -- Snakefile

- Changed upstream file: scripts/build_demand_profiles.py
  Affected custom rule: build_demand_profiles_custom
  Parent upstream rule: build_demand_profiles
  Review target:
    - workflow/custom.smk
  Compare manually:
    git diff origin/main..upstream/main -- scripts/build_demand_profiles.py

- Changed upstream file: scripts/add_export.py
  Affected custom rule: add_export_custom
  Parent upstream rule: add_export
  Review target:
    - workflow/custom.smk
  Compare manually:
    git diff origin/main..upstream/main -- scripts/add_export.py

- Changed upstream file: scripts/prepare_sector_network.py
  Affected custom rule: prepare_sector_network_custom
  Parent upstream rule: prepare_sector_network
  Review target:
    - workflow/custom.smk
  Compare manually:
    git diff origin/main..upstream/main -- scripts/prepare_sector_network.py

- Changed upstream file: scripts/solve_network.py
  Affected custom rule: solve_sector_network_custom
  Parent upstream rule: solve_sector_network
  Review target:
    - workflow/custom.smk
  Compare manually:
    git diff origin/main..upstream/main -- scripts/solve_network.py

- Changed upstream file: scripts/solve_network.py
  Affected custom rule: solve_network_myopic_custom
  Parent upstream rule: solve_network_myopic
  Review target:
    - workflow/custom.smk
  Compare manually:
    git diff origin/main..upstream/main -- scripts/solve_network.py

- Changed upstream file: scripts/solve_network.py
  Affected custom rule: solve_custom_sector_network
  Parent upstream rule: solve_sector_network
  Review target:
    - workflow/custom.smk
    - scripts/custom/solve_custom_sector_network.py
  Compare manually:
    git diff origin/main..upstream/main -- scripts/solve_network.py

