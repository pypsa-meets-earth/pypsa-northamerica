# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import shutil
import warnings

warnings.filterwarnings("ignore")
from scripts.custom._helper import (
    configure_logging,
    create_logger,
    mock_snakemake,
    update_config_from_wildcards,
)

logger = create_logger(__name__)


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "retrieve_ssp2",
            configfile="configs/calibration/config.base_AC.yaml",
        )

    configure_logging(snakemake)

    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    old_northamerica_path = snakemake.input.old_path
    new_northamerica_path = snakemake.output.ssp2_northamerica
    nc_path = snakemake.params.nc_path

    if os.path.isfile(nc_path):
        os.path.exists(nc_path)
        os.remove(nc_path)
        logger.info(f"Removed {nc_path} file successfully")

    shutil.copy(old_northamerica_path, new_northamerica_path)
    logger.info(f"Retrieved NorthAmerica.csv file successfully")

    with open(snakemake.output.ssp2_dummy_output, "w") as f:
        f.write("success")
