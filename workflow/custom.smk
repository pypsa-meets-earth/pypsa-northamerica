# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from snakemake.utils import min_version

min_version("6.0")

import sys

sys.path.append("scripts")

from snakemake.remote.HTTP import RemoteProvider as HTTPRemoteProvider
from scripts.custom._helper import renewable_profiles_outputs

HTTP = HTTPRemoteProvider()

RESULTS_DIR = "../plots/results/"
PYPSA_EARTH_DIR = ""
CUSTOM_USA_DATA_DIR = "data/custom/usa/"


# Import the base standalone workflow as a module with custom rules disabled.
# Only selected rules are copied below under *_custom names.
module pypsa_earth:
    snakefile:
        "../Snakefile"
    config:
        {**config, "custom_rules": []}


configfile: "config.default.yaml"
configfile: "configs/bundle_config.yaml"
configfile: "configs/custom/config.main.yaml"


wildcard_constraints:
    simpl="[a-zA-Z0-9]*|all",
    clusters="[0-9]+(m|flex)?|all|min",
    ll="(v|c)([0-9.]+|opt|all)|all",
    opts="[-+a-zA-Z0-9.]*",
    unc="[-+a-zA-Z0-9.]*",
    planning_horizon="[0-9]{4}",
    countries="[A-Z]{2}",


run = config["run"]
RDIR = run["name"] + "/" if run.get("name") else ""
CDIR = RDIR if not run.get("shared_cutouts") else ""
SECDIR = run["sector_name"] + "/" if run.get("sector_name") else ""
SDIR = config["summary_dir"].strip("/") + f"/{SECDIR}"
RESDIR = config["results_dir"].strip("/") + f"/{SECDIR}"


localrules:
    all,


rule process_airport_data:
    input:
        fuel_data=CUSTOM_USA_DATA_DIR + "airport_data/fuel_jf.csv",
        airport_data=CUSTOM_USA_DATA_DIR + "airport_data/airports.csv",
        passengers_data=CUSTOM_USA_DATA_DIR
        + "airport_data/T100_Domestic_Market_and_Segment_Data_-3591723781169319541.csv",
        aviation_demand=CUSTOM_USA_DATA_DIR + "icct/aviation_demand.csv",
    output:
        statewise_output="plots/results/passengers_vs_consumption.csv",
        merged_data="plots/results/merged_airports.csv",
        consumption_per_passenger="plots/results/consumption_per_passenger.png",
        correlation_matrix="plots/results/correlation_matrix.png",
        comparision_consumption_passengers="plots/results/comparision_consumption_passengers.png",
        custom_airports_data=PYPSA_EARTH_DIR + "resources/" + SECDIR + "airports.csv",
    resources:
        mem_mb=3000,
    script:
        "../scripts/custom/process_airport_data.py"


rule generate_aviation_scenario:
    input:
        aviation_demand_data=CUSTOM_USA_DATA_DIR
        + "icct/US Aviation Fuel Demand Projection_NP_0.1.xls",
    output:
        scenario_df=CUSTOM_USA_DATA_DIR + "icct/aviation_demand.csv",
    resources:
        mem_mb=3000,
    script:
        "../scripts/custom/generate_aviation_scenarios.py"


if config["custom_data"]["airports"]:

    ruleorder: process_airport_data > prepare_airports

else:

    ruleorder: prepare_airports > process_airport_data


if config["countries"] == ["US"] and config["retrieve_precomputed"].get(
    "cutouts", False
):

    rule retrieve_cutouts:
        params:
            countries=config["countries"],
        output:
            cutouts=PYPSA_EARTH_DIR + "cutouts/cutout-2013-era5.nc",
        resources:
            mem_mb=16000,
        script:
            "../scripts/custom/retrieve_cutouts.py"


# retrieving precomputed osm/raw data and bypassing download_osm_data rule
if config["countries"] == ["US"] and config["retrieve_precomputed"].get(
    "osm_raw", False
):

    rule retrieve_osm_raw:
        params:
            destination="resources/" + RDIR,
        output:
            cables="resources/" + RDIR + "osm/raw/all_raw_cables.geojson",
            generators="resources/" + RDIR + "osm/raw/all_raw_generators.geojson",
            generators_csv="resources/" + RDIR + "osm/raw/all_raw_generators.csv",
            lines="resources/" + RDIR + "osm/raw/all_raw_lines.geojson",
            substations="resources/" + RDIR + "osm/raw/all_raw_substations.geojson",
        script:
            "../scripts/custom/retrieve_osm_raw.py"

    ruleorder: retrieve_osm_raw > download_osm_data


# retrieving precomputed osm/clean data and bypassing clean_osm_data rule
if config["countries"] == ["US"] and config["retrieve_precomputed"].get(
    "osm_clean", False
):

    rule retrieve_osm_clean:
        params:
            destination="resources/" + RDIR,
        output:
            generators="resources/" + RDIR + "osm/clean/all_clean_generators.geojson",
            generators_csv="resources/" + RDIR + "osm/clean/all_clean_generators.csv",
            lines="resources/" + RDIR + "osm/clean/all_clean_lines.geojson",
            substations="resources/" + RDIR + "osm/clean/all_clean_substations.geojson",
        script:
            "../scripts/custom/retrieve_osm_clean.py"

    ruleorder: retrieve_osm_clean > clean_osm_data


# retrieving shapes data and bypassing build_shapes rule
if config["countries"] == ["US"] and config["retrieve_precomputed"].get(
    "shapes", False
):

    rule retrieve_shapes:
        params:
            destination="resources/" + RDIR,
        output:
            country_shapes="resources/" + RDIR + "shapes/country_shapes.geojson",
            offshore_shapes="resources/" + RDIR + "shapes/offshore_shapes.geojson",
            gadm_shapes="resources/" + RDIR + "shapes/gadm_shapes.geojson",
            africa_shape="resources/" + RDIR + "shapes/africa_shape.geojson",
        script:
            "../scripts/custom/retrieve_shapes.py"

    ruleorder: retrieve_shapes > build_shapes


# retrieving base_network data and bypassing build_osm_network rule
if config["countries"] == ["US"] and config["retrieve_precomputed"].get(
    "osm_network", False
):

    rule retrieve_osm_network:
        params:
            destination="resources/" + RDIR,
        input:
            generators="resources/" + RDIR + "osm/clean/all_clean_generators.geojson",
            lines="resources/" + RDIR + "osm/clean/all_clean_lines.geojson",
            substations="resources/" + RDIR + "osm/clean/all_clean_substations.geojson",
            country_shapes="resources/" + RDIR + "shapes/country_shapes.geojson",
        output:
            lines="resources/" + RDIR + "base_network/all_lines_build_network.csv",
            converters="resources/"
            + RDIR
            + "base_network/all_converters_build_network.csv",
            transformers="resources/"
            + RDIR
            + "base_network/all_transformers_build_network.csv",
            substations="resources/" + RDIR + "base_network/all_buses_build_network.csv",
        script:
            "../scripts/custom/retrieve_osm_network.py"

    ruleorder: retrieve_osm_network > build_osm_network


# retrieving base.nc and bypassing base_network rule
if config["countries"] == ["US"] and config["retrieve_precomputed"].get(
    "base_network", False
):

    rule retrieve_base_network:
        input:
            osm_buses="resources/" + RDIR + "base_network/all_buses_build_network.csv",
            osm_lines="resources/" + RDIR + "base_network/all_lines_build_network.csv",
            osm_converters="resources/"
            + RDIR
            + "base_network/all_converters_build_network.csv",
            osm_transformers="resources/"
            + RDIR
            + "base_network/all_transformers_build_network.csv",
            country_shapes="resources/" + RDIR + "shapes/country_shapes.geojson",
            offshore_shapes="resources/" + RDIR + "shapes/offshore_shapes.geojson",
        output:
            PYPSA_EARTH_DIR + "networks/" + RDIR + "base.nc",
        script:
            "../scripts/custom/retrieve_base_network.py"

    ruleorder: retrieve_base_network > base_network


# retrieving renewable_profiles data and bypassing build_renewable_profiles rule
if config["countries"] == ["US"] and config["retrieve_precomputed"].get(
    "renewable_profiles", False
):

    rule retrieve_renewable_profiles:
        params:
            destination="resources/" + RDIR,
            alternative_clustering=config["cluster_options"]["alternative_clustering"],
        output:
            expand(
                "{PYPSA_EARTH_DIR}resources/{RDIR}{file}",
                PYPSA_EARTH_DIR=PYPSA_EARTH_DIR,
                RDIR=RDIR,
                file=renewable_profiles_outputs(),
            ),
        script:
            "../scripts/custom/retrieve_renewable_profiles.py"

    ruleorder: retrieve_renewable_profiles > build_renewable_profiles


if config["countries"] == ["US"]:

    use rule build_powerplants from pypsa_earth as build_powerplants_custom with:
        input:
            base_network="networks/" + RDIR + "base.nc",
            pm_config="configs/powerplantmatching_config.yaml",
            custom_powerplants=CUSTOM_USA_DATA_DIR + "custom_powerplants.csv",
            osm_powerplants="resources/" + RDIR + "osm/clean/all_clean_generators.csv",
            gadm_shapes="resources/" + RDIR + "shapes/gadm_shapes.geojson",

    ruleorder: build_powerplants_custom > build_powerplants


if config["countries"] == ["US"]:

    rule retrieve_ssp2:
        input:
            old_path=CUSTOM_USA_DATA_DIR + "NorthAmerica.csv",
        output:
            ssp2_northamerica=PYPSA_EARTH_DIR
            + "data/ssp2-2.6/2030/era5_2013/NorthAmerica.csv",
        script:
            "../scripts/custom/retrieve_ssp2.py"

    use rule build_demand_profiles from pypsa_earth as build_demand_profiles_custom with:
        input:
            base_network="networks/" + RDIR + "base.nc",
            regions="resources/" + RDIR + "bus_regions/regions_onshore.geojson",
            load=rules.retrieve_ssp2.output.ssp2_northamerica,
            gadm_shapes="resources/" + RDIR + "shapes/gadm_shapes.geojson",


if config["retrieve_precomputed"].get("demand_profiles", False):

    rule retrieve_test_demand_profiles:
        output:
            demand_profile_path="resources/NA_test/demand_profiles.csv",
        params:
            url=config["custom_databundles"]["bundle_demand_profiles_NA_test"]["urls"][
                "zenodo"
            ],
        shell:
            """
            mkdir -p resources/NA_test
            wget -q -O {output.demand_profile_path}.gz {params.url}
            gunzip -f {output.demand_profile_path}.gz
            """

    ruleorder: retrieve_test_demand_profiles > build_demand_profiles_from_eia > build_demand_profiles_custom > build_demand_profiles


if config["countries"] == ["US"]:

    rule prepare_growth_rate_scenarios:
        input:
            source_growth_factors=lambda wildcards: CUSTOM_USA_DATA_DIR
            + "US_growth_rates/{config['demand_projection']['scenario']}/growth_factors_cagr.csv",
            source_industry_growth=lambda wildcards: CUSTOM_USA_DATA_DIR
            + "US_growth_rates/{config['demand_projection']['scenario']}/industry_growth_cagr.csv",
        output:
            growth_factors_cagr=PYPSA_EARTH_DIR + "data/demand/growth_factors_cagr.csv",
            industry_growth_cagr=PYPSA_EARTH_DIR
            + "data/demand/industry_growth_cagr.csv",
        script:
            "../scripts/custom/prepare_growth_rate_scenarios.py"

    use rule prepare_energy_totals from pypsa_earth as prepare_energy_totals_custom with:
        params:
            countries=config["countries"],
            base_year=config["demand_data"]["base_year"],
            sector_options=config["sector"],
        output:
            energy_totals=PYPSA_EARTH_DIR
            + "resources/"
            + SECDIR
            + "energy_totals_{demand}_{planning_horizons}_aviation_mod.csv",

    rule modify_aviation_demand:
        input:
            aviation_demand=CUSTOM_USA_DATA_DIR + "icct/aviation_demand.csv",
            energy_totals=PYPSA_EARTH_DIR
            + "resources/"
            + SECDIR
            + "energy_totals_{demand}_{planning_horizons}_aviation_mod.csv",
        output:
            energy_totals=PYPSA_EARTH_DIR
            + "resources/"
            + SECDIR
            + "energy_totals_{demand}_{planning_horizons}.csv",
        script:
            "../scripts/custom/modify_aviation_demand.py"

    ruleorder: modify_aviation_demand > prepare_energy_totals_custom > prepare_energy_totals


if config["demand_distribution"]["enable"]:

    rule preprocess_demand_data:
        input:
            demand_utility_path=CUSTOM_USA_DATA_DIR
            + "demand_data/table_10_EIA_utility_sales.xlsx",
            country_gadm_path=PYPSA_EARTH_DIR
            + "resources/"
            + RDIR
            + "shapes/country_shapes.geojson",
            erst_path=CUSTOM_USA_DATA_DIR
            + "demand_data/Electric_Retail_Service_Territories.geojson",
            gadm_usa_path=CUSTOM_USA_DATA_DIR + "demand_data/gadm41_USA_1.json",
            eia_per_capita_path=CUSTOM_USA_DATA_DIR + "demand_data/use_es_capita.xlsx",
            additional_demand_path=CUSTOM_USA_DATA_DIR + "demand_data/HS861_2010-.xlsx",
        output:
            utility_demand_path=CUSTOM_USA_DATA_DIR
            + "demand_data/ERST_mapped_demand_centroids.geojson",
        script:
            "../scripts/custom/preprocess_demand_data.py"

    rule retrieve_demand_data:
        output:
            CUSTOM_USA_DATA_DIR + "demand_data/table_10_EIA_utility_sales.xlsx",
            CUSTOM_USA_DATA_DIR
            + "demand_data/Electric_Retail_Service_Territories.geojson",
            CUSTOM_USA_DATA_DIR + "demand_data/gadm41_USA_1.json",
            CUSTOM_USA_DATA_DIR + "demand_data/use_es_capita.xlsx",
            CUSTOM_USA_DATA_DIR + "demand_data/HS861_2010-.xlsx",
            CUSTOM_USA_DATA_DIR + "demand_data/Balancing_Authorities.geojson",
            CUSTOM_USA_DATA_DIR + "demand_data/EIA930_2023_Jan_Jun_opt.csv",
            CUSTOM_USA_DATA_DIR + "demand_data/EIA930_2023_Jul_Dec_opt.csv",
        script:
            "../scripts/custom/retrieve_demand_data.py"

    rule build_demand_profiles_from_eia:
        params:
            demand_projections=CUSTOM_USA_DATA_DIR + "demand_projections/",
            demand_horizon=config["demand_projection"]["planning_horizon"],
            demand_scenario=config["demand_projection"]["scenario"],
            data_center_profiles=CUSTOM_USA_DATA_DIR + "data_center_profiles/",
            geo_crs=config["crs"]["geo_crs"],
        input:
            BA_demand_path1=CUSTOM_USA_DATA_DIR
            + "demand_data/EIA930_2023_Jan_Jun_opt.csv",
            BA_demand_path2=CUSTOM_USA_DATA_DIR
            + "demand_data/EIA930_2023_Jul_Dec_opt.csv",
            BA_shape_path=CUSTOM_USA_DATA_DIR
            + "demand_data/Balancing_Authorities.geojson",
            utility_demand_path=CUSTOM_USA_DATA_DIR
            + "demand_data/ERST_mapped_demand_centroids.geojson",
            base_network=PYPSA_EARTH_DIR + "networks/" + RDIR + "base.nc",
            gadm_shape=CUSTOM_USA_DATA_DIR + "demand_data/gadm41_USA_1.json",
        output:
            demand_profile_path=PYPSA_EARTH_DIR
            + "resources/"
            + RDIR
            + "demand_profiles.csv",
        script:
            "../scripts/custom/build_demand_profiles_from_eia.py"

    ruleorder: build_demand_profiles_from_eia > build_demand_profiles_custom > build_demand_profiles


if config["saf_mandate"]["ekerosene_split"]:

    rule set_saf_mandate:
        params:
            non_spatial_ekerosene=config["saf_mandate"]["non_spatial_ekerosene"],
            saf_scenario=config["saf_mandate"]["saf_scenario"],
        input:
            network=PYPSA_EARTH_DIR
            + "results/"
            + SECDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}.nc",
            saf_scenarios=CUSTOM_USA_DATA_DIR + "saf_blending_rates/saf_scenarios.csv",
        output:
            modified_network=PYPSA_EARTH_DIR
            + "results/"
            + SECDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_saf.nc",
        script:
            "../scripts/custom/set_saf_mandate.py"


saf_suffix = "_saf" if config["saf_mandate"]["ekerosene_split"] else ""


if config["countries"] == ["US"]:

    use rule retrieve_us_cities_dataset from pypsa_earth as retrieve_us_cities_dataset_custom with:
        log:
            "data/industry/retrieve_us_cities_dataset.log",

    use rule retrieve_ammonia_dataset from pypsa_earth as retrieve_ammonia_dataset_custom with:
        log:
            "data/industry/retrieve_ammonia_dataset.log",

    ruleorder: retrieve_us_cities_dataset_custom > retrieve_us_cities_dataset
    ruleorder: retrieve_ammonia_dataset_custom > retrieve_ammonia_dataset


if config["custom_industry"]["enable"]:

    rule build_custom_industry_demand:
        params:
            countries=config["countries"],
            add_ethanol=config["custom_industry"]["ethanol"],
            add_ammonia=config["custom_industry"]["ammonia"],
            add_steel=config["custom_industry"]["steel"],
            add_cement=config["custom_industry"]["cement"],
            gadm_layer_id=config["build_shape_options"]["gadm_layer_id"],
            alternative_clustering=config["cluster_options"]["alternative_clustering"],
            industry_database=config["custom_data"]["industry_database"],
        input:
            uscity_map=CUSTOM_USA_DATA_DIR + "industry_data/uscities.csv",
            ethanol_plants=CUSTOM_USA_DATA_DIR + "industry_data/ethanolcapacity.xlsx",
            ammonia_plants=CUSTOM_USA_DATA_DIR + "industry_data/ammoniacapacity.xlsx",
            shapes_path=PYPSA_EARTH_DIR
            + "resources/"
            + RDIR
            + "bus_regions/regions_onshore_elec_s{simpl}_{clusters}.geojson",
            pypsa_earth_industrial_database="resources/industrial_database.csv",
            industry_growth_cagr=PYPSA_EARTH_DIR
            + "data/demand/industry_growth_cagr.csv",
        output:
            industrial_energy_demand_per_node=PYPSA_EARTH_DIR
            + "resources/"
            + SECDIR
            + "demand/industrial_energy_demand_per_node_elec_s{simpl}_{clusters}_{planning_horizons}_{demand}_custom_industry.csv",
        threads: 1
        resources:
            mem_mb=2000,
        script:
            "../scripts/custom/build_custom_industry_demand.py"

    rule add_custom_industry:
        params:
            costs=config["costs"],
            add_ethanol=config["custom_industry"]["ethanol"],
            add_ammonia=config["custom_industry"]["ammonia"],
            add_steel=config["custom_industry"]["steel"],
            add_cement=config["custom_industry"]["cement"],
            ccs_retrofit=config["custom_industry"]["CCS_retrofit"],
            biogenic_co2=config["custom_industry"]["biogenic_co2"],
            grid_h2=config["custom_industry"]["grid_H2"],
            other_electricity=config["custom_industry"]["other_electricity"],
            data_centers=config["demand_projection"]["data_centers_load"],
            data_center_profiles=CUSTOM_USA_DATA_DIR + "data_center_profiles/",
            dac_inputs=config["custom_industry"]["dac_inputs"],
            geo_crs=config["crs"]["geo_crs"],
            buffer_co2_stored=config["custom_industry"]["buffer_co2_stored"],
            co2_storage_tanks=config["custom_industry"]["co2_storage_tanks"],
        input:
            industrial_energy_demand_per_node=PYPSA_EARTH_DIR
            + "resources/"
            + SECDIR
            + "demand/industrial_energy_demand_per_node_elec_s{simpl}_{clusters}_{planning_horizons}_{demand}_custom_industry.csv",
            energy_totals=PYPSA_EARTH_DIR
            + "resources/"
            + SECDIR
            + "energy_totals_{demand}_{planning_horizons}.csv",
            network=lambda w: f"{PYPSA_EARTH_DIR}results/{SECDIR}prenetworks/elec_s{w.simpl}_{w.clusters}_ec_l{w.ll}_{w.opts}_{w.sopts}_{w.planning_horizons}_{w.discountrate}_{w.demand}{saf_suffix}.nc",
            costs=PYPSA_EARTH_DIR
            + "resources/"
            + RDIR
            + "costs_{planning_horizons}.csv",
            gadm_shape=CUSTOM_USA_DATA_DIR + "demand_data/gadm41_USA_1.json",
        output:
            modified_network=PYPSA_EARTH_DIR
            + "results/"
            + SECDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_custom_industry.nc",
        script:
            "../scripts/custom/add_industry.py"

    use rule add_export from pypsa_earth as add_export_custom with:
        input:
            export_ports="resources/" + SECDIR + "export_ports.csv",
            costs="resources/" + RDIR + "costs_{planning_horizons}_sec.csv",
            ship_profile="resources/" + SECDIR + "ship_profile_{h2export}TWh.csv",
            network=PYPSA_EARTH_DIR
            + "results/"
            + SECDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_custom_industry.nc",
            shapes_path="resources/"
            + RDIR
            + "bus_regions/regions_onshore_elec_s{simpl}_{clusters}.geojson",

    ruleorder: add_export_custom > add_export


if config["foresight"] == "overnight":

    use rule solve_sector_network from pypsa_earth as solve_sector_network_custom with:
        input:
            # network=RESDIR
            # + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}.nc",
            network=RESDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export.nc",
            costs="resources/" + RDIR + "costs_{planning_horizons}_sec.csv",
            configs=PYPSA_EARTH_DIR + SDIR + "configs/config.yaml",  # included to trigger copy_config rule
            overrides=CUSTOM_USA_DATA_DIR + "override_component_attrs",
            agg_p_nom_minmax=config["electricity"]["agg_p_nom_limits"]["file"],  # ensure the CSV with capacity constraints is copied into the shadow directory (needed on Windows, since shadowed scripts can’t access files outside `input`)

    ruleorder: solve_sector_network_custom > solve_sector_network


if config["foresight"] == "myopic":

    use rule solve_network_myopic from pypsa_earth as solve_network_myopic_custom with:
        input:
            network=RESDIR
            + "prenetworks-brownfield/elec_s{simpl}_{clusters}_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export.nc",
            costs="resources/" + RDIR + "costs_{planning_horizons}_sec.csv",
            configs=PYPSA_EARTH_DIR + SDIR + "configs/config.yaml",  # included to trigger copy_config rule
            overrides=CUSTOM_USA_DATA_DIR + "override_component_attrs",
            agg_p_nom_minmax=config["electricity"]["agg_p_nom_limits"]["file"],  # ensure the CSV with capacity constraints is copied into the shadow directory (needed on Windows, since shadowed scripts can’t access files outside `input`)

    ruleorder: solve_network_myopic_custom > solve_network_myopic

    rule solve_custom_network_myopic:
        params:
            solving=config["solving"],
            foresight=config["foresight"],
            planning_horizons=config["scenario"]["planning_horizons"],
            co2_sequestration_potential=config["scenario"].get(
                "co2_sequestration_potential", 200
            ),
            augmented_line_connection=config["augmented_line_connection"],
            temporal_matching_carriers=config["policy_config"]["hydrogen"][
                "temporal_matching_carriers"
            ],
            distance_crs="EPSG:3857",
            grid_region_field="Grid Region",
        input:
            ces_path=CUSTOM_USA_DATA_DIR
            + "current_electricity_state_policies/clean_targets.csv",
            res_path=CUSTOM_USA_DATA_DIR
            + "current_electricity_state_policies/res_targets.csv",
            production_tax_credits=CUSTOM_USA_DATA_DIR
            + "tax_credits/production_tax_credits.csv",
            investment_tax_credits=CUSTOM_USA_DATA_DIR
            + "tax_credits/investment_tax_credits.csv",
            gadm_shape_path=CUSTOM_USA_DATA_DIR + "demand_data/gadm41_USA_1.json",
            grid_regions_shape_path=CUSTOM_USA_DATA_DIR
            + "temporal_matching/needs_grid_regions_aggregated.geojson",
            overrides=CUSTOM_USA_DATA_DIR + "override_component_attrs",
            network=PYPSA_EARTH_DIR
            + RESDIR
            + "prenetworks-brownfield/elec_s{simpl}_{clusters}_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export.nc",
            costs=PYPSA_EARTH_DIR
            + "resources/"
            + RDIR
            + "costs_{planning_horizons}.csv",
            configs=PYPSA_EARTH_DIR + SDIR + "configs/config.yaml",  # included to trigger copy_config rule
            agg_p_nom_minmax=config["electricity"]["agg_p_nom_limits"]["file"],
        output:
            network=PYPSA_EARTH_DIR
            + RESDIR
            + "postnetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export.nc",
            # config=RESDIR
            # + "configs/config.elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export.yaml",
        shadow:
            "shallow"
        log:
            solver=PYPSA_EARTH_DIR
            + RESDIR
            + "logs/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export_solver.log",
            python=PYPSA_EARTH_DIR
            + RESDIR
            + "logs/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export_python.log",
            memory=PYPSA_EARTH_DIR
            + RESDIR
            + "logs/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export_memory.log",
        threads: 25
        resources:
            mem_mb=config["solving"]["mem"],
        benchmark:
            (
                PYPSA_EARTH_DIR
                + RESDIR
                + "benchmarks/solve_network/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export"
            )
        script:
            "../scripts/custom/solve_custom_sector_network.py"

    ruleorder: solve_custom_network_myopic > solve_network_myopic_custom > solve_network_myopic


if config["demand_distribution"]["set_distribution_fees"]:

    use rule prepare_sector_network from pypsa_earth as prepare_sector_network_custom with:
        output:
            PYPSA_EARTH_DIR
            + RESDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_distribution_fees.nc",

    ruleorder: prepare_sector_network_custom > prepare_sector_network

    rule set_distribution_fees:
        params:
            distance_crs=config["crs"]["distance_crs"],
        input:
            shape_path=CUSTOM_USA_DATA_DIR
            + "EIA_market_module_regions/EMM_regions.geojson",
            regional_fees_path=CUSTOM_USA_DATA_DIR
            + "EIA_market_module_regions/regional_fees.csv",
            network=PYPSA_EARTH_DIR
            + RESDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_distribution_fees.nc",
        output:
            PYPSA_EARTH_DIR
            + RESDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}.nc",
        script:
            "../scripts/custom/set_distribution_fees.py"

    ruleorder: set_distribution_fees > prepare_sector_network
    ruleorder: prepare_sector_network_custom > prepare_sector_network


if config["foresight"] == "overnight" and config["state_policy"] != "off":

    rule solve_custom_sector_network:
        params:
            solving=config["solving"],
            augmented_line_connection=config["augmented_line_connection"],
            temporal_matching_carriers=config["policy_config"]["hydrogen"][
                "temporal_matching_carriers"
            ],
            distance_crs="EPSG:3857",
            grid_region_field="Grid Region",
        input:
            ces_path=CUSTOM_USA_DATA_DIR
            + "current_electricity_state_policies/clean_targets.csv",
            res_path=CUSTOM_USA_DATA_DIR
            + "current_electricity_state_policies/res_targets.csv",
            production_tax_credits=CUSTOM_USA_DATA_DIR
            + "tax_credits/production_tax_credits.csv",
            investment_tax_credits=CUSTOM_USA_DATA_DIR
            + "tax_credits/investment_tax_credits.csv",
            gadm_shape_path=CUSTOM_USA_DATA_DIR + "demand_data/gadm41_USA_1.json",
            grid_regions_shape_path=CUSTOM_USA_DATA_DIR
            + "temporal_matching/needs_grid_regions_aggregated.geojson",
            overrides=CUSTOM_USA_DATA_DIR + "override_component_attrs",
            network=PYPSA_EARTH_DIR
            + RESDIR
            + "prenetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export.nc",
            costs=PYPSA_EARTH_DIR
            + "resources/"
            + RDIR
            + "costs_{planning_horizons}.csv",
            configs=PYPSA_EARTH_DIR + SDIR + "configs/config.yaml",  # included to trigger copy_config rule
        output:
            PYPSA_EARTH_DIR
            + RESDIR
            + "postnetworks/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export.nc",
        shadow:
            "shallow"
        log:
            solver=PYPSA_EARTH_DIR
            + RESDIR
            + "logs/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export_solver.log",
            python=PYPSA_EARTH_DIR
            + RESDIR
            + "logs/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export_python.log",
            memory=PYPSA_EARTH_DIR
            + RESDIR
            + "logs/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export_memory.log",
        threads: 25
        resources:
            mem_mb=config["solving"]["mem"],
        benchmark:
            (
                PYPSA_EARTH_DIR
                + RESDIR
                + "benchmarks/solve_network/elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_{sopts}_{planning_horizons}_{discountrate}_{demand}_{h2export}export"
            )
        script:
            "../scripts/custom/solve_custom_sector_network.py"

    ruleorder: solve_custom_sector_network > solve_sector_network


rule test_modify_prenetwork:
    input:
        prenetwork=PYPSA_EARTH_DIR
        + "networks/"
        + RDIR
        + "elec_s{simpl}_{clusters}_ec_l{ll}_{opts}.nc",
    output:
        network=PYPSA_EARTH_DIR
        + "networks/"
        + RDIR
        + "elec_s{simpl}_{clusters}_ec_l{ll}_{opts}_mod.nc",
    resources:
        mem_mb=16000,
    script:
        "../scripts/custom/test_modify_network.py"


# use rule prepare_network with:
#    input:
#        **{k: v for k, v in rules.prepare_network.input.items() if k != "tech_costs"},
# use rule add_extra_components with:
#    input:
#        **{k: v for k, v in rules.add_extra_components.input.items()},
