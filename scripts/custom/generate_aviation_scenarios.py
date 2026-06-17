# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
from scripts.custom._helper import (
    create_logger,
    mock_snakemake,
    update_config_from_wildcards,
)

logger = create_logger(__name__)


# Function to create a DataFrame for a specific scenario
def create_df_scenario(
    scenario_df, lower_year, upper_year, lower_scenario, upper_scenario, scenario_str
):
    base_df = scenario_df.copy()
    # Apply lower scenario growth rates
    for year in lower_year:
        base_df[year] = base_df[year - 1] * lower_scenario / 100 + base_df[year - 1]
    # Apply upper scenario growth rates
    for year in upper_year:
        base_df[year] = base_df[year - 1] * upper_scenario / 100 + base_df[year - 1]
    base_df["scenario"] = scenario_str
    return base_df


# Function to preprocess the aviation DataFrame
def preprocess_df(aviation_df):
    rename_col = {
        "Unnamed: 7": "state_fraction",
    }

    statename_to_abbr = {
        "Alabama": "AL",
        "Montana": "MT",
        "Alaska": "AK",
        "Nebraska": "NE",
        "Arizona": "AZ",
        "Nevada": "NV",
        "Arkansas": "AR",
        "New Hampshire": "NH",
        "California": "CA",
        "New Jersey": "NJ",
        "Colorado": "CO",
        "New Mexico": "NM",
        "Connecticut": "CT",
        "New York": "NY",
        "Delaware": "DE",
        "North Carolina": "NC",
        "Florida": "FL",
        "North Dakota": "ND",
        "Georgia": "GA",
        "Ohio": "OH",
        "Hawaii": "HI",
        "Oklahoma": "OK",
        "Idaho": "ID",
        "Oregon": "OR",
        "Illinois": "IL",
        "Dist. of Col.": "DC",
        "Pennsylvania": "PA",
        "Indiana": "IN",
        "Rhode Island": "RI",
        "Iowa": "IA",
        "South Carolina": "SC",
        "Kansas": "KS",
        "South Dakota": "SD",
        "Kentucky": "KY",
        "Tennessee": "TN",
        "Louisiana": "LA",
        "Texas": "TX",
        "Maine": "ME",
        "Utah": "UT",
        "Maryland": "MD",
        "Vermont": "VT",
        "Massachusetts": "MA",
        "Virginia": "VA",
        "Michigan": "MI",
        "Washington": "WA",
        "Minnesota": "MN",
        "West Virginia": "WV",
        "Mississippi": "MS",
        "Wisconsin": "WI",
        "Missouri": "MO",
        "Wyoming": "WY",
        "US Total": "US",
    }

    # Rename columns
    aviation_df = aviation_df.rename(columns=rename_col)
    # Select relevant columns
    aviation_df = aviation_df[["state_fraction", 2023]]

    # Drop unnecessary rows
    index_drop = [np.nan, "State-Level Total"]
    aviation_df = aviation_df.drop(index=index_drop)

    # Rename index to state abbreviations
    aviation_df = aviation_df.rename(index=statename_to_abbr)

    # Calculate US total fraction
    US_total_fraction = aviation_df["state_fraction"].iloc[1:].sum()
    aviation_df.loc["US", "state_fraction"] = round(US_total_fraction, 4)

    return aviation_df


# Function to define efficiency input values
def efficiency_input():
    low_scenario_lower_year_value = 1.4216
    low_scenario_upper_year_value = 1.3565
    central_scenario_lower_year_value = 1.2541
    central_scenario_upper_year_value = 0.5566
    high_scenario_lower_year_value = 1.0866
    high_scenario_upper_year_value = 0.0822

    lower_year_value = [i for i in range(2024, 2035)]
    upper_year_value = [i for i in range(2035, 2041)]

    return (
        low_scenario_lower_year_value,
        low_scenario_upper_year_value,
        central_scenario_lower_year_value,
        central_scenario_upper_year_value,
        high_scenario_lower_year_value,
        high_scenario_upper_year_value,
        lower_year_value,
        upper_year_value,
    )


# Function to compute scenarios based on the aviation DataFrame
def compute_scenario(aviation_df):
    (
        low_scenario_lower_year,
        low_scenario_upper_year,
        central_scenario_lower_year,
        central_scenario_upper_year,
        high_scenario_lower_year,
        high_scenario_upper_year,
        lower_year,
        upper_year,
    ) = efficiency_input()

    high = [
        low_scenario_upper_year,
        central_scenario_upper_year,
        high_scenario_upper_year,
    ]
    low = [
        low_scenario_lower_year,
        central_scenario_lower_year,
        high_scenario_lower_year,
    ]

    scenarios = ["low", "central", "high"]

    final_scenario_df = pd.DataFrame()

    # Create DataFrame for each scenario and concatenate them
    for x, y, z in zip(low, high, scenarios):
        scenario_df = create_df_scenario(aviation_df, lower_year, upper_year, x, y, z)
        final_scenario_df = pd.concat([final_scenario_df, scenario_df])

    return final_scenario_df


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "generate_aviation_scenario",
            configfile="configs/calibration/config.base_AC.yaml",
        )

    #  update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)
    aviation_data_path = snakemake.input.aviation_demand_data

    # Read the aviation demand data from the Excel file
    logger.info("Reading aviation demand data from Excel file.")
    aviation_demand = pd.read_excel(
        aviation_data_path,
        sheet_name="Aviation Demand Projection",
        header=1,
        index_col=0,
        skiprows=0,
    )

    logger.info("Preprocessing the aviation demand data.")
    data = preprocess_df(aviation_demand)

    logger.info("Computing the scenarios based on the preprocessed data.")
    final_scenario_df = compute_scenario(data)

    logger.info("Saving the final scenario DataFrame to a CSV file.")
    final_scenario_df.to_csv(
        snakemake.output.scenario_df, index=True, index_label="state"
    )
    logger.info("Process completed successfully.")
