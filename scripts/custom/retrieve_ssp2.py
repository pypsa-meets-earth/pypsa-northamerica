# SPDX-FileCopyrightText: Open Energy Transition gGmbH
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import shutil
from pathlib import Path

from scripts.custom._helper import configure_logging, create_logger

logger = create_logger(__name__)


if __name__ == "__main__":
    configure_logging(snakemake)

    source = Path(snakemake.input.old_path)
    target = Path(snakemake.output.ssp2_northamerica)

    if not source.exists():
        raise FileNotFoundError(f"Missing source demand file: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)

    logger.info(f"Copied {source} to {target}")
