# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))

warnings.filterwarnings("ignore")

from scripts.custom._helper import (
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
            "retrieve_electricity_network",
            configfile="configs/custom/scenarios/test/config.test.na.yaml",
        )

    configure_logging(snakemake)

    # Update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # Load electricity network bundle configuration
    config_electricity_network = config["custom_databundles"][
        "bundle_electricity_network_NA_test"
    ]

    # Destination for elec.nc
    output_path = Path(snakemake.output[0])
    destination = output_path.parent

    # Download electricity network
    if "zenodo" in config_electricity_network["urls"]:
        download_and_unzip_zenodo(
            config_electricity_network,
            destination,
            logger,
        )
    else:
        download_and_unzip_gdrive(
            config_electricity_network,
            destination,
            logger,
        )

    if not output_path.exists():
        raise FileNotFoundError(
            f"Expected downloaded electricity network not found: {output_path}"
        )
