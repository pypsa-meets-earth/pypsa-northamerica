# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import warnings

warnings.filterwarnings("ignore")
from scripts._helper import (
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
            "retrieve_cutouts",
            configfile="configs/calibration/config.base_AC.yaml",
            countries=["US"],
        )

    configure_logging(snakemake)

    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # load cutouts configuration
    config_cutouts = config["custom_databundles"]["bundle_cutouts_USA"]

    # destination for cutouts
    destination = os.path.join(PYPSA_EARTH_DIR, config_cutouts["destination"])

    # download cutouts
    downloaded = download_and_unzip_gdrive(
        config_cutouts, destination=destination, logger=logger
    )
