# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import datetime as dt

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa

from scripts._helper import (
    BASE_PATH,
    configure_logging,
    create_logger,
    get_colors,
    mock_snakemake,
    update_config_from_wildcards,
)

logger = create_logger(__name__)


def parse_inputs():
    """
    Load all input data
    Parameters
    ----------
    Returns
    -------
    df_ba_demand: pandas dataframe
        Balancing Authority demand profiles
    gdf_ba_shape: geopandas dataframe
        Balancing Authority shapes
    df_utility_demand: geopandas dataframe
        Output of preprocess_demand_data - demand mapped to utility level shapes and holes
    pypsa_network: pypsa
        network to obtain pypsa bus information
    """

    df_ba_demand1 = pd.read_csv(snakemake.input.BA_demand_path1, index_col="period")
    df_ba_demand2 = pd.read_csv(snakemake.input.BA_demand_path2, index_col="period")
    df_ba_demand = df_ba_demand1._append(df_ba_demand2)
    df_ba_demand = df_ba_demand[~df_ba_demand.index.duplicated(keep="first")]
    df_ba_demand = df_ba_demand.replace(0, np.nan)
    df_ba_demand = df_ba_demand.dropna(axis=1)

    gdf_ba_shape = gpd.read_file(snakemake.input.BA_shape_path)
    gdf_ba_shape = gdf_ba_shape.to_crs(3857)

    df_utility_demand = gpd.read_file(snakemake.input.utility_demand_path)
    df_utility_demand.rename(columns={"index_right": "index_right_1"}, inplace=True)
    df_utility_demand = df_utility_demand.to_crs(3857)

    pypsa_network = pypsa.Network(snakemake.input.base_network)

    return df_ba_demand, gdf_ba_shape, df_utility_demand, pypsa_network


def build_demand_profiles(df_utility_demand, df_ba_demand, gdf_ba_shape, pypsa_network):
    """
    Build spatiotemporal demand profiles
    Parameters
    ----------
    df_utility_demand: geopandas dataframe
        Output of preprocess_demand_data - demand mapped to utility level shapes and holes
    df_ba_demand: pandas dataframe
        Balancing Authority demand profiles
    gdf_ba_shape: geopandas dataframe
        Balancing Authority shapes
    pypsa_network: pypsa
        network to obtain pypsa bus information
    Returns
    -------
    df_demand_bus_timeshifted: pandas dataframe
        bus-wise demand profiles
    """

    # Obtaining the centroids of the Utility demands
    df_utility_centroid = df_utility_demand.copy()
    df_utility_centroid.geometry = df_utility_centroid.geometry.centroid

    # Removing those shapes which do not have a representation in the demand timeseries data
    demand_columns = df_ba_demand.columns
    demand_columns = [x.split("_")[1] for x in demand_columns if x.endswith("_D")]
    drop_shape_rows = list(set(gdf_ba_shape["EIAcode"].tolist()) - set(demand_columns))
    gdf_ba_shape_filtered = gdf_ba_shape[~gdf_ba_shape["EIAcode"].isin(drop_shape_rows)]
    gdf_ba_shape_filtered.geometry = gdf_ba_shape_filtered.geometry.centroid
    gdf_ba_shape_filtered["color_ba"] = get_colors(len(gdf_ba_shape_filtered))

    df_utility_centroid = gpd.sjoin_nearest(
        df_utility_centroid, gdf_ba_shape_filtered, how="left"
    )
    df_utility_centroid.rename(columns={"index_right": "index_ba"}, inplace=True)

    # temporal scaling factor
    df_utility_centroid["temp_scale"] = df_utility_centroid.apply(
        lambda x: df_ba_demand[f"E_{x['EIAcode']}_D"].sum()
        / 1e3
        / x["Sales (Megawatthours)"],
        axis=1,
    )

    # Mapping demand utilities to nearest PyPSA bus
    df_reqd = pypsa_network.buses.query('carrier == "AC"')
    pypsa_gpd = gpd.GeoDataFrame(
        df_reqd, geometry=gpd.points_from_xy(df_reqd.x, df_reqd.y), crs=4326
    )
    pypsa_gpd = pypsa_gpd.to_crs(3857)
    pypsa_gpd["color"] = get_colors(len(pypsa_gpd))

    df_utility_centroid = gpd.sjoin_nearest(df_utility_centroid, pypsa_gpd, how="left")
    df_utility_centroid.rename(
        columns={"index_right": "PyPSA_bus", "Bus": "PyPSA_bus"}, inplace=True
    )

    df_demand_bus = pd.DataFrame(
        index=pd.to_datetime(df_ba_demand.index),
        columns=df_reqd.index.tolist(),
        data=0.0,
    )

    for col in df_demand_bus.columns:
        utility_rows = df_utility_centroid.query("PyPSA_bus == @col")
        for i in np.arange(0, len(utility_rows)):
            row = utility_rows.iloc[i]
            if not np.isnan(row["temp_scale"]):
                demand_data = df_ba_demand[f"E_{row['EIAcode']}_D"].copy()
                demand_data /= row["temp_scale"]
                demand_data /= 1000  # Converting to MWh
                df_demand_bus[col] += demand_data.tolist()

    # The EIA profiles start at 6:00:00 hours on 1/1 instead of 00:00:00 hours - rolling over the time series to start at 00:00 hours
    df_demand_bus_timeshifted = df_demand_bus[-9:-3]._append(df_demand_bus[:-9])
    df_demand_bus_timeshifted = df_demand_bus_timeshifted[:8760]
    df_demand_bus_timeshifted.index = pypsa_network.snapshots
    df_demand_bus_timeshifted.index.name = "time"
    logger.info(
        "Built demand_profiles.csv based on demand distribution using utility level and balancing authority demand data."
    )
    return df_demand_bus_timeshifted


def read_scaling_factor(demand_scenario, horizon):
    """
    Reads scaling factor for future projections
    Parameters
    ----------
    demand_scenario: str
        Future demand projection scenario
    horizon: int
        Horizon for demand projection
    Returns
    -------
    scaling_factor: pandas dataframe
        Scaling factor of demand projection scenario
    """
    horizon = (
        2024 if horizon == 2025 else horizon
    )  # select 2024 demand projection for 2025 horizon
    foldername = os.path.join(BASE_PATH, snakemake.params.demand_projections)
    filename = f"Scaling_Factor_{demand_scenario}_Moderate_{horizon}_by_state.csv"
    scaling_factor = pd.read_csv(os.path.join(foldername, filename), sep=";")
    scaling_factor["time"] = pd.to_datetime(scaling_factor["time"])
    logger.info(f"Read {filename} for scaling the demand for {horizon}.")
    return scaling_factor


def get_spatial_mapping(pypsa_network, gadm_shape_path, geo_crs):
    """
    Determines gadm to bus mapping
    Parameters
    ----------
    pypsa_network: netcdf file
        base.nc network
    gadm_shape_path: str
        path to gadm shape file
    geo_crs: str
        Geographical CRS
    Returns
    -------
    spatial_gadm_bus_mapping: pandas series
        Mapping of GADM regions to base network buses
    """
    # read gadm file
    gadm_shape = gpd.read_file(gadm_shape_path)

    # create geodataframe out of x and y coordinates of buses
    buses_gdf = gpd.GeoDataFrame(
        pypsa_network.buses,
        geometry=gpd.points_from_xy(pypsa_network.buses.x, pypsa_network.buses.y),
        crs=geo_crs,
    ).reset_index()

    # map gadm shapes to each bus
    spatial_gadm_bus_mapping = (
        buses_gdf.sjoin(gadm_shape, how="left", predicate="within")
        .set_index("Bus")["ISO_1"]
        .str.replace("US-", "")
    )
    return spatial_gadm_bus_mapping


def scale_demand_profiles(df_demand_profiles, spatial_gadm_bus_mapping, scaling_factor):
    """
    Scales demand profiles for each state based on the NREL EFS demand projections
    Parameters
    ----------
    df_demand_profiles: pandas dataframe
        Hourly demand profiles for buses of base network
    spatial_gadm_bus_mapping: pandas series
        Mapping of GADM regions to base network buses
    scaling_factor: pandas dataframe
        Hourly scaling factor per each state
    Returns
    -------
    scaled_demand_profiles: pandas dataframe
         Scaled demand profiles based on the demand projections
    """
    # convert demand_profiles from wide to long format
    df_demand_long = df_demand_profiles.melt(
        ignore_index=False, var_name="Bus", value_name="demand"
    )

    # map Bus IDs to State Codes
    df_demand_long["region_code"] = df_demand_long["Bus"].map(spatial_gadm_bus_mapping)

    # merge with scaling_factor DataFrame based on region_code and time
    df_demand_long.reset_index(inplace=True)
    scaling_factor["time"] = scaling_factor["time"].apply(
        lambda t: t.replace(year=df_demand_long["time"][0].year)
    )
    df_scaled = df_demand_long.merge(
        scaling_factor, on=["region_code", "time"], how="left"
    )
    del scaling_factor, df_demand_long

    # multiply demand by scaling factor
    df_scaled["scaling_factor"] = df_scaled["scaling_factor"].fillna(1)
    df_scaled["scaled_demand"] = df_scaled["demand"] * df_scaled["scaling_factor"]

    # pivot back to original wide format
    scaled_demand_profiles = df_scaled.pivot(
        index="time", columns="Bus", values="scaled_demand"
    )
    scaled_demand_profiles = scaled_demand_profiles[
        sorted(scaled_demand_profiles.columns)
    ]
    logger.info(f"Scaled demand based on scaling factor for each state.")

    return scaled_demand_profiles


def read_data_center_profiles(horizon, data_center_profiles_path):
    """
    Reads statewise data center profiles for given horizon
    Parameters
    ----------
    horizon: int
        Horizon of the data center profiles
    data_center_profiles_path: str
        Path to data center profiles file
    Returns
    -------
    statewise_data_center_load: pandas series
        Statewise data center demand for selected horizon
    """
    foldername = os.path.join(BASE_PATH, data_center_profiles_path)
    filename = f"data_center_profile_{horizon}_by_state.csv"
    data_center_profile = pd.read_csv(os.path.join(foldername, filename))
    statewise_data_center_load = data_center_profile.groupby("region_code")[
        "load_GW"
    ].mean()
    logger.info(f"Read {filename} for setting data center demands for {horizon}.")

    return statewise_data_center_load


def add_data_center_demand(
    df_demand_profiles, spatial_gadm_bus_mapping, data_center_demand
):
    """
    Adds data center demand to demand profile
    Parameters
    ----------
    df_demand_profiles: pandas dataframe
        Hourly demand profiles for each bus of base network
    spatial_gadm_bus_mapping: pandas series
        Mapping of GADM regions to base network buses
    data_center_profiles: pandas dataframe
        Hourly statewise data center profiles
    Returns
    -------
    df_demand_profiles: pandas dataframe
        Updated demand profiles with added data centers load
    """
    # Count total buses per region (excluding NaNs)
    region_counts = spatial_gadm_bus_mapping.value_counts(dropna=True)

    for bus in df_demand_profiles.columns:
        # gadm region where bus belongs
        bus_region = spatial_gadm_bus_mapping.loc[bus]

        if bus_region in data_center_demand.index:
            # data center demand for the gadm region in GW
            region_data_center_demand = data_center_demand.loc[bus_region]
            # take fraction of regional data center demand
            bus_data_center_demand = (
                region_data_center_demand * 1e3
            ) / region_counts.loc[bus_region]
            # add bus-level data center demand
            df_demand_profiles.loc[:, bus] += bus_data_center_demand

    logger.info(f"Update demand profiles by adding data center load.")
    return df_demand_profiles


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "build_demand_profiles_from_eia",
            configfile="configs/calibration/config.base.yaml",
        )

    configure_logging(snakemake)

    # set relevant paths
    plot_path = os.path.join(BASE_PATH, "plots/demand_modelling")
    os.makedirs(plot_path, exist_ok=True)

    df_ba_demand, gdf_ba_shape, df_utility_demand, pypsa_network = parse_inputs()

    df_demand_profiles = build_demand_profiles(
        df_utility_demand, df_ba_demand, gdf_ba_shape, pypsa_network
    )

    # get spatial GADM to bus mapping
    spatial_gadm_bus_mapping = get_spatial_mapping(
        pypsa_network, snakemake.input.gadm_shape, snakemake.params.geo_crs
    )

    # scale demand for future scenarios
    if snakemake.params.demand_horizon >= 2025:
        scaling_factor = read_scaling_factor(
            snakemake.params.demand_scenario, snakemake.params.demand_horizon
        )
        df_demand_profiles = scale_demand_profiles(
            df_demand_profiles, spatial_gadm_bus_mapping, scaling_factor
        )

    # set data center demand profiles
    if snakemake.config["demand_projection"]["data_centers_load"]:
        data_center_demand = read_data_center_profiles(
            snakemake.params.demand_horizon, snakemake.params.data_center_profiles
        )
        df_demand_profiles = add_data_center_demand(
            df_demand_profiles, spatial_gadm_bus_mapping, data_center_demand
        )

    # save demand_profiles.csv
    df_demand_profiles.to_csv(snakemake.output.demand_profile_path)
