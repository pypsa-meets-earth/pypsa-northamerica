# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "scripts"))

from _helpers import progress_retrieve

from scripts.custom._helper import configure_logging

configure_logging(snakemake)

bundle = snakemake.config["custom_databundles"]["bundle_demand_profiles_test"]
url = bundle["urls"]["zenodo"]

output = Path(snakemake.output.demand_profile_path)
output.parent.mkdir(parents=True, exist_ok=True)

archive = output.parent / "demand_profiles_test.csv.zip"

progress_retrieve(url, str(archive))

with zipfile.ZipFile(archive, "r") as zf:
    zf.extract("demand_profiles.csv", path=output.parent)

extracted = output.parent / "demand_profiles.csv"
if not extracted.exists():
    raise FileNotFoundError(f"Expected {extracted} after extracting {archive}")

extracted.rename(output)

archive.unlink()
