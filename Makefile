# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

.PHONY: test setup clean

test:
	set -e
	snakemake -c1 solve_sector_networks_myopic \
		--configfile configs/custom/scenarios/test/config.test.na.yaml
	echo "NorthAmerica workflow test completed successfully."

setup:
	echo "Setup complete."

clean:
	snakemake -j1 solve_sector_networks_myopic \
		--delete-all-output \
		--configfile configs/custom/scenarios/test/config.test.na.yaml
	echo "Clean-up complete."
