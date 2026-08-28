# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import pandas as pd
from _helper import DATA_DIR, PYPSA_EARTH_DIR

PPL_PATH = "original_custom_powerplants/original_custom_powerplants.csv"
COST_PATH = "resources/US_2023/costs_2020.csv"
NEW_PPL_PATH = "custom_powerplants.csv"


def read_custom_powerplants():
    """
    Reads the custom power plants data from a CSV file.

    Returns:
        pd.DataFrame: DataFrame containing the custom power plants data.
    """
    filepath = f"{DATA_DIR}/{PPL_PATH}"
    df = pd.read_csv(filepath, index_col=0)
    return df


def read_costs():
    """
    Reads the costs data from a CSV file.

    Returns:
        pd.DataFrame: DataFrame containing the costs data.
    """
    filepath = f"{PYPSA_EARTH_DIR}/{COST_PATH}"
    df = pd.read_csv(filepath, index_col=0)
    return df


if __name__ == "__main__":
    # read original custom powerplants
    df = read_custom_powerplants()
    # read costs file to get lifetime of powerplants
    costs_df = read_costs()
    # filter only lifetime rows from costs_df
    lifetime_df = costs_df[costs_df["parameter"] == "lifetime"]
    lifetime_series = lifetime_df["value"]
    lifetime_series.rename(
        index={"offwind": "offwind-ac", "battery storage": "battery"}, inplace=True
    )
    # set lifetime to CCGT and OCGT manually to 45 years and nuclear to 60 years
    lifetime_series["CCGT"] = 45
    lifetime_series["OCGT"] = 45
    lifetime_series["nuclear"] = 60
    # read lifetime from costs file
    df["lifetime"] = df["Fueltype"].map(lifetime_series)
    # update DatOut to be by DateIn + lifetime where DateOut is NaN
    df["DateOut"] = df.apply(
        lambda row: (
            row["DateIn"] + row["lifetime"]
            if pd.isna(row["DateOut"])
            else row["DateOut"]
        ),
        axis=1,
    )
    # drop lifetime column
    df.drop(columns=["lifetime"], inplace=True)
    # save updated DataFrame to CSV
    df.to_csv(f"{DATA_DIR}/{NEW_PPL_PATH}", index=True)
