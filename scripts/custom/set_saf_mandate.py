# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))
import numpy as np
import pandas as pd

from scripts.custom._helper import (
    configure_logging,
    create_logger,
    load_network,
    mock_snakemake,
    update_config_from_wildcards,
)

logger = create_logger(__name__)


def add_ekerosene_buses(n):
    """
    Adds e-kerosene buses and stores, and adds links between e-kerosene and oil bus
    """
    # get oil bus names
    oil_buses = n.buses.query("carrier in 'oil'")

    # add e-kerosene bus
    ekerosene_buses = [x.replace("oil", "e-kerosene") for x in oil_buses.index]
    n.madd(
        "Bus",
        ekerosene_buses,
        location=oil_buses.location.values,
        carrier="e-kerosene",
    )

    # add e-kerosene carrier
    n.add("Carrier", "e-kerosene", co2_emissions=n.carriers.loc["oil", "co2_emissions"])

    # add e-kerosene stores
    n.madd(
        "Store",
        [ekerosene_bus + " Store" for ekerosene_bus in ekerosene_buses],
        bus=ekerosene_buses,
        e_nom_extendable=True,
        e_cyclic=True,
        carrier="e-kerosene",
    )
    logger.info("Added E-kerosene buses, carrier, and stores")

    # add links between E-kerosene and Oil buses so excess synthetic oil can be used
    n.madd(
        "Link",
        [x + "-to-oil" for x in ekerosene_buses],
        bus0=ekerosene_buses,
        bus1=oil_buses.index,
        carrier="e-kerosene-to-oil",
        p_nom_extendable=True,
        efficiency=1.0,
    )
    logger.info("Added links between E-kerosene and Oil buses")

    # link all e-kerosene buses with E-kerosene-main bus if set in config
    if snakemake.params.non_spatial_ekerosene:
        ekerosene_main_bus = ["E-kerosene-main"]
        n.madd(
            "Bus",
            ekerosene_main_bus,
            location="E-kerosene-main",
            carrier="e-kerosene-main",
        )
        n.madd(
            "Link",
            [x + "-to-main" for x in ekerosene_buses],
            bus0=ekerosene_buses,
            bus1=ekerosene_main_bus,
            carrier="e-kerosene-to-main",
            p_nom_extendable=True,
            efficiency=1.0,
        )
        n.madd(
            "Link",
            [x.replace("e-kerosene", "main-to-e-kerosene") for x in ekerosene_buses],
            bus0=ekerosene_main_bus,
            bus1=ekerosene_buses,
            carrier="main-to-e-kerosene",
            p_nom_extendable=True,
            efficiency=1.0,
        )
        logger.info("Added links between E-kerosene buses and E-kerosene main bus")


def reroute_FT_output(n):
    """
    Reroutes output of Fischer-Tropsch from Oil to E-kerosene bus
    """
    ft_carrier = "Fischer-Tropsch"
    ft_links = n.links.query("carrier in @ft_carrier").index

    # switch bus1 of FT from oil to E-kerosene
    n.links.loc[ft_links, "bus1"] = n.links.loc[ft_links, "bus1"].str.replace(
        "oil", "e-kerosene"
    )
    logger.info("Rerouted Fischer-Tropsch output from Oil buses to E-kerosene buses")


def get_dynamic_blending_rate(config):
    """
    Extract the blending rate from data/saf_blending_rates/saf_scenarios.csv based on the planning horizon
    and the scenario specified in the config file (EU, EU+ or EU-)
    """
    saf_scenario = snakemake.params.saf_scenario
    year = str(snakemake.wildcards.planning_horizons)  # e.g. 2030 -> "2030"
    csv_path = snakemake.input.saf_scenarios
    df = pd.read_csv(csv_path, index_col=0)

    rate = df.loc[saf_scenario, year]

    logger.info(f"Blending rate for scenario {saf_scenario} in {year}: {rate}")
    return float(rate)


def redistribute_aviation_demand(n, rate):
    """
    Redistribute aviation demand to e-kerosene and kerosene based on blending rate
    """
    aviation_demand_carrier = "kerosene for aviation"
    total_aviation_demand = n.loads.query("carrier in @aviation_demand_carrier")

    # new kerosene for aviation demand = total * (1 - rate)
    n.loads.loc[total_aviation_demand.index, "p_set"] *= 1 - rate
    logger.info(
        f"Set kerosene for aviation to {(1 - rate) * 100:.1f}% of total aviation demand"
    )

    # add e-kerosene for aviation load
    n.madd(
        "Load",
        total_aviation_demand.index.str.replace("kerosene", "e-kerosene"),
        bus=total_aviation_demand.bus.str.replace("oil", "e-kerosene").values,
        carrier="e-kerosene for aviation",
        p_set=total_aviation_demand.p_set.fillna(0).values * rate,
    )
    logger.info(
        f"Added e-kerosene for aviation demand at the rate of {(rate * 100):.1f}% of total aviation demand"
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "set_saf_mandate",
            configfile="configs/scenarios/config.2040.yaml",
            simpl="",
            ll="copt",
            clusters=10,
            opts="24H",
            sopts="24H",
            planning_horizons=2040,
            discountrate="0.071",
            demand="AB",
        )

    configure_logging(snakemake)

    # update config based on wildcards
    config = update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # load the network
    n = load_network(snakemake.input.network)

    # add e-kerosene buses with store, and connect e-kerosene and oil buses
    add_ekerosene_buses(n)

    # reroute FT from oil buses to e-kerosene buses
    reroute_FT_output(n)

    # split aviation demand to e-kerosene to kerosene for aviation based on blending rate
    if config["saf_mandate"]["enable_mandate"]:
        rate = get_dynamic_blending_rate(config)
        redistribute_aviation_demand(n, rate)

    # save the modified network
    n.export_to_netcdf(snakemake.output.modified_network)
