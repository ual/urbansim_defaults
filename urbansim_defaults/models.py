from urbansim.developer import developer
import urbansim.sim.simulation as sim
from urbansim.utils import misc
from urbansim.utils import networks
from urbansim.models import transition
import os
import random
from urbansim_defaults import utils
import time
import datasources
import variables
import pandana as pdna
import pandas as pd
import numpy as np


@sim.model('rsh_estimate')
def rsh_estimate(homesales, aggregations):
    return utils.hedonic_estimate("rsh.yaml", homesales, aggregations)


@sim.model('rsh_simulate')
def rsh_simulate(buildings, aggregations):
    return utils.hedonic_simulate("rsh.yaml", buildings, aggregations,
                                  "residential_price")


@sim.model('nrh_estimate')
def nrh_estimate(costar, aggregations):
    return utils.hedonic_estimate("nrh.yaml", costar, aggregations)


@sim.model('nrh_simulate')
def nrh_simulate(buildings, aggregations):
    return utils.hedonic_simulate("nrh.yaml", buildings, aggregations,
                                  "non_residential_price")


@sim.model('hlcm_estimate')
def hlcm_estimate(households, buildings, aggregations):
    return utils.lcm_estimate("hlcm.yaml", households, "building_id",
                              buildings, aggregations)


@sim.model('hlcm_simulate')
def hlcm_simulate(households, buildings, aggregations, settings):
    return utils.lcm_simulate("hlcm.yaml", households, buildings,
                              aggregations,
                              "building_id", "residential_units",
                              "vacant_residential_units",
                              settings.get("enable_supply_correction", None))


@sim.model('elcm_estimate')
def elcm_estimate(jobs, buildings, aggregations):
    return utils.lcm_estimate("elcm.yaml", jobs, "building_id",
                              buildings, aggregations)


@sim.model('elcm_simulate')
def elcm_simulate(jobs, buildings, aggregations):
    return utils.lcm_simulate("elcm.yaml", jobs, buildings, aggregations,
                              "building_id", "job_spaces",
                              "vacant_job_spaces")


@sim.model('households_relocation')
def households_relocation(households, settings):
    rate = settings['rates']['households_relocation']
    return utils.simple_relocation(households, rate, "building_id")


@sim.model('jobs_relocation')
def jobs_relocation(jobs, settings):
    rate = settings['rates']['jobs_relocation']
    return utils.simple_relocation(jobs, rate, "building_id")


@sim.model('households_transition')
def households_transition(households, household_controls, year, settings):
    ct = household_controls.to_frame()
    hh = households.to_frame(households.local_columns +
                             settings['households_transition']['add_columns'])
    print "Total households before transition: {}".format(len(hh))
    tran = transition.TabularTotalsTransition(ct,
                                              settings['households_transition']
                                              ['total_column'])
    model = transition.TransitionModel(tran)
    new, added_hh_idx, new_linked = model.transition(hh, year)
    new.loc[added_hh_idx, "building_id"] = -1
    print "Total households after transition: {}".format(len(new))
    sim.add_table("households", new)


@sim.model('simple_households_transition')
def simple_households_transition(households, settings):
    rate = settings['rates']['simple_households_transition']
    return utils.simple_transition(households, rate, "building_id")


@sim.model('jobs_transition')
def jobs_transition(jobs, employment_controls, year, settings):
    ct = employment_controls.to_frame()
    hh = jobs.to_frame(jobs.local_columns +
                       settings['jobs_transition']['add_columns'])
    print "Total jobs before transition: {}".format(len(hh))
    tran = transition.TabularTotalsTransition(ct,
                                              settings['jobs_transition']
                                              ['total_column'])
    model = transition.TransitionModel(tran)
    new, added_hh_idx, new_linked = model.transition(hh, year)
    new.loc[added_hh_idx, "building_id"] = -1
    print "Total jobs after transition: {}".format(len(new))
    sim.add_table("jobs", new)


@sim.model('simple_jobs_transition')
def jobs_transition(jobs, settings):
    rate = settings['rates']['simple_jobs_transition']
    return utils.simple_transition(jobs, rate, "building_id")


@sim.model('build_networks')
def build_networks(settings):
    name = settings['build_networks']['name']
    st = pd.HDFStore(os.path.join(misc.data_dir(), name), "r")
    nodes, edges = st.nodes, st.edges
    net = pdna.Network(nodes["x"], nodes["y"], edges["from"], edges["to"],
                       edges[["weight"]])
    net.precompute(settings['build_networks']['max_distance'])
    sim.add_injectable("net", net)


@sim.model('neighborhood_vars')
def neighborhood_vars(net):
    nodes = networks.from_yaml(net, "neighborhood_vars.yaml")
    nodes = nodes.fillna(0)
    print nodes.describe()
    sim.add_table("nodes", nodes)


@sim.model('price_vars')
def price_vars(net):
    nodes2 = networks.from_yaml(net, "price_vars.yaml")
    nodes2 = nodes2.fillna(0)
    print nodes2.describe()
    nodes = sim.get_table('nodes')
    nodes = nodes.to_frame().join(nodes2)
    sim.add_table("nodes", nodes)


@sim.model('feasibility')
def feasibility(parcels, settings):
    kwargs = settings['feasibility']
    utils.run_feasibility(parcels,
                          sim.get_injectable('parcel_sales_price_sqft'),
                          sim.get_injectable('parcel_is_allowed'),
                          **kwargs)


def add_extra_columns(df):
    for col in ["residential_price", "non_residential_price"]:
        df[col] = 0
    return df


@sim.model('residential_developer')
def residential_developer(feasibility, households, buildings, parcels, year,
                          settings):
    kwargs = settings['residential_developer']
    new_buildings = utils.run_developer(
        "residential",
        households,
        buildings,
        "residential_units",
        parcels.parcel_size,
        parcels.ave_sqft_per_unit,
        parcels.total_residential_units,
        feasibility,
        year=year,
        form_to_btype_callback=sim.get_injectable("form_to_btype_f"),
        add_more_columns_callback=add_extra_columns,
        **kwargs)

    utils.add_parcel_output(new_buildings)


@sim.model('non_residential_developer')
def non_residential_developer(feasibility, jobs, buildings, parcels, year,
                              settings):

    kwargs = settings['non_residential_developer']
    new_buildings = utils.run_developer(
        ["office", "retail", "industrial"],
        jobs,
        buildings,
        "job_spaces",
        parcels.parcel_size,
        parcels.ave_sqft_per_unit,
        parcels.total_job_spaces,
        feasibility,
        year=year,
        form_to_btype_callback=sim.get_injectable("form_to_btype_f"),
        add_more_columns_callback=add_extra_columns,
        residential=False,
        **kwargs)

    utils.add_parcel_output(new_buildings)


@sim.model("diagnostic_output")
def diagnostic_output(households, buildings, zones, year):
    households = households.to_frame()
    buildings = buildings.to_frame()
    zones = zones.to_frame()

    zones['residential_units'] = buildings.groupby('zone_id').\
        residential_units.sum()
    zones['non_residential_sqft'] = buildings.groupby('zone_id').\
        non_residential_sqft.sum()

    zones['retail_sqft'] = buildings.query('general_type == "Retail"').\
        groupby('zone_id').non_residential_sqft.sum()
    zones['office_sqft'] = buildings.query('general_type == "Office"').\
        groupby('zone_id').non_residential_sqft.sum()
    zones['industrial_sqft'] = buildings.query('general_type == "Industrial"').\
        groupby('zone_id').non_residential_sqft.sum()

    zones['average_income'] = households.groupby('zone_id').income.quantile()
    zones['household_size'] = households.groupby('zone_id').persons.quantile()

    zones['residential_price'] = buildings.\
        query('general_type == "Residential"').groupby('zone_id').\
        residential_price.quantile()
    zones['retail_rent'] = buildings[buildings.general_type == "Retail"].\
        groupby('zone_id').non_residential_price.quantile()
    zones['office_rent'] = buildings[buildings.general_type == "Office"].\
        groupby('zone_id').non_residential_price.quantile()
    zones['industrial_rent'] = \
        buildings[buildings.general_type == "Industrial"].\
        groupby('zone_id').non_residential_price.quantile()

    if "price_shifters" in sim.list_injectables():
        zones["price_shifters"] = sim.get_injectable("price_shifters")

    utils.add_simulation_output(zones, "diagnostic_outputs", year)


@sim.model("clear_cache")
def clear_cache():
    sim.clear_cache()


# this method is used to push messages from urbansim to websites for live
# exploration of simulation results
@sim.model("pusher")
def pusher(year, run_number, uuid, settings):
    try:
        import pusher
    except:
        # if pusher not installed, just return
        return
    import socket

    p = pusher.Pusher(
        app_id='90082',
        key=settings['pusher']['key'],
        secret=settings['pusher']['secret']
    )
    host = settings['pusher']['host']
    sim_output = host+"runs/run{}_simulation_output.json".format(run_number)
    parcel_output = host+"runs/run{}_parcel_output.csv".format(run_number)
    p['urbansim'].trigger('simulation_year_completed',
                          {'year': year,
                           'region': settings['pusher']['region'],
                           'run_number': run_number,
                           'hostname': socket.gethostname(),
                           'uuid': uuid,
                           'time': time.ctime(),
                           'sim_output': sim_output,
                           'field_name': 'residential_units',
                           'table': 'diagnostic_outputs',
                           'scale': 'jenks',
                           'parcel_output': parcel_output})

