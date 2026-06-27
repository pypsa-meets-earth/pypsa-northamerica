# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path

import geopandas as gpd


def write_empty_like(gdf, path):
    empty = gdf.iloc[0:0].copy()
    empty.to_file(path, driver="GeoJSON")


boundary = gpd.read_file(snakemake.input.boundary).to_crs("EPSG:4326")
boundary = boundary.dissolve().reset_index(drop=True)

boundary["subregion"] = "US small test region"
boundary["geoname"] = "US small test region"
boundary["cat"] = 0
boundary["egrid_reg"] = "US_SMALL"
boundary["regid"] = 0
boundary["SHAPE__Length"] = boundary.to_crs("EPSG:3857").length
boundary["SHAPE__Area"] = boundary.to_crs("EPSG:3857").area
boundary["name"] = "US"
boundary["country"] = "US"
boundary["GID_0"] = "US"
boundary["GID_1"] = "US.US_SMALL"
boundary["GADM_ID"] = "US.US_SMALL"
boundary["NAME_0"] = "United States"
boundary["NAME_1"] = "US small test region"
boundary["pop"] = 1_000_000.0
boundary["gdp"] = 1_000_000_000.0

for output_file in snakemake.output:
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

boundary.to_file(snakemake.output.country_shapes, driver="GeoJSON")
boundary.to_file(snakemake.output.gadm_shapes, driver="GeoJSON")
boundary.to_file(snakemake.output.extended_country_shape, driver="GeoJSON")
boundary.to_file(snakemake.output.subregion_shapes, driver="GeoJSON")

write_empty_like(boundary, snakemake.output.offshore_shapes)
write_empty_like(boundary, snakemake.output.subregion_offshore)
write_empty_like(boundary, snakemake.output.africa_shape)
