Watched upstream changes detected. Manual review required.

- Changed upstream file: Snakefile
  Review target:
    - workflow/custom.smk
  Compare manually:
    git diff origin/main..upstream/main -- Snakefile

- Changed upstream file: scripts/prepare_sector_network.py
  Affected custom rule: prepare_sector_network_custom
  Parent upstream rule: prepare_sector_network
  Review target:
    - workflow/custom.smk
  Compare manually:
    git diff origin/main..upstream/main -- scripts/prepare_sector_network.py

