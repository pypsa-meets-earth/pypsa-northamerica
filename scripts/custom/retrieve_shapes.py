# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys
from pathlib import Path

try:
    repo_dir = Path(snakemake.scriptdir).resolve().parents[1]
except NameError:
    repo_dir = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(repo_dir))

import warnings

warnings.filterwarnings("ignore")
from scripts.custom._helper import (
    PYPSA_EARTH_DIR,
    configure_logging,
    create_logger,
    download_and_unzip_gdrive,
    mock_snakemake,
    update_config_from_wildcards,
)

logger = create_logger(__name__)


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "retrieve_shapes",
            configfile="configs/calibration/config.base_AC.yaml",
        )

    configure_logging(snakemake)

    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # load shapes configuration
    config_shapes = config["custom_databundles"]["bundle_shapes_USA"]

    # destination for shapes
    destination = os.path.join(PYPSA_EARTH_DIR, snakemake.params.destination)

    # download shapes
    downloaded = download_and_unzip_gdrive(
        config_shapes, destination=destination, logger=logger
    )
