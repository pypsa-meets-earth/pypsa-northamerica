# SPDX-FileCopyrightText: PyPSA-NorthAmerica contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Custom helper functions for PyPSA-NorthAmerica workflows."""


def filter_cost_scenario_by_technology_group(costs, config):
    """Filter costs using custom technology-group scenario overrides."""
    wished_cost_scenario = config["cost_scenario"]
    scenario_by_group = config.get("cost_scenario_by_technology_group", {})

    # PyPSA-NorthAmerica:
    # Some North American workflows use different technology-data scenarios for
    # selected technology groups while keeping the global cost_scenario for all
    # other technologies.
    technology_groups = {
        "electricity": [
            "solar",
            "onwind",
            "offwind",
            "csp-tower",
            "hydro",
            "ror",
            "PHS",
            "nuclear",
            "CCGT",
            "OCGT",
            "coal",
            "oil",
            "geothermal",
            "biomass",
            "solar-utility",
            "battery storage",
        ],
        "H2_electrolysis": [
            "Alkaline electrolyzer large size",
            "Alkaline electrolyzer medium size",
            "Alkaline electrolyzer small size",
            "PEM electrolyzer small size",
            "SOEC",
        ],
        "dac": ["direct air capture"],
    }

    technology_to_scenario = {}
    for group, scenario in scenario_by_group.items():
        for technology in technology_groups.get(group, []):
            technology_to_scenario[technology] = scenario

    technologies = costs.index.get_level_values("technology")
    target_scenarios = technologies.map(
        lambda technology: technology_to_scenario.get(
            technology,
            wished_cost_scenario,
        )
    )

    return costs[
        (costs["scenario"].str.casefold() == target_scenarios.str.casefold())
        | costs["scenario"].isnull()
    ]
