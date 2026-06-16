# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa

warnings.filterwarnings("ignore")
from scripts.custom._helper import (
    PYPSA_EARTH_DIR,
    configure_logging,
    create_logger,
    download_and_unzip_gdrive,
    mock_snakemake,
    update_config_from_wildcards,
)

logger = create_logger(__name__)


def attach_emm_region_to_buses(network, path_shape, distance_crs):
    """
    Attach EMM region to buses
    """
    # Read the shapefile using geopandas
    shape = gpd.read_file(path_shape, crs=distance_crs)
    # shape.rename(columns={"GRID_REGIO": "region"}, inplace=True)

    ac_dc_carriers = ["AC", "DC"]
    location_mapping = network.buses.query("carrier in @ac_dc_carriers")[["x", "y"]]

    network.buses["x"] = network.buses["location"].map(location_mapping["x"]).fillna(0)
    network.buses["y"] = network.buses["location"].map(location_mapping["y"]).fillna(0)

    pypsa_gpd = gpd.GeoDataFrame(
        network.buses,
        geometry=gpd.points_from_xy(network.buses.x, network.buses.y),
        crs=4326,
    )

    network_columns = network.buses.columns
    bus_cols = [*network_columns, "subregion"]

    st_buses = gpd.sjoin_nearest(shape, pypsa_gpd, how="right")[bus_cols]

    network.buses["region"] = st_buses["subregion"]

    return network


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "set_custom_distribution_fees",
            simpl="",
            clusters="10",
            planning_horizons="2020",
            demand="AB",
            ll="copt",
            opts="24H",
            sopts="24H",
            discountrate="0.071",
            h2export="10",
            configfile="configs/calibration/config.base.yaml",
        )

    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    shape_path = snakemake.input.shape_path
    regional_fees_path = snakemake.input.regional_fees_path
    distance_crs = snakemake.params.distance_crs
    nc_path = snakemake.input.network
    horizon = (
        2023
        if int(snakemake.wildcards.planning_horizons) == 2020
        else int(snakemake.wildcards.planning_horizons)
    )

    regional_fees = pd.read_csv(regional_fees_path).fillna(0)
    network = pypsa.Network(nc_path)

    attach_emm_region_to_buses(network, shape_path, distance_crs)
    region_set = network.buses.region.unique()

    for region in region_set:
        region_buses = network.buses[network.buses.region.isin([region])]
        region_idx = region_buses.query("carrier == 'AC'").index

        if region_idx.empty:
            continue

        if region in regional_fees.region.unique():
            dist_fee = regional_fees[
                (regional_fees["Year"] == horizon) & (regional_fees["region"] == region)
            ]["Distribution nom USD/MWh"].iloc[0]

            mask = (network.links.bus0.isin(region_idx)) & (
                network.links.index.str.contains(" electricity distribution grid")
            )
            network.links.loc[mask, "marginal_cost"] = dist_fee
            logger.info(f"set distribution fee of {dist_fee} USD/MWh for {region}")

    network.export_to_netcdf(snakemake.output[0])
