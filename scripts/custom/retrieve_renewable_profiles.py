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
            "retrieve_renewable_profiles",
            configfile="configs/calibration/config.base_AC.yaml",
        )

    configure_logging(snakemake)

    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # load renewable_profiles configuration
    config_renewable_profiles = config["custom_databundles"][
        "bundle_renewable_profiles_USA"
    ]

    # destination for renewable_profiles/
    destination = os.path.join(PYPSA_EARTH_DIR, snakemake.params.destination)

    # url for alternative or voronoi clustering
    if snakemake.params.alternative_clustering:
        url = config_renewable_profiles["urls"]["alternative_clustering"]
    elif "zenodo" in config_renewable_profiles["urls"]:
        url = config_renewable_profiles["urls"]["zenodo"]
    else:
        url = config_renewable_profiles["urls"]["voronoi_clustering"]

    if "zenodo" in config_renewable_profiles["urls"]:
        downloaded = download_and_unzip_zenodo(
            config_renewable_profiles,
            destination,
            logger,
            url=url,
        )
    else:
        downloaded = download_and_unzip_gdrive(
            config_renewable_profiles,
            destination,
            logger,
            url=url,
        )
