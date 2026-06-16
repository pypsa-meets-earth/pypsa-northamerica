# SPDX-FileCopyrightText:  Open Energy Transition gGmbH
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
from scripts.custom._helper import mock_snakemake, update_config_from_wildcards


def plot_consumption_per_passenger(final_data):
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(
        x=final_data["State"], height=final_data["Consumption per Passenger (barrels)"]
    )
    ax.set_xlabel("State")
    ax.set_ylabel("Consumption per Passenger (barrels)")
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    plt.xticks(fontsize=8)
    plt.margins(x=0.01)
    plt.savefig(
        snakemake.output.consumption_per_passenger, bbox_inches="tight", dpi=300
    )
    logging.info(f"{snakemake.output.consumption_per_passenger} was saved")


def plot_comparision_consumption_passengers(df):
    fig, ax1 = plt.subplots(figsize=(12, 3))
    bar_width = 0.8
    bars = ax1.bar(
        df["State"],
        df["Passengers"],
        width=bar_width,
        alpha=0.5,
        color="skyblue",
        label="Passengers",
    )
    ax2 = ax1.twinx()
    line = ax2.plot(
        df["State"],
        df["Consumption (thousand barrels)"] / 1e3,
        color="red",
        marker="o",
        label="Consumption",
    )
    ax1.set_xlabel("State", fontsize=10)
    ax1.set_ylabel("Passengers", fontsize=10)
    ax2.set_ylabel("Consumption (million barrels)", fontsize=10)
    plt.title(
        "State-wise Comparison of Passengers and Fuel Consumption", pad=5, fontsize=11
    )
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=9)
    ax1.set_xticklabels(df["State"], rotation=0, ha="center", fontsize=7.5)
    ax1.margins(x=0.01)
    plt.savefig(
        snakemake.output.comparision_consumption_passengers,
        bbox_inches="tight",
        dpi=300,
    )
    logging.info(f"{snakemake.output.comparision_consumption_passengers} was saved")


def calculate_correlation(final_data):
    corr = final_data[["Consumption (thousand barrels)", "Passengers"]].corr()

    fig, ax = plt.subplots(figsize=(10, 9))  # Set figure size
    cax = ax.matshow(corr, cmap="Blues", vmin=0, vmax=1)  # Use matshow for heatmap

    # Add a color bar
    colorbar = fig.colorbar(cax)
    colorbar.ax.tick_params(labelsize=12)
    labels = ["Consumption\n(thousand barrels)", "Passengers"]
    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.columns)))
    ax.set_xticklabels(labels, rotation=0, fontsize=16)  # Rotate for readability
    ax.set_yticklabels(labels, fontsize=16)

    # Annotate each cell with the correlation value
    for (i, j), value in np.ndenumerate(corr):
        ax.text(
            j, i, f"{value:.3f}", ha="center", va="center", color="white", fontsize=18
        )

    # Add title
    plt.title("Correlation Matrix", pad=20, fontsize=18)
    plt.savefig(snakemake.output.correlation_matrix, bbox_inches="tight", dpi=300)
    logging.info(f"{snakemake.output.correlation_matrix} was saved")

    return corr.iloc[0, 1]


def get_percentage_information(final_data):
    # Calculate the total passengers and total consumption for percentage calculations
    total_passengers_all_states = final_data["Passengers"].sum()
    total_consumption_all_states = final_data["Consumption (thousand barrels)"].sum()

    # Calculate the percentage of consumption and passengers per state, rounding to two decimal places
    final_data["Consumption (%)"] = (
        (final_data["Consumption (thousand barrels)"] / total_consumption_all_states)
        * 100
    ).round(2)

    final_data["Passengers (%)"] = (
        (final_data["Passengers"] / total_passengers_all_states) * 100
    ).round(2)

    return final_data


def merge_airport_data(airports_df, passengers_df, aviation_df):
    def get_statewise_fraction(row):
        # Calculate fraction for each airport based on the total passenger
        # for each corresponding state

        state = row.iso_region
        state_passenger_total = statewise_passengers.loc[state, "passengers"]
        state_wise_fraction = row.passengers / state_passenger_total
        return state_wise_fraction

    def get_fraction(row):
        # Calculate the fraction of passengers for each airport based on
        # statewise fraction for each airports and the state fraction from total US demand

        state = row.iso_region
        state_fraction = aviation_df.loc[state, "state_fraction"].iloc[0]
        fraction = state_fraction * row.statewise_fraction
        return fraction

    # Merge the airports and passengers data
    merged_data = pd.merge(
        airports_df,
        passengers_df,
        left_on="iata_code",
        right_on="origin",
        how="inner",
    )

    merged_data = merged_data.drop(columns=["OBJECTID"])
    statewise_passengers = merged_data.groupby(["iso_region"])[["passengers"]].sum()
    merged_data["statewise_fraction"] = merged_data.apply(
        get_statewise_fraction, axis=1
    )
    merged_data.loc[:, "fraction"] = merged_data.apply(get_fraction, axis=1)

    # merged_data["fraction"] = merged_data["fraction"].fillna(0)
    merged_data.rename(
        columns={
            "iso_country": "country",
            "longitude_deg": "x",
            "latitude_deg": "y",
        },
        inplace=True,
    )

    merged_data.to_csv(snakemake.output.merged_data, index=False)
    logging.info(f"merged data saved to {snakemake.output.merged_data}")

    merged_data.to_csv(snakemake.output.custom_airports_data, index=False)
    logging.info(f"merged data saved to {snakemake.output.custom_airports_data}")

    return merged_data


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake("process_airport_data")

    #  update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # Load the CSV files
    airports = pd.read_csv(snakemake.input.airport_data)
    market_data = pd.read_csv(snakemake.input.passengers_data)
    fuel_data = pd.read_csv(
        snakemake.input.fuel_data
    )  # Load the fuel consumption data file
    aviation_demand = pd.read_csv(
        snakemake.input.aviation_demand, index_col=0
    )  # Load the aviation demand data file

    # Filter the airports file to keep only US airports
    airports_us = airports[airports["iso_country"] == "US"].copy()

    # Remove the 'US-' prefix from 'iso_region'
    airports_us["iso_region"] = airports_us["iso_region"].str.replace(
        "US-", "", regex=False
    )

    merge_airport_data(airports_us, market_data, aviation_demand)

    # Merge `market_data` with `airports_us` to get the ISO region for each airport
    merged_check = pd.merge(
        market_data,
        airports_us[["iata_code", "iso_region"]],
        left_on="origin",
        right_on="iata_code",
        how="left",
        indicator=True,
    )

    # Identify unmatched origins and calculate the total passengers excluded
    unmatched_origins = merged_check[merged_check["_merge"] == "left_only"]
    excluded_passengers_total = unmatched_origins["passengers"].sum()
    total_passengers = market_data["passengers"].sum()
    excluded_percentage = (excluded_passengers_total / total_passengers) * 100

    logging.info("Unmatched airports:")
    logging.info(str(unmatched_origins["origin"].unique()))
    logging.info(
        f"\nTotal passengers from unmatched airports: {excluded_passengers_total}"
    )
    logging.info(f"% of passengers from unmatched airports: {excluded_percentage:.2f}%")

    # Calculate the total passengers for matched airports
    matched_passengers_total = merged_check[merged_check["_merge"] == "both"][
        "passengers"
    ].sum()
    logging.info(f"Total passengers from matched airports: {matched_passengers_total}")

    # Filter only the rows that have a match
    matched_data = merged_check[merged_check["_merge"] == "both"]

    # Group by 'iso_region' and sum the passengers for each state
    passengers_per_state = (
        matched_data.groupby("iso_region")["passengers"].sum().reset_index()
    )

    # Rename columns for clarity
    passengers_per_state.rename(
        columns={"iso_region": "State", "passengers": "Passengers"}, inplace=True
    )

    # Filter the fuel data to keep only rows where 'MSN' equals 'JFACP' (data in thousand barrels)
    fuel_data_filtered = fuel_data[fuel_data["MSN"] == "JFACP"].copy()

    # Rename the column '2023' to 'Consumption (kbarrel)' for clarity
    fuel_data_filtered = fuel_data_filtered[["State", "2023"]]
    fuel_data_filtered.rename(
        columns={"2023": "Consumption (thousand barrels)"}, inplace=True
    )

    # Merge passenger and consumption data by state
    final_data = pd.merge(
        passengers_per_state, fuel_data_filtered, on="State", how="left"
    )

    # write consumption and passenger percentages over total
    final_data = get_percentage_information(final_data)

    # Estimate fuel consumption per passenger for each state
    final_data["Consumption per Passenger (barrels)"] = (
        1e3 * final_data["Consumption (thousand barrels)"] / final_data["Passengers"]
    ).round(4)

    # Plot Consumption per Passenger for each state
    plot_consumption_per_passenger(final_data)
    plot_comparision_consumption_passengers(final_data)

    # Calculate correlation coefficient between Consumption and Passengers
    correlation_coefficient = calculate_correlation(final_data)
    logging.info(
        f"Correlation coefficient between Consumption and Passengers: {correlation_coefficient}"
    )

    # Calculate the difference in percentage between passengers and consumption, rounding to two decimal places
    final_data["Consumption-passenger mismatch (%)"] = (
        final_data["Passengers (%)"] - final_data["Consumption (%)"]
    ).round(2)

    # Save the result to a new CSV file
    final_data.to_csv(snakemake.output.statewise_output, index=False)
    logging.info(
        f"The file '{snakemake.output.statewise_output}' has been created with the required columns and formatted percentages."
    )
