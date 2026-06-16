# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import warnings

warnings.filterwarnings("ignore")
from scripts._helper import (
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
            "retrieve_base_network",
            configfile="configs/calibration/config.base_AC.yaml",
        )

    configure_logging(snakemake)

    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # load base.nc configuration
    config_base_network = config["custom_databundles"]["bundle_base_network_USA"]

    # destination for base.nc
    destination = os.path.dirname(snakemake.output[0])

    # download base.nc
    downloaded = download_and_unzip_gdrive(
        config_base_network, destination=destination, logger=logger
    )
