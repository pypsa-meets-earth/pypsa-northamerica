# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
from scripts._helper import create_logger, mock_snakemake, update_config_from_wildcards

logger = create_logger(__name__)


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "modify_aviation_demand",
            demand="AB",
            planning_horizons="2030",
            configfile="configs/scenarios/config.2030.yaml",
        )
    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # Extract aviation demand scenario configuration
    aviation_config = config["aviation_demand_scenario"]
    planning_horizon = str(snakemake.wildcards.planning_horizons)
    year = "2023" if planning_horizon == "2020" else planning_horizon
    scenario = aviation_config["scenario"]
    country = aviation_config["country"]

    # Read the energy totals and aviation demand data from CSV files
    energy_total = pd.read_csv(
        snakemake.input.energy_totals,
        index_col=0,
        keep_default_na=False,
        na_values=[""],
    )

    aviation_df = pd.read_csv(snakemake.input.aviation_demand, index_col=0)

    # Calculate the domestic and international aviation energy totals
    domestic = energy_total["total domestic aviation"][0]
    international = energy_total["total international aviation"][0]

    # Calculate the ratio of domestic and international aviation energy
    domestic_ratio = domestic / (domestic + international)
    international_ratio = international / (domestic + international)

    # Get the aviation demand for the specified scenario, country, and year
    aviation_demand = aviation_df[aviation_df.scenario == scenario].loc[country, (year)]
    conversion_factor = 3.96e-2  # Convert from Million Gallon to TWh
    aviation_demand_TWh = aviation_demand * conversion_factor

    # Update the energy totals with the new aviation demand
    energy_total.loc[country, "total domestic aviation"] = (
        aviation_demand_TWh * domestic_ratio
    )
    energy_total.loc[country, "total international aviation"] = (
        aviation_demand_TWh * international_ratio
    )

    # Save the updated energy totals back to the CSV file
    energy_total.to_csv(snakemake.output.energy_totals)
