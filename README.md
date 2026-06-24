<!--
SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# PyPSA-Northamerica

## Development Status: **Under development and Active**

[![Test workflows](https://github.com/pypsa-meets-earth/pypsa-northamerica/actions/workflows/test.yml/badge.svg)](https://github.com/pypsa-meets-earth/pypsa-northamerica/actions/workflows/test.yml)
![Size](https://img.shields.io/github/repo-size/pypsa-meets-earth/pypsa-northamerica)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![REUSE status](https://api.reuse.software/badge/github.com/pypsa-meets-earth/pypsa-northamerica)](https://api.reuse.software/info/github.com/pypsa-meets-earth/pypsa-northamerica)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/pypsa-meets-earth/pypsa-northamerica/main.svg)](https://results.pre-commit.ci/latest/github/pypsa-meets-earth/pypsa-northamerica/main)
[![Discord](https://img.shields.io/discord/911692131440148490?logo=discord)](https://discord.gg/AnuJBk23FU)
[![Input data](https://img.shields.io/badge/Input%20data-Zenodo-1682D4?logo=zenodo&logoColor=white)](https://zenodo.org/records/20762977)

PyPSA-Northamerica is a North America-focused soft fork of PyPSA-Earth initially developed by Open Energy Transition in the framework of the [Grid modelling to assess electrofuels supply potential](https://www.openenergytransition.org/projects/grid-modelling-to-assess-electrofuels).

PyPSA-Northamerica extends the standard [PyPSA-Earth workflow](https://github.com/pypsa-meets-earth/pypsa-earth) with custom rules and input data for North American energy system modelling, with a current focus on the United States. It is intended as a sector-coupled model with a high spatial (100 nodes) and temporal (3 hours / 1 hour) resolution.

![PyPSA-Northamerica_Installed_capacity_2023](doc/images/usa_installed_capacity_2023.png)

The following countries are currently supported:

🇺🇸 United States

Canada and Mexico may be added in future releases.

## Running the workflow

The custom workflow is activated through:

```yaml
custom_rules: ["workflow/custom.smk"]
```

Scenario configuration files are stored in `configs/custom`. The main configuration file is `configs/custom/config.main.yaml`, while scenario-specific files are available in subfolders such as `configs/calibration/` and `configs/scenarios/`.

### Running US scenarios

All Snakemake commands should be executed from the repository root.

To run the U.S. sector-coupled model for the selected, calibrated base year (2023):

```bash
snakemake -c 1 solve_sector_networks --configfile configs/custom/calibration/config.base.yaml
```

To run a future-year Reference scenario, replace `20**` with the target year:

```bash
snakemake -c 1 solve_all_networks --configfile configs/custom/scenarios/config.20**.yaml
```

For the corresponding sector-coupled model:

```bash
snakemake -c 1 solve_sector_networks --configfile configs/custom/scenarios/config.20**.yaml
```

Future-year configuration files are currently available for 2030, 2035, and 2040.

To run the sector-coupled model across multiple horizons (myopic optimization):

```bash
snakemake -call solve_sector_networks_myopic --configfile configs/custom/scenarios/config.scenario.**.yaml
```

where ** can be replaced with any value from `01` to `10` (scenario descriptions are available in the provided config files).

### Custom workflow rules

| Rule name                        | Description                                                                                                |
|----------------------------------| ---------------------------------------------------------------------------------------------------------- |
| `validate_all`                   | Performs country-level validation against EIA and Ember data.                                              |
| `statewise_validate_all`         | Performs state-level validation against EIA data.                                                          |
| `get_capacity_factors`           | Estimates renewable capacity factors.                                                                      |
| `process_airport_data`           | Processes airport passenger and jet-fuel data and generates state-level aviation demand inputs.            |
| `generate_aviation_scenario`     | Generates aviation demand files for future scenarios.                                                      |
| `modify_aviation_demand`         | Replaces default aviation demand in `energy_totals` with custom aviation demand.                           |
| `preprocess_demand_data`         | Preprocesses utility demand data into geospatial format.                                                   |
| `build_demand_profiles_from_eia` | Builds custom demand profiles from EIA data and bypasses the default demand-profile rule.                  |
| `set_saf_mandate`                | Adds e-kerosene buses and applies SAF mandate constraints when enabled.                                    |
| `build_custom_industry_demand`   | Estimates node-level demand for selected industries such as ammonia, ethanol, cement, and steel.           |
| `add_industry`                   | Adds selected custom industries to the sector-coupled network.                                             |
| `prepare_growth_rate_scenarios`  | Selects the appropriate growth-rate files for the configured demand-projection scenario.                   |
| `solve_custom_sector_network`    | Solves the customized sector-coupled model with clean electricity, RES policy, and tax-credit constraints. |

### Custom retrieve rules

PyPSA-Northamerica also includes retrieve rules that allow selected precomputed inputs to be used instead of rebuilding them from scratch.

| Rule name                     | Description                                                               |
| ----------------------------- | ------------------------------------------------------------------------- |
| `retrieve_cutouts`            | Retrieves North American cutouts.                                         |
| `retrieve_osm_raw`            | Retrieves raw OSM data and bypasses `download_osm_data`.                  |
| `retrieve_osm_clean`          | Retrieves cleaned OSM data and bypasses `clean_osm_data`.                 |
| `retrieve_shapes`             | Retrieves shape files and bypasses `build_shapes`.                        |
| `retrieve_osm_network`        | Retrieves the OSM-based network and bypasses `build_osm_network`.         |
| `retrieve_base_network`       | Retrieves `base.nc` and bypasses `base_network`.                          |
| `retrieve_renewable_profiles` | Retrieves renewable profiles and bypasses `build_renewable_profiles`.     |
| `retrieve_custom_powerplants` | Copies `data/custom_powerplants.csv` into the PyPSA-Earth data directory. |
| `retrieve_ssp2`               | Copies `data/NorthAmerica.csv` into the SSP2 data directory.              |
| `retrieve_demand_data`        | Retrieves utility demand input data.                                      |

### Computational reproducibility

The optimization problems generated by this project become extremely large when high spatial and temporal resolution are used.
In such cases, the computational cost is primarily driven by memory-intensive linear algebra operations required during the barrier matrix factorization of the optimisation problem.

#### Hardware and solver setup

All optimization runs were executed on homogeneous HPC nodes with the following configuration:

- **CPU:** Intel Xeon Gold 6342 (2.80 GHz)
- **Cores:** 48 physical cores (96 logical processors)
- **Operating system:** Debian GNU/Linux 12 (bookworm)

All optimization problems were solved using **Gurobi Optimizer 13.0.0**.

The following solver parameters were used consistently across all runs:

```
Method = 2        # Barrier algorithm
Crossover = 0     # Disable crossover to avoid additional memory and runtime overhead
BarConvTol = 1e-4
BarHomogeneous = 1
Threads = 8
```

No solver parameters were tuned on a per-scenario basis.

#### Problem size

The resulting linear optimisation problems are extremely large. Typical model sizes are:

| Temporal resolution | Rows | Columns | Nonzeros |
|---|---|---|---|
| 3-hour | ~100–150 million | ~50–75 million | ~200–350 million |
| 1-hour | ~280–440 million | ~135–220 million | ~630–1020 million |

Although presolve procedures eliminate a large fraction of constraints and variables, the resulting presolved systems remain extremely large.

#### Memory requirements

Memory requirements are characterized using the **Estimated Factorization Memory (EFM)** reported by the solver.
EFM represents the memory required to store the numerical factorization of the linear system solved at each barrier iteration.

Typical EFM values observed:

| Temporal resolution | Estimated factorization memory |
|---|---|
| 3-hour | ~100–130 GB |
| 1-hour | ~500 GB |

While EFM does not correspond to total solver memory consumption, it provides a good proxy for peak memory requirements because matrix factorization dominates the memory footprint of barrier-based methods.

### Runtime

Typical wall-clock solution times observed in the experiments are:

| Temporal resolution | Runtime (per time horizon)   |
|---|------------------------------|
| 3-hour | ~1–3 days (typically 2 days) |
| 1-hour | ~7–12 days                   |

Solver logs indicate that **85–95% of runtime is spent in repeated linear solves during barrier iterations**, while presolve, matrix ordering and other overheads account for only a small fraction of total runtime.

#### Implications for temporal resolution

The **3-hour temporal resolution** used in the main analysis represents a trade-off between temporal detail and computational feasibility.

At **1-hour resolution**, the base-year optimization alone requires approximately one week of runtime and around **500 GB of factorization memory**, making multi-scenario analyses computationally very expensive.
The 3-hour resolution significantly reduces both runtime and memory requirements while preserving the main temporal dynamics relevant for the analysis.

## Collaborators

PyPSA-NorthAmerica builds on the PyPSA-Earth-based model developed in the framework of the [[Grid modelling to assess electrofuels supply potential](https://github.com/open-energy-transition/efuels-supply-potentials) project by:

<table>
  <tbody>
    <tr>
      <td align="center">
        <a href="https://github.com/danielelerede-oet">
          <img src="https://avatars.githubusercontent.com/u/175011591?v=4" width="100;" alt="danielelerede-oet"/>
          <br />
          <sub><b>Daniele Lerede</b></sub>
        </a>
      </td>

      <td align="center">
        <a href="https://github.com/yerbol-akhmetov">
          <img src="https://avatars.githubusercontent.com/u/113768325?v=4" width="100;" alt="yerbol-akhmetov"/>
          <br />
          <sub><b>Yerbol Akhmetov</b></sub>
        </a>
      </td>

      <td align="center">
        <a href="https://github.com/GbotemiB">
          <img src="https://avatars.githubusercontent.com/u/48842684?v=4" width="100;" alt="GbotemiB"/>
          <br />
          <sub><b>Emmanuel Gbotemi</b></sub>
        </a>
      </td>

      <td align="center">
        <a href="https://github.com/hazemakhalek">
          <img src="https://avatars.githubusercontent.com/u/87850910?v=4" width="100;" alt="hazemakhalek"/>
          <br />
          <sub><b>Hazem Akhalek</b></sub>
        </a>
      </td>

      <td align="center">
        <a href="https://github.com/SermishaNarayana">
          <img src="https://avatars.githubusercontent.com/u/156903227?v=4" width="100;" alt="SermishaNarayana"/>
          <br />
          <sub><b>Sermisha Narayana</b></sub>
        </a>
      </td>
    </tr>
  </tbody>
</table>
