# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import shutil
import sys
import warnings

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
warnings.filterwarnings("ignore")

from scripts.custom._helper import (
    PYPSA_EARTH_DIR,
    configure_logging,
    create_logger,
    mock_snakemake,
    update_config_from_wildcards,
)

logger = create_logger(__name__)

if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "prepare_growth_factors", configfile="configs/calibration/config.base.yaml"
        )

    configure_logging(snakemake)

    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    scenario = config["demand_projection"]["scenario"]
    source_file_1 = snakemake.input.source_growth_factors
    target_file_1 = snakemake.output.growth_factors_cagr

    source_file_2 = snakemake.input.source_industry_growth
    target_file_2 = snakemake.output.industry_growth_cagr

    os.makedirs(os.path.dirname(target_file_1), exist_ok=True)
    os.makedirs(os.path.dirname(target_file_2), exist_ok=True)

    for src, tgt in [(source_file_1, target_file_1), (source_file_2, target_file_2)]:
        if os.path.exists(src):
            shutil.copy(src, tgt)
            logger.info(
                f"The selected scenario is {scenario}, thus {src} is copied to {tgt}"
            )
        else:
            logger.warning(f"{src} does not exist.")
