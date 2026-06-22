# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import warnings

warnings.filterwarnings("ignore")
from scripts.custom._helper import (
    PYPSA_EARTH_DIR,
    configure_logging,
    create_logger,
    download_and_unzip_gdrive,
    download_and_unzip_zenodo,
    mock_snakemake,
    update_config_from_wildcards,
)

logger = create_logger(__name__)


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "retrieve_osm_raw",
            configfile="configs/calibration/config.base_AC.yaml",
        )

    configure_logging(snakemake)

    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # load osm raw configuration
    config_osm_raw = config["custom_databundles"]["bundle_osm_raw_USA"]

    # destination for osm/raw
    destination = os.path.join(PYPSA_EARTH_DIR, snakemake.params.destination, "osm")

    # download osm/raw
    if "zenodo" in config_osm_raw["urls"]:
        downloaded = download_and_unzip_zenodo(
            config_osm_raw,
            destination,
            logger,
        )
    else:
        downloaded = download_and_unzip_gdrive(
            config_osm_raw,
            destination,
            logger,
        )
