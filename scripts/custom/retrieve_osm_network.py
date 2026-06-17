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
            "retrieve_osm_network",
            configfile="configs/calibration/config.base_AC.yaml",
        )

    configure_logging(snakemake)

    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # load base_network configuration
    config_osm_network = config["custom_databundles"]["bundle_osm_network_USA"]

    # destination for base_network/
    destination = os.path.join(PYPSA_EARTH_DIR, snakemake.params.destination)

    # download base_network/
    if "zenodo" in  config_osm_network["urls"]:
        downloaded = download_and_unzip_zenodo(
            config_osm_network,
            destination,
            logger,
        )
    else:
        downloaded = download_and_unzip_gdrive(
            config_osm_network,
            destination,
            logger,
        )