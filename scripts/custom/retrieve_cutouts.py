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
    output_path = Path(snakemake.output[0])
    destination = output_path.parent

    # download cutouts
    if "zenodo" in config_cutouts["urls"]:
        download_and_unzip_zenodo(
            config_cutouts,
            destination,
            logger,
        )
    else:
        download_and_unzip_gdrive(
            config_cutouts,
            destination,
            logger,
        )

    if not output_path.exists():
        nc_files = list(destination.glob("*.nc"))

        if len(nc_files) == 1:
            nc_files[0].rename(output_path)
        elif len(nc_files) == 0:
            raise FileNotFoundError(
                f"No .nc file found in {destination} after downloading cutouts."
            )
        else:
            raise RuntimeError(
                f"Multiple .nc files found in {destination}: {nc_files}. "
                f"Cannot decide which one to use as {output_path}."
            )
