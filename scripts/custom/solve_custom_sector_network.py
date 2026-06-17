# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Solves linear optimal power flow for a network iteratively while updating
reactances.

Relevant Settings
-----------------

.. code:: yaml

    solving:
        tmpdir:
        options:
            formulation:
            clip_p_max_pu:
            load_shedding:
            noisy_costs:
            nhours:
            min_iterations:
            max_iterations:
            skip_iterations:
            track_iterations:
        solver:
            name:

.. seealso::
    Documentation of the configuration file ``config.yaml`` at
    :ref:`electricity_cf`, :ref:`solving_cf`, :ref:`plotting_cf`

Inputs
------

- ``networks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc``: confer :ref:`prepare`

Outputs
-------

- ``results/networks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc``: Solved PyPSA network including optimisation results

    .. image:: /img/results.png
        :width: 40 %

Description
-----------

Total annual system costs are minimised with PyPSA. The full formulation of the
linear optimal power flow (plus investment planning)
is provided in the
`documentation of PyPSA <https://pypsa.readthedocs.io/en/latest/optimal_power_flow.html#linear-optimal-power-flow>`_.
The optimization is based on the :func:`network.optimize` function.
Additionally, some extra constraints specified in :mod:`prepare_network` and :mod:`solve_network` are added.

Solving the network in multiple iterations is motivated through the dependence of transmission line capacities and impedances on values of corresponding flows.
As lines are expanded their electrical parameters change, which renders the optimisation bilinear even if the power flow
equations are linearized.
To retain the computational advantage of continuous linear programming, a sequential linear programming technique
is used, where in between iterations the line impedances are updated.
Details (and errors introduced through this heuristic) are discussed in the paper

- Fabian Neumann and Tom Brown. `Heuristics for Transmission Expansion Planning in Low-Carbon Energy System Models <https://arxiv.org/abs/1907.10548>`_), *16th International Conference on the European Energy Market*, 2019. `arXiv:1907.10548 <https://arxiv.org/abs/1907.10548>`_.

.. warning::
    Capital costs of existing network components are not included in the objective function,
    since for the optimisation problem they are just a constant term (no influence on optimal result).

    Therefore, these capital costs are not included in ``network.objective``!

    If you want to calculate the full total annual system costs add these to the objective value.

.. tip::
    The rule :mod:`solve_all_networks` runs
    for all ``scenario`` s in the configuration file
    the rule :mod:`solve_network`.
"""

import logging
import os
import re
import sys
from pathlib import Path

if "snakemake" in globals():
    REPO_ROOT = Path(snakemake.scriptdir).resolve().parents[1]
else:
    REPO_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO_ROOT / "scripts" / "custom"))
sys.path.insert(1, str(REPO_ROOT / "scripts"))

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa
import xarray as xr
from _helpers import (
    configure_logging,
    create_logger,
    read_csv_nafix,
)

from _helper import (
    attach_grid_region_to_buses,
)
from process_cost_data import load_costs
from linopy import merge
from prepare_network import set_transmission_limit
from pypsa.descriptors import get_switchable_as_dense as get_as_dense
from pypsa.optimization.abstract import optimize_transmission_expansion_iteratively
from pypsa.optimization.optimize import optimize

logger = create_logger(__name__)
pypsa.pf.logger.setLevel(logging.WARNING)


def override_component_attrs(directory):
    """Tell PyPSA to override component attributes from CSV files."""
    attrs = pypsa.components.component_attrs.copy()
    directory = Path(directory)

    for component in attrs:
        filename = component.lower().replace(" ", "_") + ".csv"
        fn = directory / filename

        if fn.exists():
            attrs[component] = pd.read_csv(fn, index_col=0, na_values="n/a")

    return attrs


def get_load_shedding_capacity(n, safety_margin=1.2):
    """
    Calculate required load shedding p_nom per bus based on the
    maximum aggregated load observed in any snapshot.

    Parameters
    ----------
    n : pypsa.Network
        The PyPSA network
    safety_margin : float, default 1.2
        Safety factor to apply to the maximum load

    Returns
    -------
    pd.Series
        Required p_nom per bus for load shedding.
    """

    load_shedding_p_nom = pd.Series(0.0, index=n.buses.index)

    for bus_name, bus_loads in n.loads.groupby("bus"):

        if not n.loads_t.p_set.empty:
            bus_load_timeseries = n.loads_t.p_set[
                bus_loads.index.intersection(n.loads_t.p_set.columns)
            ]
            # Sum loads across all components at this bus for each snapshot
            total_load_per_snapshot = bus_load_timeseries.sum(axis=1)
            max_total_load = total_load_per_snapshot.max()
        else:
            max_total_load = bus_loads["p_set"].sum()

        required_p_nom = max_total_load * safety_margin

        load_shedding_p_nom[bus_name] = required_p_nom

    return load_shedding_p_nom


def prepare_network(n, solve_opts, config):
    if "clip_p_max_pu" in solve_opts:
        for df in (
            n.generators_t.p_max_pu,
            n.generators_t.p_min_pu,
            n.storage_units_t.inflow,
        ):
            df.where(df > solve_opts["clip_p_max_pu"], other=0.0, inplace=True)

    if "lv_limit" in n.global_constraints.index:
        n.line_volume_limit = n.global_constraints.at["lv_limit", "constant"]
        n.line_volume_limit_dual = n.global_constraints.at["lv_limit", "mu"]

    if solve_opts.get("load_shedding"):
        required_p_nom = get_load_shedding_capacity(n, safety_margin=1.2)
        n.add("Carrier", "load shedding", color="#dd2e23", nice_name="Load shedding")
        n.madd(
            "Generator",
            n.buses.index,
            " load shedding",
            bus=n.buses.index,
            carrier="load shedding",
            sign=1,
            marginal_cost=solve_opts.get("load_shedding") * 1000,  # convert to Eur/MWh
            p_nom=required_p_nom.reindex(n.buses.index, fill_value=0.5e6),
        )

    if solve_opts.get("noisy_costs"):
        for t in n.iterate_components():
            # if 'capital_cost' in t.df:
            #    t.df['capital_cost'] += 1e1 + 2.*(np.random.random(len(t.df)) - 0.5)
            if "marginal_cost" in t.df:
                np.random.seed(174)
                t.df["marginal_cost"] += 1e-2 + 2e-3 * (
                    np.random.random(len(t.df)) - 0.5
                )

        for t in n.iterate_components(["Line", "Link"]):
            np.random.seed(123)
            t.df["capital_cost"] += (
                1e-1 + 2e-2 * (np.random.random(len(t.df)) - 0.5)
            ) * t.df["length"]

    if solve_opts.get("nhours"):
        nhours = solve_opts["nhours"]
        n.set_snapshots(n.snapshots[:nhours])
        n.snapshot_weightings[:] = 8760.0 / nhours

    if snakemake.config["foresight"] == "myopic":
        add_land_use_constraint(n)

    return n


def propagate_base_year_efficiencies(network, base_year=2020, cutoff_year=2025):
    """
    Set efficiency values for all generators and links built in or before `cutoff_year`
    using base-year efficiencies defined in `config.base.yaml`.
    Existing values from cost file will be overwritten.

    Parameters:
        network: PyPSA Network object
        base_year: Reference year for base efficiencies
        cutoff_year: Maximum build year considered as 'existing' (default: 2025)
    """

    base_efficiencies = {
        "coal": 0.3195,
        "oil": 0.3005,
        "CCGT": 0.4429,
        "nuclear": 0.3254,
        "biomass": 0.30,
    }

    # Apply efficiencies to existing links
    for name, link in network.links.iterrows():
        if (
            link.carrier in base_efficiencies
            and getattr(link, "build_year", float("inf")) <= cutoff_year
        ):
            network.links.at[name, "efficiency"] = base_efficiencies[link.carrier]

    # Apply efficiencies to existing nuclear generators
    for name, gen in network.generators.iterrows():
        if (
            gen.carrier == "nuclear"
            and getattr(gen, "build_year", float("inf")) <= cutoff_year
        ):
            network.generators.at[name, "efficiency"] = base_efficiencies["nuclear"]


def apply_tax_credits_to_network(
    network,
    ptc_path,
    itc_path,
    planning_horizon,
    costs,
    config_file=None,
    log_path=None,
    verbose=False,
):
    """
    Apply production and investment tax credits to the network.

    Parameters:
        network: PyPSA network object
        ptc_path: Path to CSV file with PTC (columns: carrier, credit)
        itc_path: Path to CSV file with ITC (columns: carrier, credit)
        planning_horizon: Current planning year (int)
        costs: DataFrame containing the full cost structure, including capital_cost
        config_file: Dict loaded from YAML config file
        log_path: Optional path to save a log of applied modifications
        verbose: If True, print detailed logging of applied credits
    """

    modifications = []

    # Load PTC and ITC file
    ptc_df = pd.read_csv(ptc_path)

    # Select correct regime (IRA 2022 or OB3) if present
    pre_ob3_tax_credits = None
    if config_file is not None:
        pre_ob3_tax_credits = config_file.get("policies", {}).get(
            "pre_ob3_tax_credits", None
        )

    regime = "IRA 2022" if pre_ob3_tax_credits else "OB3"

    # Filter PTC by regime if column exists
    if "regime" in ptc_df.columns:
        ptc_active = ptc_df[
            (ptc_df["regime"] == regime)
            | (ptc_df["regime"].isna())
            | (ptc_df["regime"] == "")
        ]
    else:
        ptc_active = ptc_df

    # Build dictionary for active credits
    ptc_credits = dict(zip(ptc_active["carrier"], ptc_active["credit"]))

    # Load ITC file and dictionary
    itc_df = pd.read_csv(itc_path)
    itc_credits = dict(zip(itc_df["carrier"], itc_df["credit"]))

    biomass_aliases = {
        "biomass",
        "urban central solid biomass CHP",
        "urban central solid biomass CHP CC",
    }

    cc_credit_on_co2_stored = {
        "ethanol from starch CC",
        "SMR CC",
        "DRI CC",
        "BF-BOF CC",
        "dry clinker CC",
    }

    cc_credit_on_co2_atmosphere = {"DAC"}

    electrolyzer_carriers = {"Alkaline electrolyzer large", "PEM electrolyzer", "SOEC"}

    # Apply Production Tax Credits to GENERATORS
    for name, gen in network.generators.iterrows():
        carrier = gen.carrier
        build_year = gen.build_year
        base_cost = gen["_marginal_cost_original"]

        carrier_key = carrier
        if carrier_key not in ptc_credits and carrier_key != "nuclear":
            continue

        credit = ptc_credits.get(carrier_key, 0.0)
        apply, scale = False, 1.0

        # Nuclear
        if carrier_key == "nuclear":
            # Existing nuclear (fixed window 2024–2032)
            if build_year <= 2024 and 2024 <= planning_horizon <= 2032:
                credit = ptc_credits.get("nuclear_existing", 0.0)
                apply = True

            # New nuclear
            elif 2030 <= build_year < 2033:
                horizon_limit = 2040 if pre_ob3_tax_credits else build_year + 10
                full_end = 2040 if pre_ob3_tax_credits else 2033

                if planning_horizon <= horizon_limit:
                    if planning_horizon <= full_end:
                        scale = 1.0
                        credit = ptc_credits.get("nuclear_new", 0.0)
                        apply = True
                    elif planning_horizon == full_end + 1:
                        scale = 0.75
                        credit = ptc_credits.get("nuclear_new", 0.0)
                        apply = True
                    elif planning_horizon == full_end + 2:
                        scale = 0.5
                        credit = ptc_credits.get("nuclear_new", 0.0)
                        apply = True

        # Geothermal
        elif carrier_key == "geothermal":
            horizon_limit = 2040 if pre_ob3_tax_credits else build_year + 10
            full_end = 2040 if pre_ob3_tax_credits else 2033

            if 2030 <= build_year <= 2035 and planning_horizon <= horizon_limit:
                if planning_horizon <= full_end:
                    scale = 1.0
                    apply = True
                elif planning_horizon == full_end + 1:
                    scale = 0.75
                    apply = True
                elif planning_horizon == full_end + 2:
                    scale = 0.5
                    apply = True

        # Solar and wind (only with pre-OB3 tax credits)
        elif (
            carrier_key in {"solar", "onwind", "offwind-ac", "offwind-dc"}
            and pre_ob3_tax_credits
        ):
            horizon_limit = build_year + 10
            full_end = 2033

            if 2030 <= build_year <= 2035 and planning_horizon <= horizon_limit:
                if planning_horizon <= full_end:
                    scale = 1.0
                    apply = True
                elif planning_horizon == full_end + 1:
                    scale = 0.75
                    apply = True
                elif planning_horizon == full_end + 2:
                    scale = 0.5
                    apply = True

        # Apply modification if valid
        if apply:
            new_cost = base_cost + scale * credit
            network.generators.at[name, "marginal_cost"] = new_cost
            modifications.append(
                {
                    "component": "generator",
                    "name": name,
                    "carrier": carrier,
                    "build_year": build_year,
                    "original": base_cost,
                    "credit": scale * credit,
                    "final": new_cost,
                }
            )
            if verbose:
                logger.info(f"[PTC GEN] {name} | +{scale * credit:.2f}")

    # Apply PTC to LINKS (biomass, carbon capture, electrolyzers, DAC)
    for name, link in network.links.iterrows():
        carrier = link.carrier
        build_year = getattr(link, "build_year", planning_horizon)
        base_cost = link["_marginal_cost_original"]

        # Biomass
        if carrier in biomass_aliases:
            carrier_key = "biomass"
            if carrier_key not in ptc_credits:
                continue

            horizon_limit = 2040 if pre_ob3_tax_credits else build_year + 10
            full_end = 2040 if pre_ob3_tax_credits else 2033

            if 2030 <= build_year <= 2035 and planning_horizon <= horizon_limit:
                scale = 0.0
                if planning_horizon <= full_end:
                    scale = 1.0
                elif planning_horizon == full_end + 1:
                    scale = 0.75
                elif planning_horizon == full_end + 2:
                    scale = 0.5

                if scale > 0:
                    credit_per_mwh = ptc_credits[carrier_key]
                    elec_eff = link.get("efficiency", 0.0)
                    credit = scale * credit_per_mwh * elec_eff
                    new_cost = base_cost + credit

                    network.links.at[name, "marginal_cost"] = new_cost
                    modifications.append(
                        {
                            "component": "link",
                            "name": name,
                            "carrier": carrier,
                            "build_year": build_year,
                            "original": base_cost,
                            "credit": credit,
                            "final": new_cost,
                            "efficiency": elec_eff,
                        }
                    )

                    if verbose:
                        logger.info(
                            f"[PTC LINK Biomass] {name} | year={planning_horizon}, scale={scale:.2f}, eff={elec_eff:.3f}, credit={credit:.2f}"
                        )

        # Electrolyzers
        elif carrier in electrolyzer_carriers:
            if not pre_ob3_tax_credits:
                continue

            if verbose:
                logger.info(f"[PTC LINK ELECTROLYZER] pre-OB3 active for {name}")

            if 2025 <= build_year <= 2032 and planning_horizon <= build_year + 10:
                credit_per_mwh_h2 = ptc_credits.get(carrier, 0.0)
                h2_efficiency = link.get("efficiency", 0.0)

                if h2_efficiency > 0 and credit_per_mwh_h2 != 0.0:
                    credit = credit_per_mwh_h2 * h2_efficiency
                    new_cost = base_cost + credit
                    network.links.at[name, "marginal_cost"] = new_cost
                    modifications.append(
                        {
                            "component": "link",
                            "name": name,
                            "carrier": carrier,
                            "build_year": build_year,
                            "original": base_cost,
                            "credit": credit,
                            "final": new_cost,
                        }
                    )
                    if verbose:
                        logger.info(
                            f"[PTC LINK ELECTROLYZER] credit applied for {name} | "
                            f"credit={credit:.2f}, marginal_cost={new_cost:.2f}"
                        )

        # Carbon capture with CO2 storage
        elif carrier in cc_credit_on_co2_stored:
            if 2030 <= build_year <= 2033 and planning_horizon <= build_year + 12:
                # Detect efficiency toward eligible CO2 buses (only buffer co2)
                def get_co2_eligible_efficiency(row):
                    co2_bus_patterns = ("buffer co2",)
                    for key, val in row.items():
                        if key.startswith("bus") and isinstance(val, str):
                            name = val.lower()
                            if any(pat in name for pat in co2_bus_patterns):
                                eff_key = "efficiency" + key[3:]
                                return float(row.get(eff_key, 0.0))
                    return 0.0

                tco2 = get_co2_eligible_efficiency(link)
                credit_per_t = ptc_credits.get(carrier, 0.0)

                # Always apply usage credit
                if tco2 > 0 and credit_per_t != 0.0:
                    credit = credit_per_t * tco2
                    new_cost = base_cost + credit
                    network.links.at[name, "marginal_cost"] = new_cost
                    modifications.append(
                        {
                            "component": "link",
                            "name": name,
                            "carrier": carrier,
                            "build_year": build_year,
                            "original": base_cost,
                            "credit": credit,
                            "final": new_cost,
                            "assumption": "usage-only credit",
                        }
                    )

                    if verbose:
                        logger.info(
                            f"[PTC LINK CC-stored] {name} | CO2={tco2:.3f}, credit={credit:.2f} (usage-only)"
                        )

        # DAC - CO2 atmosphere
        elif carrier in cc_credit_on_co2_atmosphere:
            if 2030 <= build_year <= 2033 and planning_horizon <= build_year + 12:
                tco2 = link.efficiency
                credit_per_t = ptc_credits.get(carrier, 0.0)

                # Apply usage credit
                if tco2 > 0 and credit_per_t != 0.0:
                    credit = credit_per_t * tco2
                    new_cost = base_cost + credit
                    network.links.at[name, "marginal_cost"] = new_cost
                    modifications.append(
                        {
                            "component": "link",
                            "name": name,
                            "carrier": carrier,
                            "build_year": build_year,
                            "original": base_cost,
                            "credit": credit,
                            "final": new_cost,
                            "assumption": "usage-only credit",
                        }
                    )

                    if verbose:
                        logger.info(
                            f"[PTC LINK DAC] {name} | CO2={tco2:.3f}, credit={credit:.2f} (usage-only)"
                        )

    # Apply Investment Tax Credits to STORAGE UNITS (batteries)
    if os.path.exists(itc_path):
        itc_df = pd.read_csv(itc_path, index_col=0)

        for carrier, row in itc_df.iterrows():
            credit_factor = -row.get("credit", 0.0) / 100

            if carrier not in network.stores.carrier.values:
                continue

            affected = network.stores.query("carrier == @carrier")
            for idx, su in affected.iterrows():
                build_year = su.get("build_year", planning_horizon)

                horizon_limit = 2040 if pre_ob3_tax_credits else build_year + 10
                full_end = 2040 if pre_ob3_tax_credits else 2033

                if 2030 <= build_year <= 2035 and planning_horizon <= horizon_limit:
                    scale = 0.0
                    if planning_horizon <= full_end:
                        scale = 1.0
                    elif planning_horizon == full_end + 1:
                        scale = 0.75
                    elif planning_horizon == full_end + 2:
                        scale = 0.5

                    if scale > 0:
                        orig = su.capital_cost
                        new = orig * (1 - scale * credit_factor)
                        network.stores.at[idx, "capital_cost"] = new
                        modifications.append(
                            {
                                "component": "store",
                                "name": idx,
                                "carrier": carrier,
                                "build_year": build_year,
                                "original": orig,
                                "credit_factor": scale * credit_factor,
                                "final": new,
                            }
                        )
                        if verbose:
                            logger.info(
                                f"[ITC STORAGE] {idx} | year={planning_horizon}, scale={scale:.2f}"
                            )

    # Apply Investment Tax Credits to LINKS (battery chargers)
    if os.path.exists(itc_path):
        itc_df = pd.read_csv(itc_path, index_col=0)

        if (
            "battery" in itc_df.index
            and "battery charger" in network.links.carrier.values
        ):
            credit_factor = -itc_df.loc["battery", "credit"] / 100

            affected = network.links.query("carrier == 'battery charger'")
            for idx, lk in affected.iterrows():
                build_year = lk.get("build_year", planning_horizon)

                horizon_limit = 2040 if pre_ob3_tax_credits else build_year + 10
                full_end = 2040 if pre_ob3_tax_credits else 2033

                if 2030 <= build_year <= 2035 and planning_horizon <= horizon_limit:
                    scale = 0.0
                    if planning_horizon <= full_end:
                        scale = 1.0
                    elif planning_horizon == full_end + 1:
                        scale = 0.75
                    elif planning_horizon == full_end + 2:
                        scale = 0.5

                    if scale > 0 and lk.capital_cost > 0:
                        orig = lk.capital_cost
                        new = orig * (1 - scale * credit_factor)
                        network.links.at[idx, "capital_cost"] = new
                        modifications.append(
                            {
                                "component": "link",
                                "name": idx,
                                "carrier": lk.carrier,
                                "build_year": build_year,
                                "original": orig,
                                "credit_factor": scale * credit_factor,
                                "final": new,
                            }
                        )
                        if verbose:
                            logger.info(
                                f"[ITC LINK BATTERY] {idx} | year={planning_horizon}, scale={scale:.2f}"
                            )

    # Save modifications log
    if modifications and log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        pd.DataFrame(modifications).to_csv(log_path, index=False)


def add_RPS_constraints(network, config_file):
    def process_targets_data(path, carrier, policy):
        df = read_csv_nafix(path)
        df.rename(columns={"Unnamed: 0": "state"}, inplace=True)
        df = df.melt(id_vars="state", var_name="year", value_name="target")
        df["carrier"] = ", ".join(carrier)
        df["year"] = df.year.astype(int)
        df["policy"] = policy
        return df

    def attach_state_to_buses(network, path_shapes, distance_crs):
        shapes = gpd.read_file(path_shapes, crs=distance_crs)
        shapes["ISO_1"] = shapes["ISO_1"].apply(lambda x: x.split("-")[1])
        shapes.rename(columns={"ISO_1": "State"}, inplace=True)

        ac_dc_carriers = ["AC", "DC"]
        location_mapping = network.buses.query("carrier in @ac_dc_carriers")[["x", "y"]]

        network.buses["x"] = (
            network.buses["location"].map(location_mapping["x"]).fillna(0)
        )
        network.buses["y"] = (
            network.buses["location"].map(location_mapping["y"]).fillna(0)
        )

        pypsa_gpd = gpd.GeoDataFrame(
            network.buses,
            geometry=gpd.points_from_xy(network.buses.x, network.buses.y),
            crs=4326,
        )

        bus_cols = list(network.buses.columns) + ["State"]
        st_buses = gpd.sjoin_nearest(shapes, pypsa_gpd, how="right")[bus_cols]

        network.buses["state"] = st_buses["State"]

        return network

    def filter_policy_data(df, coverage, planning_horizon):
        return df[
            (df["year"] == planning_horizon)
            & (df["target"] > 0.0)
            & (df["state"].isin(network.buses[f"{coverage}"].unique()))
        ]

    def _weights(kind):
        return xr.DataArray(
            getattr(network.snapshot_weightings, kind),
            dims=["snapshot"],
            coords={"snapshot": network.snapshots},
        )

    def _gen_by_bus(generators, coefficient=1.0):
        if generators.empty:
            return None

        p_gen = network.model["Generator-p"]
        gens = generators.index.intersection(p_gen.indexes["Generator"])
        if gens.empty:
            return None

        bus = xr.DataArray(
            generators.loc[gens, "bus"],
            dims=["Generator"],
            coords={"Generator": gens},
            name="bus",
        )

        return (
            (p_gen.loc[:, gens] * _weights("generators") * coefficient)
            .groupby(bus)
            .sum()
            .sum("snapshot")
        )

    def _storage_dispatch_by_bus(storages, coefficient=1.0):
        if storages.empty or "StorageUnit-p_dispatch" not in network.model.variables:
            return None

        p_dispatch = network.model["StorageUnit-p_dispatch"]
        stores = storages.index.intersection(p_dispatch.indexes["StorageUnit"])
        if stores.empty:
            return None

        bus = xr.DataArray(
            storages.loc[stores, "bus"],
            dims=["StorageUnit"],
            coords={"StorageUnit": stores},
            name="bus",
        )

        return (
            (p_dispatch.loc[:, stores] * _weights("stores") * coefficient)
            .groupby(bus)
            .sum()
            .sum("snapshot")
        )

    def _link_by_bus1(links, weighting_kind, coefficient=1.0, use_efficiency=True):
        if links.empty:
            return None

        p_link = network.model["Link-p"]
        link_index = links.index.intersection(p_link.indexes["Link"])
        if link_index.empty:
            return None

        if use_efficiency:
            eff = xr.DataArray(
                network.links.loc[link_index, "efficiency"].astype(float),
                dims=["Link"],
                coords={"Link": link_index},
            )
        else:
            eff = 1.0

        bus = xr.DataArray(
            network.links.loc[link_index, "bus1"],
            dims=["Link"],
            coords={"Link": link_index},
            name="bus",
        )

        return (
            (p_link.loc[:, link_index] * _weights(weighting_kind) * eff * coefficient)
            .groupby(bus)
            .sum()
            .sum("snapshot")
        )

    def _add(lhs, term):
        if term is None:
            return lhs
        return term if lhs is None else lhs + term

    def add_constraints_to_network(
        res_generators_eligible,
        res_storages_eligible,
        res_links_eligible,
        ces_generators_eligible,
        conventional_links_eligible,
        state,
        policy_data,
        constraints_type,
    ):
        target = policy_data[policy_data.policy == f"{constraints_type}"][
            "target"
        ].item()
        target_year = policy_data[policy_data.policy == f"{constraints_type}"][
            "year"
        ].item()

        res_generators_eligible = res_generators_eligible.copy()
        ces_generators_eligible = ces_generators_eligible.copy()

        res_generators_eligible["bus"] = res_generators_eligible.bus.str.replace(
            " low voltage", "", regex=False
        )
        ces_generators_eligible["bus"] = ces_generators_eligible.bus.str.replace(
            " low voltage", "", regex=False
        )

        lhs = None

        lhs = _add(lhs, _gen_by_bus(res_generators_eligible))
        lhs = _add(
            lhs,
            _storage_dispatch_by_bus(
                res_storages_eligible,
                coefficient=(1 - target),
            ),
        )
        lhs = _add(
            lhs,
            _link_by_bus1(
                res_links_eligible,
                weighting_kind="stores",
                coefficient=(1 - target),
                use_efficiency=True,
            ),
        )
        lhs = _add(
            lhs,
            _gen_by_bus(
                ces_generators_eligible,
                coefficient=-target,
            ),
        )
        lhs = _add(
            lhs,
            _link_by_bus1(
                conventional_links_eligible,
                weighting_kind="generators",
                coefficient=-target,
                use_efficiency=True,
            ),
        )

        if lhs is None:
            logger.warning(
                "No eligible assets found for %s constraint for %s.",
                constraints_type,
                state,
            )
            return

        if state != "US":
            buses = network.buses.index[network.buses.state == state]
        else:
            buses = network.buses.index[network.buses.country == "US"]

        lhs_grouped = lhs.reindex(bus=buses, fill_value=0).sum("bus")

        network.model.add_constraints(
            lhs_grouped >= 0,
            name=f"{constraints_type}_{state}_rps_limit",
        )

        logger.info(
            f"Added {constraints_type} constraint for {state} in {target_year}."
        )

    res_generator_carriers = [
        "solar",
        "onwind",
        "offwind-ac",
        "solar rooftop",
        "offwind-dc",
        "ror",
        "geothermal",
    ]
    res_link_carriers = []
    res_storage_carriers = ["hydro"]
    ces_generator_carriers = res_generator_carriers + ["nuclear"]

    conventional_link_carriers = [
        "OCGT",
        "CCGT",
        "oil",
        "coal",
        "lignite",
        "urban central gas CHP",
        "urban central gas CHP CC",
        "biomass",
        "urban central solid biomass CHP",
        "urban central solid biomass CHP CC",
    ]

    ces_data = process_targets_data(
        snakemake.input.ces_path,
        ces_generator_carriers + res_link_carriers,
        "CES",
    )
    res_data = process_targets_data(
        snakemake.input.res_path,
        res_generator_carriers + res_link_carriers,
        "RES",
    )
    policy_data = pd.concat([ces_data, res_data], ignore_index=True)

    path_shapes = snakemake.input.gadm_shape_path
    distance_crs = config_file["crs"]["distance_crs"]
    network = attach_state_to_buses(network, path_shapes, distance_crs)
    planning_horizon = int(snakemake.wildcards.planning_horizons)

    state_policies = config_file["policies"]["state"]
    country_policies = config_file["policies"]["country"]

    if state_policies:
        state_policy_data = filter_policy_data(policy_data, "state", planning_horizon)
        state_list = state_policy_data.state.unique()

        for state in state_list:
            region_buses = network.buses[network.buses.state.isin([state])]
            if region_buses.empty:
                continue

            region_policy = state_policy_data[state_policy_data.state == state]

            region_generators = network.generators[
                network.generators.bus.isin(region_buses.index)
            ]
            res_generators_eligible = region_generators[
                region_generators.carrier.isin(res_generator_carriers)
            ]
            ces_generators_eligible = region_generators[
                region_generators.carrier.isin(ces_generator_carriers)
            ]

            region_links = network.links[network.links.bus1.isin(region_buses.index)]
            res_links_eligible = region_links[
                region_links.carrier.isin(res_link_carriers)
            ]

            region_storages = network.storage_units[
                network.storage_units.bus.isin(region_buses.index)
            ]
            res_storages_eligible = region_storages[
                region_storages.carrier.isin(res_storage_carriers)
            ]

            conventional_links_eligible = region_links[
                region_links.carrier.isin(conventional_link_carriers)
            ]

            if "RES" in region_policy.policy.values and "RES" in state_policies:
                add_constraints_to_network(
                    res_generators_eligible,
                    res_storages_eligible,
                    res_links_eligible,
                    ces_generators_eligible,
                    conventional_links_eligible,
                    state,
                    region_policy,
                    "RES",
                )

            if "CES" in region_policy.policy.values and "CES" in state_policies:
                add_constraints_to_network(
                    ces_generators_eligible,
                    res_storages_eligible,
                    res_links_eligible,
                    ces_generators_eligible,
                    conventional_links_eligible,
                    state,
                    region_policy,
                    "CES",
                )

    if country_policies:
        country_policy_data = filter_policy_data(
            policy_data, "country", planning_horizon
        )
        country_ces_generators = network.generators[
            network.generators.carrier.isin(ces_generator_carriers)
        ]
        country_res_storages = network.storage_units[
            network.storage_units.carrier.isin(res_storage_carriers)
        ]
        country_res_links = network.links[network.links.carrier.isin(res_link_carriers)]
        country_conventional_links = network.links[
            network.links.carrier.isin(conventional_link_carriers)
        ]

        if "CES" in country_policy_data.policy.values and "CES" in country_policies:
            add_constraints_to_network(
                country_ces_generators,
                country_res_storages,
                country_res_links,
                country_ces_generators,
                country_conventional_links,
                "US",
                country_policy_data,
                "CES",
            )


def add_CCL_constraints(n, config):
    """
    Add CCL (country & carrier limit) constraint to the network.

    Add minimum and maximum levels of generator nominal capacity per carrier
    for individual countries. Opts and path for agg_p_nom_minmax.csv must be defined
    in config.yaml. Default file is available at data/agg_p_nom_minmax.csv.
    Parameter include_existing in config.yaml decides whether existing capacities
    are considered in the CCL constraints. Default is false.

    Parameters
    ----------
    n : pypsa.Network
    config : dict

    Example
    -------
    scenario:
        opts: [CCL-Co2L-24H]
    electricity:
        agg_p_nom_limits:
            file: data/agg_p_nom_minmax.csv
            include_existing: false
    """
    agg_p_nom_limits = config["electricity"].get("agg_p_nom_limits")

    try:
        agg_p_nom_minmax = read_csv_nafix(
            snakemake.input.agg_p_nom_minmax, index_col=list(range(2)), header=[0, 1]
        )[snakemake.wildcards.planning_horizons]
    except IOError:
        logger.exception(
            "Need to specify the path to a .csv file containing "
            "aggregate capacity limits per country in "
            "config['electricity']['agg_p_nom_limit']."
        )
    logger.info(
        "Adding per carrier generation capacity constraints for " "individual countries"
    )

    capacity_variable = n.model["Generator-p_nom"]

    # get carriers to which CCL constraints apply
    ccl_carriers = agg_p_nom_minmax.index.get_level_values(1).unique()
    ext_carriers = n.generators.query("p_nom_extendable").carrier.unique()
    ccl_carriers = ccl_carriers[ccl_carriers.isin(ext_carriers)]

    # If no CCL carriers found, return early
    if not ccl_carriers.any():
        logger.info(
            "No CCL carriers found that are extendable. Skipping CCL constraints."
        )
        return

    # Get extendable generators for relevant carriers
    gens = n.generators[n.generators.carrier.isin(ccl_carriers)]
    gens = gens.rename_axis(index="Generator-ext")

    # Prepare country and carrier grouper
    grouper = pd.concat(
        [gens.bus.map(n.buses.country).rename("country"), gens.carrier], axis=1
    )

    # Prepare LHS
    lhs = capacity_variable.groupby(grouper).sum()

    # Obtain existing capacities
    existing_capacities = gens.p_nom.groupby(
        [grouper["country"], grouper["carrier"]]
    ).sum()

    # Obtain minimum and maximum constraint limits
    min_values = agg_p_nom_minmax["min"]
    max_values = agg_p_nom_minmax["max"]

    # Adjust limits if existing capacities are considered
    if agg_p_nom_limits.get("include_existing", False):
        min_values = (min_values - existing_capacities).clip(lower=0)
        max_values = (max_values - existing_capacities).clip(lower=0)
        logger.info(
            f"Considered existing capacities in CCL constraints for carrier {c}."
        )

    # Convert limits to xarray for masking
    min_values = xr.DataArray(min_values.dropna()).rename(dim_0="group")
    max_values = xr.DataArray(max_values.dropna()).rename(dim_0="group")

    # Valid constraints
    valid_min_index = min_values.indexes["group"].intersection(lhs.indexes["group"])
    valid_max_index = max_values.indexes["group"].intersection(lhs.indexes["group"])

    if not valid_min_index.empty:
        n.model.add_constraints(
            lhs.sel(group=valid_min_index) >= min_values.loc[valid_min_index],
            name="agg_p_nom_min",
        )

    if not valid_max_index.empty:
        n.model.add_constraints(
            lhs.sel(group=valid_max_index) <= max_values.loc[valid_max_index],
            name="agg_p_nom_max",
        )


def add_h2_production_constraints(n, config):
    """
    Add annual aggregate H2 production min/max constraints for electrolysis.
    """
    hcfg = config.get("policy_config", {}).get("hydrogen", {})

    if not hcfg.get("h2_production_constraint", False):
        return

    csv_path = hcfg.get("h2_production_limits")
    if csv_path is None:
        raise ValueError(
            "h2_production_constraint is enabled but no "
            "'h2_production_limits' CSV is provided in config."
        )

    logger.info("Adding aggregate H2 production constraints")

    try:
        df_full = read_csv_nafix(csv_path, index_col=[0, 1], header=[0, 1])
        df_y = df_full[snakemake.wildcards.planning_horizons]
    except IOError:
        logger.exception("Could not read aggregate H2 production limits.")
        return
    except KeyError:
        logger.warning(
            "No H2 production limits found for year %s. Skipping.",
            snakemake.wildcards.planning_horizons,
        )
        return

    if df_y.empty:
        logger.info("Empty H2 production cap table. Skipping.")
        return

    logical_carrier = "h2_electrolysis"

    electrolysis_carriers = [
        "Alkaline electrolyzer large",
        "Alkaline electrolyzer medium",
        "Alkaline electrolyzer small",
        "PEM electrolyzer",
        "SOEC",
        "Flexible electrolyzer",
    ]

    el_links_all = n.links.index[n.links.carrier.isin(electrolysis_carriers)]
    if el_links_all.empty:
        raise ValueError(
            "H2 production constraint enabled but no electrolyzer links found."
        )

    p_link = n.model["Link-p"]
    el_links = el_links_all.intersection(p_link.indexes["Link"])

    if el_links.empty:
        raise ValueError("Electrolyzers exist but none have Link-p variables.")

    weights = xr.DataArray(
        n.snapshot_weightings.generators,
        dims=["snapshot"],
        coords={"snapshot": n.snapshots},
    )

    efficiency = xr.DataArray(
        n.links.loc[el_links, "efficiency"].astype(float),
        dims=["Link"],
        coords={"Link": el_links},
    )

    h2_out_links = (p_link.loc[:, el_links] * weights * efficiency).sum("snapshot")

    el_country = n.buses.loc[n.links.loc[el_links, "bus0"], "country"]

    for sense, column, cname in [
        (">=", "min", "h2_prod_min"),
        ("<=", "max", "h2_prod_max"),
    ]:
        if column not in df_y.columns:
            continue

        limits = df_y[column].dropna()
        if limits.empty:
            continue

        for idx, value in limits.items():
            country, carrier = idx

            if carrier != logical_carrier:
                continue

            links = el_links[el_country.loc[el_links] == country]
            if links.empty:
                continue

            lhs = h2_out_links.loc[links].sum()

            logger.info(
                "Applying H2 %s cap for %s in %s: %.2f MWh",
                column.upper(),
                country,
                snakemake.wildcards.planning_horizons,
                float(value),
            )

            if sense == ">=":
                n.model.add_constraints(lhs >= value, name=f"{cname}_{country}")
            else:
                n.model.add_constraints(lhs <= value, name=f"{cname}_{country}")

    logger.info(
        "H2 production caps applied for year %s.",
        snakemake.wildcards.planning_horizons,
    )


def add_EQ_constraints(n, o, scaling=1e-1):
    """
    Add equity constraints to the network.

    Currently this is only implemented for the electricity sector only.

    Opts must be specified in the config.yaml.

    Parameters
    ----------
    n : pypsa.Network
    o : str

    Example
    -------
    scenario:
        opts: [Co2L-EQ0.7-24h]

    Require each country or node to on average produce a minimal share
    of its total electricity consumption itself. Example: EQ0.7c demands each country
    to produce on average at least 70% of its consumption; EQ0.7 demands
    each node to produce on average at least 70% of its consumption.
    """
    float_regex = r"[0-9]*\.?[0-9]+"
    level = float(re.findall(float_regex, o)[0])
    if o[-1] == "c":
        ggrouper = n.generators.bus.map(n.buses.country)
        lgrouper = n.loads.bus.map(n.buses.country)
        sgrouper = n.storage_units.bus.map(n.buses.country)
    else:
        ggrouper = n.generators.bus
        lgrouper = n.loads.bus
        sgrouper = n.storage_units.bus
    load = (
        n.snapshot_weightings.generators
        @ n.loads_t.p_set.groupby(lgrouper, axis=1).sum()
    )
    inflow = (
        n.snapshot_weightings.stores
        @ n.storage_units_t.inflow.groupby(sgrouper, axis=1).sum()
    )
    inflow = inflow.reindex(load.index).fillna(0.0)
    rhs = scaling * (level * load - inflow)
    dispatch_variable = n.model["Generator-p"]
    lhs_gen = (
        (dispatch_variable * (n.snapshot_weightings.generators * scaling))
        .groupby(ggrouper.to_xarray())
        .sum()
        .sum("snapshot")
    )
    # the current formulation implies that the available hydro power is (inflow - spillage)
    # it implies efficiency_dispatch is 1 which is not quite general
    # see https://github.com/pypsa-meets-earth/pypsa-earth/issues/1245 for possible improvements
    if not n.storage_units_t.inflow.empty:
        spillage_variable = n.model["StorageUnit-spill"]
        lhs_spill = (
            (spillage_variable * (-n.snapshot_weightings.stores * scaling))
            .groupby_sum(sgrouper)
            .groupby(sgrouper.to_xarray())
            .sum()
            .sum("snapshot")
        )
        lhs = lhs_gen + lhs_spill
    else:
        lhs = lhs_gen
    n.model.add_constraints(lhs >= rhs, name="equity_min")


def add_BAU_constraints(n, config):
    """
    Add a per-carrier minimal overall capacity.

    BAU_mincapacities and opts must be adjusted in the config.yaml.

    Parameters
    ----------
    n : pypsa.Network
    config : dict

    Example
    -------
    scenario:
        opts: [Co2L-BAU-24h]
    electricity:
        BAU_mincapacities:
            solar: 0
            onwind: 0
            OCGT: 100000
            offwind-ac: 0
            offwind-dc: 0
    Which sets minimum expansion across all nodes e.g. in Europe to 100GW.
    OCGT bus 1 + OCGT bus 2 + ... > 100000
    """
    mincaps = pd.Series(config["electricity"]["BAU_mincapacities"])
    p_nom = n.model["Generator-p_nom"]
    ext_i = n.generators.query("p_nom_extendable")
    ext_carrier_i = xr.DataArray(ext_i.carrier.rename_axis("Generator-ext"))
    lhs = p_nom.groupby(ext_carrier_i).sum()
    rhs = mincaps[lhs.indexes["carrier"]].rename_axis("carrier")
    n.model.add_constraints(lhs >= rhs, name="bau_mincaps")


def add_SAFE_constraints(n, config):
    """
    Add a capacity reserve margin of a certain fraction above the peak demand.
    Renewable generators and storage do not contribute. Ignores network.

    Parameters
    ----------
        n : pypsa.Network
        config : dict

    Example
    -------
    config.yaml requires to specify opts:

    scenario:
        opts: [Co2L-SAFE-24h]
    electricity:
        SAFE_reservemargin: 0.1
    Which sets a reserve margin of 10% above the peak demand.
    """
    peakdemand = n.loads_t.p_set.sum(axis=1).max()
    margin = 1.0 + config["electricity"]["SAFE_reservemargin"]
    reserve_margin = peakdemand * margin
    conventional_carriers = config["electricity"]["conventional_carriers"]
    ext_gens_i = n.generators.query(
        "carrier in @conventional_carriers & p_nom_extendable"
    ).index
    capacity_variable = n.model["Generator-p_nom"]
    p_nom = n.model["Generator-p_nom"].loc[ext_gens_i]
    lhs = p_nom.sum()
    exist_conv_caps = n.generators.query(
        "~p_nom_extendable & carrier in @conventional_carriers"
    ).p_nom.sum()
    rhs = reserve_margin - exist_conv_caps
    n.model.add_constraints(lhs >= rhs, name="safe_mintotalcap")


def add_operational_reserve_margin_constraint(n, sns, config):
    """
    Build reserve margin constraints based on the formulation
    as suggested in GenX
    https://energy.mit.edu/wp-content/uploads/2017/10/Enhanced-Decision-Support-for-a-Changing-Electricity-Landscape.pdf
    It implies that the reserve margin also accounts for optimal
    dispatch of distributed energy resources (DERs) and demand response
    which is a novel feature of GenX.
    """
    reserve_config = config["electricity"]["operational_reserve"]
    EPSILON_LOAD = reserve_config["epsilon_load"]
    EPSILON_VRES = reserve_config["epsilon_vres"]
    CONTINGENCY = reserve_config["contingency"]

    # Reserve Variables
    n.model.add_variables(
        0, np.inf, coords=[sns, n.generators.index], name="Generator-r"
    )
    reserve = n.model["Generator-r"]
    summed_reserve = reserve.sum("Generator")

    # Share of extendable renewable capacities
    ext_i = n.generators.query("p_nom_extendable").index
    vres_i = n.generators_t.p_max_pu.columns
    if not ext_i.empty and not vres_i.empty:
        capacity_factor = n.generators_t.p_max_pu[vres_i.intersection(ext_i)]
        p_nom_vres = (
            n.model["Generator-p_nom"]
            .loc[vres_i.intersection(ext_i)]
            .rename({"Generator-ext": "Generator"})
        )
        lhs = summed_reserve + (
            p_nom_vres * (-EPSILON_VRES * xr.DataArray(capacity_factor))
        ).sum("Generator")

    # Total demand per t
    demand = get_as_dense(n, "Load", "p_set").sum(axis=1)

    # VRES potential of non extendable generators
    capacity_factor = n.generators_t.p_max_pu[vres_i.difference(ext_i)]
    renewable_capacity = n.generators.p_nom[vres_i.difference(ext_i)]
    potential = (capacity_factor * renewable_capacity).sum(axis=1)

    # Right-hand-side
    rhs = EPSILON_LOAD * demand + EPSILON_VRES * potential + CONTINGENCY

    n.model.add_constraints(lhs >= rhs, name="reserve_margin")


def update_capacity_constraint(n):
    gen_i = n.generators.index
    ext_i = n.generators.query("p_nom_extendable").index
    fix_i = n.generators.query("not p_nom_extendable").index

    dispatch = n.model["Generator-p"]
    reserve = n.model["Generator-r"]

    capacity_fixed = n.generators.p_nom[fix_i]

    p_max_pu = get_as_dense(n, "Generator", "p_max_pu")

    lhs = dispatch + reserve

    # TODO check if `p_max_pu[ext_i]` is safe for empty `ext_i` and drop if cause in case
    if not ext_i.empty:
        capacity_variable = n.model["Generator-p_nom"].rename(
            {"Generator-ext": "Generator"}
        )
        lhs = dispatch + reserve - capacity_variable * xr.DataArray(p_max_pu[ext_i])

    rhs = (p_max_pu[fix_i] * capacity_fixed).reindex(columns=gen_i, fill_value=0)

    n.model.add_constraints(lhs <= rhs, name="gen_updated_capacity_constraint")


def add_operational_reserve_margin(n, sns, config):
    """
    Parameters
    ----------
        n : pypsa.Network
        sns: pd.DatetimeIndex
        config : dict

    Example:
    --------
    config.yaml requires to specify operational_reserve:
    operational_reserve: # like https://genxproject.github.io/GenX/dev/core/#Reserves
        activate: true
        epsilon_load: 0.02 # percentage of load at each snapshot
        epsilon_vres: 0.02 # percentage of VRES at each snapshot
        contingency: 400000 # MW
    """

    add_operational_reserve_margin_constraint(n, sns, config)

    update_capacity_constraint(n)


def add_battery_constraints(n):
    """
    Add constraint ensuring that charger = discharger, i.e.
    1 * charger_size - efficiency * discharger_size = 0
    """
    if not n.links.p_nom_extendable.any():
        return

    discharger_bool = n.links.index.str.contains("battery discharger")
    charger_bool = n.links.index.str.contains("battery charger")

    dischargers_ext = n.links[discharger_bool].query("p_nom_extendable").index
    chargers_ext = n.links[charger_bool].query("p_nom_extendable").index

    eff = n.links.efficiency[dischargers_ext].values
    lhs = (
        n.model["Link-p_nom"].loc[chargers_ext]
        - n.model["Link-p_nom"].loc[dischargers_ext] * eff
    )

    n.model.add_constraints(lhs == 0, name="Link-charger_ratio")


def add_RES_constraints(n, res_share, config):
    """
    The constraint ensures that a predefined share of power is generated
    by renewable sources

    Parameters
    ----------
        n : pypsa.Network
        res_share: float
        config : dict
    """

    logger.warning(
        "The add_RES_constraints() is still work in progress. "
        "Unexpected results might be incurred, particularly if "
        "temporal clustering is applied or if an unexpected change of technologies "
        "is subject to future improvements."
    )

    renew_techs = config["electricity"]["renewable_carriers"]

    charger = ["H2 electrolysis", "battery charger"]
    discharger = ["H2 fuel cell", "battery discharger"]

    ren_gen = n.generators.query("carrier in @renew_techs")
    ren_stores = n.storage_units.query("carrier in @renew_techs")
    ren_charger = n.links.query("carrier in @charger")
    ren_discharger = n.links.query("carrier in @discharger")

    gens_i = ren_gen.index
    stores_i = ren_stores.index
    charger_i = ren_charger.index
    discharger_i = ren_discharger.index

    stores_t_weights = n.snapshot_weightings.stores

    lgrouper = n.loads.bus.map(n.buses.country)
    ggrouper = ren_gen.bus.map(n.buses.country)
    sgrouper = ren_stores.bus.map(n.buses.country)
    cgrouper = ren_charger.bus0.map(n.buses.country)
    dgrouper = ren_discharger.bus0.map(n.buses.country)

    load = (
        n.snapshot_weightings.generators
        @ n.loads_t.p_set.groupby(lgrouper, axis=1).sum()
    )
    rhs = res_share * load

    # Generators
    lhs_gen = (
        (n.model["Generator-p"].loc[:, gens_i] * n.snapshot_weightings.generators)
        .groupby(ggrouper.to_xarray())
        .sum()
    )

    # StorageUnits
    store_disp_expr = (
        n.model["StorageUnit-p_dispatch"].loc[:, stores_i] * stores_t_weights
    )
    store_expr = n.model["StorageUnit-p_store"].loc[:, stores_i] * stores_t_weights
    charge_expr = n.model["Link-p"].loc[:, charger_i] * stores_t_weights.apply(
        lambda r: r * n.links.loc[charger_i].efficiency
    )
    discharge_expr = n.model["Link-p"].loc[:, discharger_i] * stores_t_weights.apply(
        lambda r: r * n.links.loc[discharger_i].efficiency
    )

    lhs_dispatch = store_disp_expr.groupby(sgrouper).sum()
    lhs_store = store_expr.groupby(sgrouper).sum()

    # Stores (or their resp. Link components)
    # Note that the variables "p0" and "p1" currently do not exist.
    # Thus, p0 and p1 must be derived from "p" (which exists), taking into account the link efficiency.
    lhs_charge = charge_expr.groupby(cgrouper).sum()

    lhs_discharge = discharge_expr.groupby(cgrouper).sum()

    lhs = lhs_gen + lhs_dispatch - lhs_store - lhs_charge + lhs_discharge

    n.model.add_constraints(lhs == rhs, name="res_share")


def add_land_use_constraint(n):
    if "m" in snakemake.wildcards.clusters:
        _add_land_use_constraint_m(n)
    else:
        _add_land_use_constraint(n)


def _add_land_use_constraint(n):
    # warning: this will miss existing offwind which is not classed AC-DC and has carrier 'offwind'

    for carrier in ["solar", "solar rooftop", "onwind", "offwind-ac", "offwind-dc"]:
        existing = (
            n.generators.loc[n.generators.carrier == carrier, "p_nom"]
            .groupby(n.generators.bus.map(n.buses.location))
            .sum()
        )
        existing.index += " " + carrier + "-" + snakemake.wildcards.planning_horizons
        n.generators.loc[existing.index, "p_nom_max"] -= existing

    n.generators.p_nom_max.clip(lower=0, inplace=True)

    # Where land use constraint reduces p_nom_max below p_nom / p_nom_min,
    # cap both down to p_nom_max to remain feasible.
    # This happens when existing capacity already exceeds the land use budget.
    violating = n.generators.p_nom_min > n.generators.p_nom_max
    if violating.any():
        logger.warning(
            f"Land use constraint reduced p_nom_max below p_nom/p_nom_min for "
            f"{violating.sum()} generators. Capping p_nom and p_nom_min to p_nom_max:\n"
            f"{n.generators.index[violating].tolist()}"
        )
        n.generators.loc[violating, "p_nom_min"] = n.generators.loc[
            violating, "p_nom_max"
        ]
        n.generators.loc[violating, "p_nom"] = n.generators.loc[violating, "p_nom_max"]


def _add_land_use_constraint_m(n):
    # if generators clustering is lower than network clustering, land_use accounting is at generators clusters

    planning_horizons = snakemake.config["scenario"]["planning_horizons"]
    grouping_years = snakemake.config["existing_capacities"]["grouping_years"]
    current_horizon = snakemake.wildcards.planning_horizons

    for carrier in ["solar", "solar rooftop", "onwind", "offwind-ac", "offwind-dc"]:
        existing = n.generators.loc[n.generators.carrier == carrier, "p_nom"]
        ind = list(
            set(
                [
                    i.split(sep=" ")[0] + " " + i.split(sep=" ")[1]
                    for i in existing.index
                ]
            )
        )

        previous_years = [
            str(y)
            for y in planning_horizons + grouping_years
            if y < int(snakemake.wildcards.planning_horizons)
        ]

        for p_year in previous_years:
            ind2 = [
                i for i in ind if i + " " + carrier + "-" + p_year in existing.index
            ]
            sel_current = [i + " " + carrier + "-" + current_horizon for i in ind2]
            sel_p_year = [i + " " + carrier + "-" + p_year for i in ind2]
            n.generators.loc[sel_current, "p_nom_max"] -= existing.loc[
                sel_p_year
            ].rename(lambda x: x[:-4] + current_horizon)

    n.generators.p_nom_max.clip(lower=0, inplace=True)


def add_h2_network_cap(n, cap):
    h2_network = n.links.loc[n.links.carrier == "H2 pipeline"]
    if h2_network.index.empty:
        return
    h2_network_cap = n.model["Link-p_nom"]
    h2_network_cap_index = h2_network_cap.indexes["Link-ext"]
    subset_index = h2_network.index.intersection(h2_network_cap_index)
    diff_index = h2_network.index.difference(subset_index)
    if len(diff_index) > 0:
        logger.warning(
            f"Impossible to set a limit for H2 pipelines extension for the following links: {diff_index}"
        )
    lhs = (
        h2_network_cap.loc[subset_index] * h2_network.loc[subset_index, "length"]
    ).sum()
    rhs = cap * 1000
    n.model.add_constraints(lhs <= rhs, name="h2_network_cap")


def add_flexible_electrolyzers(n, costs):
    """
    Add a 'Flexible electrolyzer' technology:
    - Same technical and cost parameters as the existing Alkaline electrolyzer (large size)
    - Very high marginal cost so it is used only as last-resort hydrogen production
    - Not subject to 45V constraints (temporal matching, additionality, deliverability)
    """
    logger.info("Adding flexible electrolyzers")

    flex_carrier = "Flexible electrolyzer"
    if flex_carrier not in n.carriers.index:
        n.add("Carrier", flex_carrier)

    ref = "Alkaline electrolyzer large"
    ref_links = n.links[n.links.carrier == ref]
    if ref_links.empty:
        raise ValueError(
            f"Reference electrolyzer '{ref}' not found in the network. "
            f"add_hydrogen() must run before add_flexible_electrolyzers()."
        )

    efficiency = float(ref_links["efficiency"].iloc[0])
    capital_cost = float(ref_links["capital_cost"].iloc[0])
    lifetime = int(ref_links["lifetime"].iloc[0])

    marginal_cost = 1e6

    ac_nodes = ref_links["bus0"].values
    h2_nodes = ref_links["bus1"].values

    # make link names unique
    names = [f"{bus0} {flex_carrier} #{i}" for i, bus0 in enumerate(ac_nodes)]

    n.madd(
        "Link",
        names,
        bus0=ac_nodes,
        bus1=h2_nodes,
        p_nom_extendable=True,
        carrier=flex_carrier,
        efficiency=efficiency,
        capital_cost=capital_cost,
        lifetime=lifetime,
        marginal_cost=marginal_cost,
    )

    # CHECK: fail fast if nothing was added
    if (n.links.carrier == flex_carrier).sum() == 0:
        raise RuntimeError(
            "Flexible electrolyzers were not added (zero links after madd)."
        )

    logger.info(
        f"Flexible electrolyzers added with parameters copied from '{ref}' "
        f"and marginal cost={marginal_cost}"
    )


def hydrogen_temporal_constraint(n, additionality, time_period):
    """
    Enforces temporal matching and additionality for hydrogen production.
    """
    temporal_matching_carriers = snakemake.params.temporal_matching_carriers
    hydrogen_cfg = snakemake.config["policy_config"]["hydrogen"]
    allowed_excess = hydrogen_cfg["allowed_excess"]

    deliverability_period = hydrogen_cfg.get("deliverability_period", "yearly")
    if deliverability_period not in ("yearly", "no_deliverability"):
        raise ValueError(
            "deliverability_period must be 'yearly' or 'no_deliverability'"
        )

    def _period_labels(snapshots, period):
        if period in ("hour", "hourly"):
            return pd.Index(snapshots, name="period")
        if period in ("month", "monthly"):
            return pd.Index(snapshots.month, name="period")
        if period in ("year", "yearly"):
            return pd.Index(snapshots.year, name="period")
        if period == "no_temporal_matching":
            return pd.Index([0] * len(snapshots), name="period")
        raise ValueError(f"Unsupported time period: {period}")

    def _sum_by_period(expr, period):
        labels = _period_labels(n.snapshots, period)
        out = []
        for label in pd.Index(labels).unique():
            snapshots = n.snapshots[labels == label]
            out.append((label, expr.loc[snapshots].sum("snapshot")))
        return out

    weights = xr.DataArray(
        n.snapshot_weightings.generators,
        dims=["snapshot"],
        coords={"snapshot": n.snapshots},
    )

    res_gen_index = n.generators.index[
        n.generators.carrier.isin(temporal_matching_carriers)
    ]
    res_stor_index = n.storage_units.index[
        n.storage_units.carrier.isin(temporal_matching_carriers)
    ]

    electrolysis_carriers = [
        "Alkaline electrolyzer large",
        "Alkaline electrolyzer medium",
        "Alkaline electrolyzer small",
        "PEM electrolyzer",
        "SOEC",
    ]

    electrolyzers = n.links.index[n.links.carrier.isin(electrolysis_carriers)]
    p_link = n.model["Link-p"]
    electrolyzers = electrolyzers.intersection(p_link.indexes["Link"])

    if electrolyzers.empty:
        logger.warning("No electrolyzer Link-p variables found. Skipping H2 matching.")
        return

    electrolysis = p_link.loc[:, electrolyzers]

    if additionality:
        el_build_year = n.links.loc[electrolyzers, "build_year"]
        cohorts = el_build_year.unique()

        gen_by_year = n.generators.build_year
        stor_by_year = n.storage_units.build_year

        allowed_RES = {}
        for year in cohorts:
            allowed_gen = res_gen_index.intersection(
                gen_by_year.index[gen_by_year >= year]
            )
            allowed_stor = res_stor_index.intersection(
                stor_by_year.index[stor_by_year >= year]
            )
            allowed_RES[year] = {"gen": allowed_gen, "stor": allowed_stor}
    else:
        el_build_year = None
        cohorts = []

    logger.info(
        f"setting h2 export to {time_period}ly matching constraint "
        f"{'with' if additionality else 'without'} additionality "
        f"(deliverability period={deliverability_period})"
    )

    region_col = "grid_region"
    if region_col not in n.buses.columns:
        raise ValueError(f"'{region_col}' missing in n.buses")

    gen_region = (
        n.buses.loc[n.generators.loc[res_gen_index, "bus"], region_col].values
        if len(res_gen_index) > 0
        else np.array([])
    )
    stor_region = (
        n.buses.loc[n.storage_units.loc[res_stor_index, "bus"], region_col].values
        if len(res_stor_index) > 0
        else np.array([])
    )
    el_region = n.buses.loc[n.links.loc[electrolyzers, "bus0"], region_col].values

    regions = pd.Index(pd.unique(el_region))

    p_gen = n.model["Generator-p"]
    p_stor = (
        n.model["StorageUnit-p_dispatch"]
        if "StorageUnit-p_dispatch" in n.model.variables
        else None
    )

    if not additionality:
        for region in regions:
            gen_mask = gen_region == region
            stor_mask = stor_region == region
            el_mask = el_region == region

            res_r = None

            if gen_mask.any():
                gens = res_gen_index[gen_mask].intersection(p_gen.indexes["Generator"])
                if len(gens) > 0:
                    res_r = (p_gen.loc[:, gens] * weights).sum("Generator")

            if stor_mask.any() and p_stor is not None:
                storages = res_stor_index[stor_mask].intersection(
                    p_stor.indexes["StorageUnit"]
                )
                if len(storages) > 0:
                    term = (p_stor.loc[:, storages] * weights).sum("StorageUnit")
                    res_r = term if res_r is None else res_r + term

            if res_r is None:
                res_r = xr.DataArray(
                    0.0,
                    dims=["snapshot"],
                    coords={"snapshot": n.snapshots},
                )

            if el_mask.any():
                el_links = electrolyzers[el_mask]
                el_r = (
                    electrolysis.loc[:, el_links] * weights * (-allowed_excess)
                ).sum("Link")
            else:
                el_r = xr.DataArray(
                    0.0,
                    dims=["snapshot"],
                    coords={"snapshot": n.snapshots},
                )

            res_r_agg = _sum_by_period(res_r, time_period)
            el_r_agg = _sum_by_period(el_r, time_period)

            for i, ((_, res_expr), (_, el_expr)) in enumerate(zip(res_r_agg, el_r_agg)):
                lhs = res_expr + el_expr
                n.model.add_constraints(
                    lhs >= 0.0,
                    name=f"RESconstraints_tm_reg_{region}_{i}_REStarget_tm_reg_{region}_{i}",
                )

    if additionality and len(cohorts) > 0:
        cohorts_sorted = np.sort(cohorts)

        for region in regions:
            gen_mask_r = gen_region == region
            stor_mask_r = stor_region == region
            el_mask_r = el_region == region

            for year in cohorts_sorted:
                gens_y = allowed_RES[year]["gen"].intersection(
                    res_gen_index[gen_mask_r]
                )
                stor_y = allowed_RES[year]["stor"].intersection(
                    res_stor_index[stor_mask_r]
                )

                res_y_r = None

                gens_y = gens_y.intersection(p_gen.indexes["Generator"])
                if len(gens_y) > 0:
                    res_y_r = (p_gen.loc[:, gens_y] * weights).sum("Generator")

                if p_stor is not None:
                    stor_y = stor_y.intersection(p_stor.indexes["StorageUnit"])
                    if len(stor_y) > 0:
                        term = (p_stor.loc[:, stor_y] * weights).sum("StorageUnit")
                        res_y_r = term if res_y_r is None else res_y_r + term

                if res_y_r is None:
                    res_y_r = xr.DataArray(
                        0.0,
                        dims=["snapshot"],
                        coords={"snapshot": n.snapshots},
                    )

                el_mask_yplus_r = ((el_build_year >= year).values) & el_mask_r
                el_cols_yplus_r = electrolyzers[el_mask_yplus_r]

                if len(el_cols_yplus_r) > 0:
                    el_input_yplus_r = (
                        electrolysis.loc[:, el_cols_yplus_r]
                        * weights
                        * (-allowed_excess)
                    ).sum("Link")
                else:
                    el_input_yplus_r = xr.DataArray(
                        0.0,
                        dims=["snapshot"],
                        coords={"snapshot": n.snapshots},
                    )

                res_y_r_agg = _sum_by_period(res_y_r, time_period)
                el_input_yplus_r_agg = _sum_by_period(
                    el_input_yplus_r,
                    time_period,
                )

                for i, ((_, res_expr), (_, el_expr)) in enumerate(
                    zip(res_y_r_agg, el_input_yplus_r_agg)
                ):
                    lhs = res_expr + el_expr
                    n.model.add_constraints(
                        lhs >= 0.0,
                        name=(
                            "RESconstraints_additionality_threshold_"
                            f"{region}_{year}_{i}_"
                            "REStarget_additionality_threshold_"
                            f"{region}_{year}_{i}"
                        ),
                    )


def add_chp_constraints(n):
    if n.links.empty:
        return

    electric_bool = (
        n.links.index.str.contains("urban central")
        & n.links.index.str.contains("CHP")
        & n.links.index.str.contains("electric")
    )
    heat_bool = (
        n.links.index.str.contains("urban central")
        & n.links.index.str.contains("CHP")
        & n.links.index.str.contains("heat")
    )

    electric = n.links.index[electric_bool]
    heat = n.links.index[heat_bool]

    electric_ext = n.links[electric_bool].query("p_nom_extendable").index
    heat_ext = n.links[heat_bool].query("p_nom_extendable").index

    electric_fix = n.links[electric_bool].query("~p_nom_extendable").index
    heat_fix = n.links[heat_bool].query("~p_nom_extendable").index

    p = n.model["Link-p"]  # dimension: [time, link]

    # output ratio between heat and electricity and top_iso_fuel_line for extendable
    if not electric_ext.empty:
        p_nom = n.model["Link-p_nom"]

        lhs = (
            p_nom.loc[electric_ext]
            * (n.links.p_nom_ratio * n.links.efficiency)[electric_ext].values
            - p_nom.loc[heat_ext] * n.links.efficiency[heat_ext].values
        )
        n.model.add_constraints(lhs == 0, name="chplink-fix_p_nom_ratio")

        rename = {"Link-ext": "Link"}
        lhs = (
            p.loc[:, electric_ext]
            + p.loc[:, heat_ext]
            - p_nom.rename(rename).loc[electric_ext]
        )
        n.model.add_constraints(lhs <= 0, name="chplink-top_iso_fuel_line_ext")

    # top_iso_fuel_line for fixed
    if not electric_fix.empty:
        lhs = p.loc[:, electric_fix] + p.loc[:, heat_fix]
        rhs = n.links.p_nom[electric_fix]
        n.model.add_constraints(lhs <= rhs, name="chplink-top_iso_fuel_line_fix")

    # back-pressure
    if not electric.empty:
        lhs = (
            p.loc[:, heat] * (n.links.efficiency[heat] * n.links.c_b[electric].values)
            - p.loc[:, electric] * n.links.efficiency[electric]
        )
        n.model.add_constraints(lhs <= 0, name="chplink-backpressure")


def add_co2_sequestration_limit(n, sns):
    co2_stores = n.stores.loc[n.stores.carrier == "co2 stored"].index

    if co2_stores.empty:
        return

    vars_final_co2_stored = n.model["Store-e"].loc[sns[-1], co2_stores]

    lhs = (1 * vars_final_co2_stored).sum()
    rhs = (
        n.config["sector"].get("co2_sequestration_potential", 5) * 1e6
    )  # TODO change 200 limit (Europe)

    name = "co2_sequestration_limit"

    n.model.add_constraints(lhs <= rhs, name=f"GlobalConstraint-{name}")


def set_h2_colors(n):
    blue_h2 = n.model["Link-p"].loc[
        n.links.index[n.links.index.str.contains("blue H2")]
    ]

    pink_h2 = n.model["Link-p"].loc[
        n.links.index[n.links.index.str.contains("pink H2")]
    ]

    fuelcell_ind = n.loads[n.loads.carrier == "land transport fuel cell"].index

    other_ind = n.loads[
        (n.loads.carrier == "H2 for industry")
        | (n.loads.carrier == "H2 for shipping")
        | (n.loads.carrier == "H2")
    ].index

    load_fuelcell = (
        n.loads_t.p_set[fuelcell_ind].sum(axis=1) * n.snapshot_weightings["generators"]
    ).sum()

    load_other_h2 = n.loads.loc[other_ind].p_set.sum() * 8760

    load_h2 = load_fuelcell + load_other_h2

    weightings_blue = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(blue_h2.columns)),
        index=n.snapshots,
        columns=blue_h2.columns,
    )

    weightings_pink = pd.DataFrame(
        np.outer(n.snapshot_weightings["generators"], [1.0] * len(pink_h2.columns)),
        index=n.snapshots,
        columns=pink_h2.columns,
    )

    total_blue = (weightings_blue * blue_h2).sum().sum()

    total_pink = (weightings_pink * pink_h2).sum().sum()

    rhs_blue = load_h2 * snakemake.config["sector"]["hydrogen"]["blue_share"]
    rhs_pink = load_h2 * snakemake.config["sector"]["hydrogen"]["pink_share"]

    n.model.add_constraints(total_blue == rhs_blue, name="blue_h2_share")

    n.model.add_constraints(total_pink == rhs_pink, name="pink_h2_share")


def add_existing(n):
    if snakemake.wildcards["planning_horizons"] == "2050":
        directory = (
            "results/"
            + "Existing_capacities/"
            + snakemake.config["run"].replace("2050", "2030")
        )
        n_name = (
            snakemake.input.network.split("/")[-1]
            .replace(str(snakemake.config["scenario"]["clusters"][0]), "")
            .replace(str(snakemake.config["costs"]["discountrate"][0]), "")
            .replace("_presec", "")
            .replace(".nc", ".csv")
        )
        df = read_csv_nafix(directory + "/electrolyzer_caps_" + n_name, index_col=0)
        existing_electrolyzers = df.p_nom_opt.values

        h2_index = n.links[n.links.carrier == "H2 Electrolysis"].index
        n.links.loc[h2_index, "p_nom_min"] = existing_electrolyzers

        # n_name = snakemake.input.network.split("/")[-1].replace(str(snakemake.config["scenario"]["clusters"][0]), "").\
        #     replace(".nc", ".csv").replace(str(snakemake.config["costs"]["discountrate"][0]), "")
        df = read_csv_nafix(directory + "/res_caps_" + n_name, index_col=0)

        for tech in snakemake.config["custom_data"]["renewables"]:
            # df = read_csv_nafix(snakemake.config["custom_data"]["existing_renewables"], index_col=0)
            existing_res = df.loc[tech]
            existing_res.index = existing_res.index.str.apply(lambda x: x + tech)
            tech_index = n.generators[n.generators.carrier == tech].index
            n.generators.loc[tech_index, tech] = existing_res


def add_lossy_bidirectional_link_constraints(n: pypsa.components.Network) -> None:
    """
    Ensures that the two links simulating a bidirectional_link are extended the same amount.
    """

    if not n.links.p_nom_extendable.any() or "reversed" not in n.links.columns:
        return

    # ensure that the 'reversed' column is boolean and identify all link carriers that have 'reversed' links
    n.links["reversed"] = n.links.reversed.fillna(0).astype(bool)
    carriers = n.links.loc[n.links.reversed, "carrier"].unique()  # noqa: F841

    # get the indices of all forward links (non-reversed), that have a reversed counterpart
    forward_i = n.links.query(
        "carrier in @carriers and ~reversed and p_nom_extendable"
    ).index

    # function to get backward (reversed) indices corresponding to forward links
    # this function is required to properly interact with the myopic naming scheme
    def get_backward_i(forward_i):
        return pd.Index(
            [
                (
                    re.sub(r"-(\d{4})$", r"-reversed-\1", s)
                    if re.search(r"-\d{4}$", s)
                    else s + "-reversed"
                )
                for s in forward_i
            ]
        )

    # get the indices of all backward links (reversed)
    backward_i = get_backward_i(forward_i)

    # Get the p_nom optimization variables for the links
    links_p_nom = n.model["Link-p_nom"]

    # only consider forward and backward links that are present in the optimization variables
    subset_forward = forward_i.intersection(links_p_nom.indexes["Link-ext"])
    subset_backward = backward_i.intersection(links_p_nom.indexes["Link-ext"])

    # ensure we have a matching number of forward and backward links
    if len(subset_forward) != len(subset_backward):
        raise ValueError("Mismatch between forward and backward links.")

    # define the lefthand side of the constrain p_nom (forward) - p_nom (backward) = 0
    # this ensures that the forward links always have the same maximum nominal power as their backward counterpart
    lhs = links_p_nom.loc[backward_i] - links_p_nom.loc[forward_i]

    # add the constraint to the PySPA model
    n.model.add_constraints(lhs == 0, name="Link-bidirectional_sync")


def extra_functionality(n, snapshots):
    """
    Collects supplementary constraints which will be passed to
    ``pypsa.linopf.network_lopf``.

    If you want to enforce additional custom constraints, this is a good location to add them.
    The arguments ``opts`` and ``snakemake.config`` are expected to be attached to the network.
    """
    opts = n.opts
    config = n.config
    if "BAU" in opts and n.generators.p_nom_extendable.any():
        add_BAU_constraints(n, config)
    if "SAFE" in opts and n.generators.p_nom_extendable.any():
        add_SAFE_constraints(n, config)
    if "CCL" in opts and n.generators.p_nom_extendable.any():
        add_CCL_constraints(n, config)
    reserve = config["electricity"].get("operational_reserve", {})
    if reserve.get("activate"):
        add_operational_reserve_margin(n, snapshots, config)
    for o in opts:
        if "RES" in o:
            res_share = float(re.findall(r"[0-9]*\.?[0-9]+$", o)[0])
            add_RES_constraints(n, res_share, config)
    for o in opts:
        if "EQ" in o:
            add_EQ_constraints(n, o)

    add_battery_constraints(n)
    add_lossy_bidirectional_link_constraints(n)

    if snakemake.config["sector"]["chp"]:
        logger.info("setting CHP constraints")
        add_chp_constraints(n)

    add_flexible_electrolyzers(n, read_csv_nafix(snakemake.input.costs, index_col=0))
    add_h2_production_constraints(n, config)

    additionality = snakemake.config["policy_config"]["hydrogen"]["additionality"]
    temporal_matching_period = snakemake.config["policy_config"]["hydrogen"][
        "temporal_matching"
    ]

    if temporal_matching_period == "no_temporal_matching":
        logger.info("No H2 temporal matching constraint set.")
    elif temporal_matching_period in ["hourly", "monthly", "yearly"]:
        hydrogen_temporal_constraint(n, additionality, temporal_matching_period[:-2])
    else:
        raise ValueError("Invalid H2 temporal matching option.")

    if config["state_policy"] == "on" and n.generators.p_nom_extendable.any():
        add_RPS_constraints(n, config)

    if snakemake.config["sector"]["hydrogen"]["network"]:
        if snakemake.config["sector"]["hydrogen"]["network_limit"]:
            add_h2_network_cap(
                n, snakemake.config["sector"]["hydrogen"]["network_limit"]
            )

    if snakemake.config["sector"]["hydrogen"]["set_color_shares"]:
        logger.info("setting H2 color mix")
        set_h2_colors(n)

    add_co2_sequestration_limit(n, snapshots)


def solve_network(n, config, solving, **kwargs):
    set_of_options = solving["solver"]["options"]
    cf_solving = solving["options"]

    kwargs["solver_options"] = (
        solving["solver_options"][set_of_options] if set_of_options else {}
    )
    kwargs["solver_name"] = solving["solver"]["name"]
    kwargs["extra_functionality"] = extra_functionality

    skip_iterations = cf_solving.get("skip_iterations", False)
    if not n.lines.s_nom_extendable.any():
        skip_iterations = True
        logger.info("No expandable lines found. Skipping iterative solving.")

    # add to network for extra_functionality
    n.config = config
    n.opts = opts

    if skip_iterations:
        status, condition = n.optimize(**kwargs)
    else:
        kwargs["track_iterations"] = (cf_solving.get("track_iterations", False),)
        kwargs["min_iterations"] = (cf_solving.get("min_iterations", 4),)
        kwargs["max_iterations"] = (cf_solving.get("max_iterations", 6),)
        status, condition = n.optimize.optimize_transmission_expansion_iteratively(
            **kwargs
        )

    if status != "ok":  # and not rolling_horizon:
        logger.warning(
            f"Solving status '{status}' with termination condition '{condition}'"
        )
    if "infeasible" in condition:
        labels = n.model.compute_infeasibilities()
        logger.info(f"Labels:\n{labels}")
        n.model.print_infeasibilities()
        raise RuntimeError("Solving status 'infeasible'")

    return n


if __name__ == "__main__":
    if "snakemake" not in globals():
        from _helpers import mock_snakemake

        snakemake = mock_snakemake(
            "solve_sector_network",
            simpl="",
            clusters="4",
            ll="c1",
            opts="Co2L-4H",
            planning_horizons="2030",
            discountrate="0.071",
            demand="AB",
            sopts="144H",
            h2export="120",
            configfile="config.tutorial.yaml",
        )

    configure_logging(snakemake)

    opts = snakemake.wildcards.opts.split("-")
    solve_opts = snakemake.config["solving"]["options"]

    is_sector_coupled = "sopts" in snakemake.wildcards.keys()

    overrides = override_component_attrs(snakemake.input.overrides)
    n = pypsa.Network(snakemake.input.network, override_component_attrs=overrides)

    n = attach_grid_region_to_buses(
        n,
        path_shapes=snakemake.input.grid_regions_shape_path,
        grid_region_field=snakemake.params.grid_region_field,
        distance_crs=snakemake.params.distance_crs,
    )

    Nyears = n.snapshot_weightings.objective.sum() / 8760.0
    costs = load_costs(
        snakemake.input.costs,
        snakemake.config["costs"],
        snakemake.config["electricity"],
        Nyears,
    )

    if snakemake.params.augmented_line_connection.get("add_to_snakefile"):
        if not n.lines.empty:
            n.lines.loc[n.lines.index.str.contains("new"), "s_nom_min"] = (
                snakemake.params.augmented_line_connection.get("min_expansion")
            )

    if (
        snakemake.config["custom_data"]["add_existing"]
        and snakemake.wildcards.planning_horizons == "2050"
        and is_sector_coupled
    ):
        add_existing(n)

    n = prepare_network(n, solve_opts, config=snakemake.config)

    propagate_base_year_efficiencies(n)

    for comp_df in [n.generators, n.links]:
        if "_marginal_cost_original" not in comp_df.columns:
            comp_df["_marginal_cost_original"] = comp_df["marginal_cost"]
        else:
            new_rows = comp_df["_marginal_cost_original"].isna()
            comp_df.loc[new_rows, "_marginal_cost_original"] = comp_df.loc[
                new_rows, "marginal_cost"
            ]

    for comp_df in [n.generators, n.links]:
        comp_df["marginal_cost"] = comp_df["_marginal_cost_original"]

    logger.info(f"Applying tax credits for {snakemake.wildcards.planning_horizons}")
    apply_tax_credits_to_network(
        n,
        ptc_path=snakemake.input.production_tax_credits,
        itc_path=snakemake.input.investment_tax_credits,
        planning_horizon=int(snakemake.wildcards.planning_horizons),
        costs=costs,
        config_file=snakemake.config,
        log_path=f"logs/tax_credit_modifications_{snakemake.wildcards.planning_horizons}.csv",
        verbose=False,
    )

    if snakemake.config.get("line_expansion_limits", None):
        ll_expansion_limit = snakemake.config["line_expansion_limits"][
            int(snakemake.wildcards.planning_horizons)
        ]
        ll_type, factor = ll_expansion_limit[0], ll_expansion_limit[1:]
        set_transmission_limit(
            n, ll_type=ll_type, factor=factor, costs=costs, Nyears=Nyears
        )

    n = solve_network(
        n,
        config=snakemake.config,
        solving=snakemake.params.solving,
        log_fn=snakemake.log.solver,
    )
    n.meta = dict(snakemake.config, **dict(wildcards=dict(snakemake.wildcards)))
    n.export_to_netcdf(snakemake.output[0])
    logger.info(f"Objective function: {n.objective}")
    logger.info(f"Objective constant: {n.objective_constant}")
