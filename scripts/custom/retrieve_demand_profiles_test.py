# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import zipfile
from pathlib import Path

from scripts.custom._helper import configure_logging, progress_retrieve

configure_logging(snakemake)

bundle = snakemake.config["custom_databundles"]["bundle_demand_profiles_test"]
url = bundle["urls"]["zenodo"]

output = Path(snakemake.output.demand_profile_path)
output.parent.mkdir(parents=True, exist_ok=True)

archive = output.parent / "demand_profiles_test.csv.zip"

progress_retrieve(url, str(archive))

with zipfile.ZipFile(archive, "r") as zf:
    zf.extractall(output.parent)

(output.parent / "demand_profiles_test.csv").rename(output)

archive.unlink()
