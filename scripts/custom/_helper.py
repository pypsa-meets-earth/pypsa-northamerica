# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os
import random
import re
import sys
import warnings
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import googledrivedownloader as gdd
import pandas as pd
import pypsa
import snakemake as sm
import yaml
from pypsa.components import component_attrs, components
from pypsa.descriptors import Dict
from snakemake.script import Snakemake

warnings.filterwarnings("ignore")


# get the base working directory
BASE_PATH = os.path.abspath(os.path.join(__file__, "../.."))
PLOTS_DIR = BASE_PATH + "/plots/results/"
DATA_DIR = BASE_PATH + "/data/"
# get pypsa-earth submodule directory path
PYPSA_EARTH_DIR = BASE_PATH + "/submodules/pypsa-earth"

LINE_OPTS = {"2021": "copt"}


def load_network(filepath):
    """Input:
        filepath - full path to the network
    Output:
        n - PyPSA network
    """
    try:
        n = pypsa.Network(filepath)
        logging.info(f"Loading {filepath}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return None
    return n


def mock_snakemake(rule_name, configfile=None, **wildcards):
    """
    This function is expected to be executed from the "scripts"-directory of "
    the snakemake project. It returns a snakemake.script.Snakemake object,
    based on the Snakefile.

    If a rule has wildcards, you have to specify them in **wildcards**.

    Parameters
    ----------
    rule_name: str
        name of the rule for which the snakemake object should be generated
    wildcards:
        keyword arguments fixing the wildcards. Only necessary if wildcards are
        needed.
    """

    script_dir = Path(__file__).parent.resolve()
    os.chdir(script_dir.parent)
    for p in sm.SNAKEFILE_CHOICES:
        if Path(p).exists():
            snakefile = p
            break
    if isinstance(configfile, str):
        with open(configfile, "r") as file:
            configfile = yaml.safe_load(file)

    workflow = sm.Workflow(
        snakefile,
        overwrite_configfiles=[],
        rerun_triggers=[],
        overwrite_config=configfile,
    )  # overwrite_config=config
    workflow.include(snakefile)
    workflow.global_resources = {}
    try:
        rule = workflow.get_rule(rule_name)
    except Exception as exception:
        print(
            exception,
            f"The {rule_name} might be a conditional rule in the Snakefile.\n"
            f"Did you enable {rule_name} in the config?",
        )
        raise
    dag = sm.dag.DAG(workflow, rules=[rule])
    wc = Dict(wildcards)
    job = sm.jobs.Job(rule, dag, wc)

    def make_accessable(*ios):
        for io in ios:
            for i in range(len(io)):
                io[i] = Path(io[i]).absolute()

    make_accessable(job.input, job.output, job.log)
    snakemake = Snakemake(
        job.input,
        job.output,
        job.params,
        job.wildcards,
        job.threads,
        job.resources,
        job.log,
        job.dag.workflow.config,
        job.rule.name,
        None,
    )
    snakemake.benchmark = job.benchmark

    # create log and output dir if not existent
    for path in list(snakemake.log) + list(snakemake.output):
        build_directory(path)

    os.chdir(script_dir)
    return snakemake


def update_config_from_wildcards(config, w):
    if w.get("planning_horizon"):
        planning_horizon = w.planning_horizon
        config["validation"]["planning_horizon"] = planning_horizon
    if w.get("clusters"):
        clusters = w.clusters
        config["scenario"]["clusters"] = clusters
    if w.get("countries"):
        countries = w.countries
        config["scenario"]["countries"] = countries
    if w.get("simpl"):
        simpl = w.simpl
        config["scenario"]["simpl"] = simpl
    if w.get("opts"):
        opts = w.opts
        config["scenario"]["opts"] = opts
    if w.get("ll"):
        ll = w.ll
        config["scenario"]["ll"] = ll
    return config


def build_directory(path, just_parent_directory=True):
    """
    It creates recursively the directory and its leaf directories.

    Parameters:
        path (str): The path to the file
        just_parent_directory (Boolean): given a path dir/subdir
            True: it creates just the parent directory dir
            False: it creates the full directory tree dir/subdir
    """

    # Check if the provided path points to a directory
    if just_parent_directory:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    else:
        Path(path).mkdir(parents=True, exist_ok=True)


def get_solved_network_path(scenario_folder):
    """
    Get the full path to the PyPSA network file from the specified scenario folder.
    Assumes that only one network file exists in the folder.

    Args:
        scenario_folder (str): Folder containing the scenario data.

    Returns:
        str: Full path to the network file.
    """
    results_dir = os.path.join(
        BASE_PATH, f"submodules/pypsa-earth/results/{scenario_folder}/networks"
    )
    filenames = os.listdir(results_dir)

    # Ensure only one network file exists
    if len(filenames) != 1:
        logging.warning(f"Only 1 network per scenario is allowed currently!")
    filepath = os.path.join(results_dir, filenames[0])

    return filepath


def load_pypsa_network(scenario_folder):
    """
    Load a PyPSA network from a specific scenario folder.

    Args:
        scenario_folder (str): Folder containing the scenario data.

    Returns:
        pypsa.Network: The loaded PyPSA network object.
    """
    network_path = get_solved_network_path(scenario_folder)
    network = pypsa.Network(network_path)
    return network


def load_network(path):
    """
    Loads a PyPSA network from a path
    """
    network = pypsa.Network(path)
    return network


def create_logger(logger_name, level=logging.INFO):
    """
    Create a logger for a module and adds a handler needed to capture in logs
    traceback from exceptions emerging during the workflow.
    """
    logger_instance = logging.getLogger(logger_name)
    logger_instance.setLevel(level)
    handler = logging.StreamHandler(stream=sys.stdout)
    logger_instance.addHandler(handler)
    return logger_instance


def configure_logging(snakemake, skip_handlers=False):
    import logging

    kwargs = snakemake.config.get("logging", dict()).copy()
    kwargs.setdefault("level", "INFO")

    if skip_handlers is False:
        logs_dir = Path(__file__).parent.joinpath("..", "logs")
        logs_dir.mkdir(parents=True, exist_ok=True)  # Ensure logs directory

        fallback_path = logs_dir.joinpath(f"{snakemake.rule}.log")
        logfile = snakemake.log.get(
            "python", snakemake.log[0] if snakemake.log else fallback_path
        )
        formatter = logging.Formatter("%(levelname)s - %(message)s")

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(logfile)
        file_handler.setFormatter(formatter)

        kwargs.update(
            {
                "handlers": [
                    # Prefer the "python" log, otherwise take the first log for each
                    # Snakemake rule
                    file_handler,
                    stream_handler,
                ]
            }
        )
    logging.basicConfig(**kwargs, force=True)


def download_and_unzip_gdrive(
    config, destination, logger, disable_progress=False, url=None
):
    """
    Downloads and unzips data from custom bundle config
    """
    resource = config["category"]
    file_path = os.path.join(PYPSA_EARTH_DIR, f"tempfile_{resource}.zip")
    if url is None:
        url = config["urls"]["gdrive"]

    # retrieve file_id from path
    try:
        # cut the part before the ending \view
        partition_view = re.split(r"/view|\\view", str(url), 1)
        if len(partition_view) < 2:
            logger.error(
                f'Resource {resource} cannot be downloaded: "\\view" not found in url {url}'
            )
            return False

        # split url to get the file_id
        code_split = re.split(r"\\|/", partition_view[0])

        if len(code_split) < 2:
            logger.error(
                f'Resource {resource} cannot be downloaded: character "\\" not found in {partition_view[0]}'
            )
            return False

        # get file id
        file_id = code_split[-1]

        # remove tempfile.zip if exists
        Path(file_path).unlink(missing_ok=True)

        # download file from google drive
        gdd.download_file_from_google_drive(
            file_id=file_id,
            dest_path=file_path,
            showsize=not disable_progress,
            unzip=False,
        )
        with ZipFile(file_path, "r") as zipObj:
            bad_file = zipObj.testzip()
            if bad_file:
                logger.info(f"Corrupted file found: {bad_file}")
            else:
                logger.info("No errors found in the zip file.")
            # Extract all the contents of zip file in current directory
            zipObj.extractall(path=destination)
        # remove tempfile.zip
        Path(file_path).unlink(missing_ok=True)

        logger.info(f"Download resource '{resource}' from cloud '{url}'.")

        return True

    except Exception as e:
        logger.error(f"Failed to download or extract the file: {str(e)}")
        return False


def osm_raw_outputs():
    outputs = [
        "osm/raw/all_raw_cables.geojson",
        "osm/raw/all_raw_generators.geojson",
        "osm/raw/all_raw_generators.csv",
        "osm/raw/all_raw_lines.geojson",
        "osm/raw/all_raw_substations.geojson",
    ]
    return outputs


def osm_clean_outputs():
    outputs = [
        "osm/clean/all_clean_generators.geojson",
        "osm/clean/all_clean_generators.csv",
        "osm/clean/all_clean_lines.geojson",
        "osm/clean/all_clean_substations.geojson",
    ]
    return outputs


def shapes_outputs():
    outputs = [
        "shapes/country_shapes.geojson",
        "shapes/offshore_shapes.geojson",
        "shapes/africa_shape.geojson",
        "shapes/gadm_shapes.geojson",
    ]
    return outputs


def osm_network_outputs():
    outputs = [
        "base_network/all_lines_build_network.csv",
        "base_network/all_converters_build_network.csv",
        "base_network/all_transformers_build_network.csv",
        "base_network/all_buses_build_network.csv",
    ]
    return outputs


def renewable_profiles_outputs():
    carriers = ["csp", "hydro", "offwind-ac", "offwind-dc", "onwind", "solar"]
    outputs = ["renewable_profiles/profile_" + x + ".nc" for x in carriers]
    return outputs


def get_colors(n):
    return ["#%06x" % random.randint(0, 0xFFFFFF) for _ in range(n)]


def attach_grid_region_to_buses(
    network, path_shapes, grid_region_field="Grid Region", distance_crs="EPSG:3857"
):
    """
    Attach each bus in the network to a grid region defined in a shapefile.
    """
    shapes = gpd.read_file(path_shapes)
    if "GRID_REGIO" in shapes.columns and grid_region_field not in shapes.columns:
        shapes = shapes.rename(columns={"GRID_REGIO": grid_region_field})
    if grid_region_field not in shapes.columns:
        raise ValueError(f"Field '{grid_region_field}' not found in {path_shapes}")

    if not {"x", "y"}.issubset(network.buses.columns):
        ac_dc = ["AC", "DC"]
        locmap = network.buses.query("carrier in @ac_dc")[["x", "y"]]
        network.buses["x"] = network.buses["location"].map(locmap["x"]).fillna(0)
        network.buses["y"] = network.buses["location"].map(locmap["y"]).fillna(0)

    buses_gdf = gpd.GeoDataFrame(
        network.buses.copy(),
        geometry=gpd.points_from_xy(network.buses.x, network.buses.y),
        crs="EPSG:4326",
    )

    if shapes.crs is None:
        shapes = shapes.set_crs("EPSG:4326")
    if buses_gdf.crs != shapes.crs:
        buses_gdf = buses_gdf.to_crs(shapes.crs)

    joined = gpd.sjoin(
        buses_gdf,
        shapes[[grid_region_field, "geometry"]],
        how="left",
        predicate="within",
    )[[grid_region_field]]
    miss = joined[grid_region_field].isna()
    if miss.any():
        buses_m = buses_gdf.loc[miss].to_crs(distance_crs)
        shapes_m = shapes.to_crs(distance_crs)
        near = gpd.sjoin_nearest(
            buses_m,
            shapes_m[[grid_region_field, "geometry"]],
            how="left",
            distance_col="dist_m",
        )[[grid_region_field]]
        joined.loc[miss, grid_region_field] = near[grid_region_field].values

    if "region" in network.buses.columns and "emm_region" not in network.buses.columns:
        network.buses.rename(columns={"region": "emm_region"}, inplace=True)

    network.buses["grid_region"] = joined[grid_region_field].values
    return network
