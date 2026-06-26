# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys
import warnings
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path.cwd()))
sys.path.append(os.path.abspath(os.path.join(__file__, "../../")))

warnings.filterwarnings("ignore")

from scripts.custom._helper import configure_logging, mock_snakemake

if __name__ == "__main__":
    if "snakemake" not in globals():
        snakemake = mock_snakemake(
            "build_test_shapes",
            configfile="configs/custom/scenarios/test/config.test.na.yaml",
        )

    configure_logging(snakemake)

    region = snakemake.params.region
    region_column = snakemake.params.region_column

    emm = gpd.read_file(snakemake.input.emm_regions).to_crs("EPSG:4326")
    test_region = emm[emm[region_column] == region].copy()

    if test_region.empty:
        raise ValueError(f"No EMM region found with {region_column} == {region!r}.")

    test_region["name"] = "US"
    test_region["country"] = "US"
    test_region["GID_0"] = "US"
    test_region["GID_1"] = f"US.{region}"
    test_region["NAME_0"] = "United States"
    test_region["NAME_1"] = test_region["subregion"].iloc[0]

    output_dir = Path(snakemake.output.country_shapes).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    empty = test_region.iloc[0:0].copy()

    test_region.to_file(snakemake.output.country_shapes, driver="GeoJSON")
    test_region.to_file(snakemake.output.gadm_shapes, driver="GeoJSON")
    test_region.to_file(snakemake.output.extended_country_shape, driver="GeoJSON")
    test_region.to_file(snakemake.output.subregion_shapes, driver="GeoJSON")
    test_region.to_file(snakemake.output.africa_shape, driver="GeoJSON")

    empty.to_file(snakemake.output.offshore_shapes, driver="GeoJSON")
    empty.to_file(snakemake.output.subregion_offshore, driver="GeoJSON")
