# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Creates onshore and offshore bus regions.

Onshore regions can either be generated as Voronoi polygons around buses or
assigned from predefined region shapes (e.g. GADM, Balancing Authorities,
EIA Market Module Regions, or NEEDS Grid Regions).

Relevant Settings
-----------------

.. code:: yaml

    countries:

.. seealso::
    Documentation of the configuration file ``config.yaml`` at
    :ref:`toplevel_cf`

Inputs
------

- ``resources/country_shapes.geojson``: confer :ref:`shapes`
- ``resources/offshore_shapes.geojson``: confer :ref:`shapes`
- ``networks/base.nc``: confer :ref:`base`

Outputs
-------

- ``resources/regions_onshore.geojson``:

    .. image:: /img/regions_onshore.png
        :width: 33 %

- ``resources/regions_offshore.geojson``:

    .. image:: /img/regions_offshore.png
        :width: 33 %

Description
-----------

Creates the geographical regions associated with each network bus. Depending on
the selected clustering mode, onshore regions are either computed using Voronoi
tessellation or assigned from predefined region polygons.
"""
import sys
from pathlib import Path

if "snakemake" in globals():
    REPO_ROOT = Path(snakemake.scriptdir).resolve().parents[1]
else:
    REPO_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO_ROOT / "scripts" / "custom"))
sys.path.insert(1, str(REPO_ROOT / "scripts"))

import os
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa
from _helpers import REGION_COLS, configure_logging, create_logger, nearest_shape
from shapely.geometry import Polygon

logger = create_logger(__name__)


ALTERNATIVE_CLUSTERING_SHAPES = {
    "balancing_areas": "data/custom/usa/demand_data/Balancing_Authorities.geojson",
    "eia_market_module": "data/custom/usa/EIA_market_module_regions/EMM_regions.geojson",
    "needs_grid_regions": "data/custom/usa/temporal_matching/needs_grid_regions_aggregated.geojson",
}


def voronoi(
    points: pd.DataFrame,
    outline: Polygon,
    geo_crs: str = "EPSG:4326",
) -> gpd.GeoSeries:
    """
    Create Voronoi polygons from a set of points within an outline.

    Parameters
    ----------
    points : pd.DataFrame
         DataFrame containing the coordinates of the points with columns ["x", "y"] and index
    outline : Polygon
        Shapely Polygon defining the outline within which to compute the Voronoi partition.
    geo_crs : str
        CRS used for geographic projection, passed to GeoPandas (e.g. "EPSG:4326")

    Returns
    -------
    gpd.GeoSeries
        GeoSeries of Voronoi polygons corresponding to each point in `points`, clipped to the `outline` polygon.
    """

    pts = gpd.GeoSeries(
        gpd.points_from_xy(points.x, points.y),
        index=points.index,
        crs=geo_crs,
    )
    voronoi = pts.voronoi_polygons(extend_to=outline).clip(outline)

    # can be removed with shapely 2.1 where order is preserved
    # https://github.com/shapely/shapely/issues/2020
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        pts = gpd.GeoDataFrame(geometry=pts)
        voronoi = gpd.GeoDataFrame(geometry=voronoi)
        joined = gpd.sjoin_nearest(pts, voronoi, how="right")

    gdf = joined.dissolve(by=points.index.name).reindex(points.index).squeeze()

    return gdf


def get_shape_assignment(
    onshore_buses: pd.DataFrame,
    shapes: gpd.GeoDataFrame,
    geo_crs: str = "EPSG:4326",
    metric_crs: str = "EPSG:3857",
) -> tuple[np.ndarray, np.ndarray]:
    """
    Get the shape assigned to each bus by finding the nearest polygon.

    Parameters
    ----------
    onshore_buses : pd.DataFrame
        Onshore buses with columns ["x", "y"].
    shapes : gpd.GeoDataFrame
        GeoDataFrame containing the candidate region polygons. Its index is used
        as the shape identifier.
    geo_crs : str, optional
        Geographic CRS used for bus coordinates, by default "EPSG:4326".
    metric_crs : str, optional
        Metric CRS used for nearest-neighbour distance calculation, by default "EPSG:3857".

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        A tuple containing:
        - geometries assigned to each bus;
        - shape IDs assigned to each bus.
    """
    geo_regions = gpd.GeoDataFrame(
        onshore_buses[["x", "y"]],
        geometry=gpd.points_from_xy(onshore_buses["x"], onshore_buses["y"]),
        crs=geo_crs,
    ).to_crs(metric_crs)

    join_geos = gpd.sjoin_nearest(
        geo_regions,
        shapes.to_crs(metric_crs),
        how="left",
    )

    join_geos = join_geos[~join_geos.index.duplicated()]
    shape_ids = join_geos["index_right"].values
    selected = shapes.loc[shape_ids]

    return selected.geometry.values, selected.index.values


if __name__ == "__main__":
    if "snakemake" not in globals():
        from _helpers import mock_snakemake

        snakemake = mock_snakemake("build_bus_regions")

    configure_logging(snakemake)

    inputs = snakemake.input
    country_shapes_fn = inputs.get("subregion_shapes") or inputs.country_shapes
    offshore_shapes_fn = inputs.get("subregion_offshore") or inputs.offshore_shapes
    countries = snakemake.params.countries
    geo_crs = snakemake.params.crs["geo_crs"]
    area_crs = snakemake.params.crs["area_crs"]
    metric_crs = snakemake.params.crs["distance_crs"]

    n = pypsa.Network(inputs.base_network)

    country_shapes = gpd.read_file(country_shapes_fn).set_index("name")["geometry"]

    offshore_shapes = gpd.read_file(offshore_shapes_fn)

    offshore_shapes = offshore_shapes.reindex(columns=REGION_COLS).set_index("name")[
        "geometry"
    ]

    # Option for subregion
    subregion_shapes = snakemake.input.get("subregion_shapes")
    if subregion_shapes:
        crs = {"geo_crs": geo_crs, "distance_crs": metric_crs}
        tolerance = snakemake.config.get("subregion", {}).get("tolerance", 100)
        n = nearest_shape(n, country_shapes_fn, crs, tolerance=tolerance)

        countries = list(country_shapes.index)

    gadm_shapes = gpd.read_file(inputs.gadm_shapes).set_index("GADM_ID")

    alternative_shape = snakemake.params.cluster_options.get(
        "alternative_clustering_shape",
        "gadm",
    )

    if alternative_shape == "gadm":
        alternative_shapes = gadm_shapes
    else:
        alternative_shapes = gpd.read_file(
            ALTERNATIVE_CLUSTERING_SHAPES[alternative_shape]
        ).to_crs(geo_crs)
        alternative_shapes = alternative_shapes.reset_index(drop=True)
        alternative_shapes.index = alternative_shapes.index.astype(str)
        alternative_shapes.index.name = "shape_id"

    onshore_regions = []
    offshore_regions = []

    n_alternative_shapes = 0

    for country in countries:
        c_b = n.buses.country == country
        if n.buses.loc[c_b & n.buses.substation_lv, ["x", "y"]].empty:
            logger.warning(f"No low voltage buses found for {country}!")
            continue

        onshore_shape = country_shapes[country]
        onshore_locs = n.buses.loc[c_b & n.buses.substation_lv, ["x", "y"]]
        if snakemake.params.alternative_clustering:
            if alternative_shape == "gadm":
                alternative_shapes_country = alternative_shapes[
                    alternative_shapes.country == country
                ]
            else:
                alternative_shapes_country = alternative_shapes

            n_alternative_shapes += len(alternative_shapes_country)

            onshore_geometry, shape_id = get_shape_assignment(
                onshore_locs,
                alternative_shapes_country,
                geo_crs,
                metric_crs,
            )
        else:
            onshore_geometry = voronoi(onshore_locs, onshore_shape)
            shape_id = 0  # Not used

        temp_region = gpd.GeoDataFrame(
            {
                "name": onshore_locs.index,
                "x": onshore_locs["x"],
                "y": onshore_locs["y"],
                "geometry": onshore_geometry,
                "country": country,
                "shape_id": shape_id,
            },
            crs=geo_crs,
        )
        temp_region = temp_region[
            temp_region.geometry.is_valid & ~temp_region.geometry.is_empty
        ]
        onshore_regions.append(temp_region)

        # These two logging could be commented out
        if country not in offshore_shapes.index:
            logger.warning(f"No off-shore shapes for {country}")
            continue

        offshore_shape = offshore_shapes[country]

        if n.buses.loc[c_b & n.buses.substation_off, ["x", "y"]].empty:
            logger.warning(f"No off-shore substations found for {country}")
            continue
        else:
            offshore_locs = n.buses.loc[c_b & n.buses.substation_off, ["x", "y"]]
            shape_id = 0  # Not used
            offshore_geometry = voronoi(offshore_locs, offshore_shape)
            offshore_regions_c = gpd.GeoDataFrame(
                {
                    "name": offshore_locs.index,
                    "x": offshore_locs["x"],
                    "y": offshore_locs["y"],
                    "geometry": offshore_geometry,
                    "country": country,
                    "shape_id": shape_id,
                },
                crs=country_shapes.crs,
            )
            offshore_regions_c = offshore_regions_c.loc[
                offshore_regions_c.to_crs(area_crs).area > 1e-2
            ]
            offshore_regions_c = offshore_regions_c[
                offshore_regions_c.geometry.is_valid
                & ~offshore_regions_c.geometry.is_empty
            ]
            offshore_regions.append(offshore_regions_c)

    # create geodataframe and remove nan shapes
    onshore_regions = gpd.GeoDataFrame(
        pd.concat(onshore_regions, ignore_index=True),
        crs=country_shapes.crs,
    ).dropna(axis="index", subset=["geometry"])

    if snakemake.params.alternative_clustering:
        # Determine isolated buses
        n.determine_network_topology()
        non_isolated_buses = n.buses.duplicated(subset=["sub_network"], keep=False)
        isolated_buses = n.buses[~non_isolated_buses].index

        non_isolated_regions = onshore_regions[
            ~onshore_regions.name.isin(isolated_buses)
        ]
        isolated_regions = onshore_regions[onshore_regions.name.isin(isolated_buses)]

        # Combine regions while prioritizing non-isolated buses
        onshore_regions = pd.concat(
            [non_isolated_regions, isolated_regions]
        ).drop_duplicates("shape_id", keep="first")

        if n_alternative_shapes and len(onshore_regions) < n_alternative_shapes:
            logger.warning(
                "The number of remaining buses is lower than the number of "
                "alternative clustering shapes."
            )

    if subregion_shapes:
        logger.info("Deactivate subregion classificaition")
        original_shapes = snakemake.input.original_shapes
        n = nearest_shape(n, original_shapes, crs, tolerance=tolerance)

        onshore_regions["country"] = onshore_regions.name.map(n.buses.country)
        if offshore_regions:
            for offshore_region in offshore_regions:
                offshore_region["country"] = offshore_region.name.map(n.buses.country)

    onshore_regions = pd.concat([onshore_regions], ignore_index=True).to_file(
        snakemake.output.regions_onshore
    )

    if offshore_regions:
        # if a offshore_regions exists execute below
        pd.concat(offshore_regions, ignore_index=True).to_file(
            snakemake.output.regions_offshore
        )
    else:
        # if no offshore_regions exist save an empty offshore_shape
        offshore_shapes.to_frame().to_file(snakemake.output.regions_offshore)
