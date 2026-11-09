# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

.PHONY: test setup clean test-upstream

test:
	set -e
	PYTHONPATH=$(PWD) snakemake -c1 solve_sector_networks_myopic \
		--configfile configs/custom/scenarios/test/config.test.na.yaml
	echo "NorthAmerica workflow test completed successfully."

setup:
	echo "Setup complete."

clean:
	PYTHONPATH=$(PWD) snakemake -j1 solve_sector_networks_myopic \
		--delete-all-output \
		--configfile configs/custom/scenarios/test/config.test.na.yaml
	echo "Clean-up complete."

# Run upstream's general test scenarios explicitly when needed.
test-upstream:
	set -e
	snakemake -c4 solve_all_networks --configfile config.tutorial.yaml test/config.test.yaml
	snakemake -c4 solve_all_networks_monte --configfile config.tutorial.yaml test/config.monte_carlo.yaml
	snakemake -c4 solve_sector_networks --configfile config.tutorial.yaml test/config.sector.yaml
	snakemake -c4 solve_sector_networks_myopic --configfile config.tutorial.yaml test/config.myopic.yaml
	snakemake -c4 solve_all_networks --configfile config.tutorial.yaml test/config.custom.yaml
	snakemake -c4 solve_all_networks --configfile config.tutorial.yaml test/config.landlock.yaml
