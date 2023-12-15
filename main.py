import meraki.aio
import asyncio
import pandas as pd
import config
import batch_helper
from tabulate import tabulate
from datetime import datetime
from datetime import timedelta

# Instantiate async Meraki API client
aiomeraki = meraki.aio.AsyncDashboardAPI(
    config.api_key,
    base_url="https://api.meraki.com/api/v1",
    log_file_prefix=__file__[:-3],
    print_console=False,
    maximum_retries=config.max_retries,
    maximum_concurrent_requests=config.max_requests,
)
# Instantiate synchronous Meraki API client
dashboard = meraki.DashboardAPI(
    config.api_key,
    base_url="https://api.meraki.com/api/v1",
    log_file_prefix=__file__[:-3],
    print_console=config.console_logging,
)

# Check if target date configuration is valid
if (config.delay_use_days and config.delay_use_specific_date) == True:
    print(f"Error! Cannot set both delay_use_days and delay_use_specific_date to True. Aborting script.")
    exit(1)
elif config.delay_use_days == True:
    if config.delay_days>30:
        print(f"Error! Target date cannot be more than 30 days into the future. Chosen date is {config.delay_days} days into the future.")
        exit(1)
    else:
        current_time = datetime.now()
        delay_date = current_time + timedelta(days=config.delay_days)
elif config.delay_use_specific_date == True:
    current_time = datetime.now()
    delay_date_str = config.delay_specific_date
    delay_date = datetime.strptime(delay_date_str, "%Y-%m-%dT%H:%M:%SZ")
    delta = delay_date - current_time
    if delta.days > 30:
        print(f"Error! Target date cannot be more than 30 days into the future. Chosen date is {delta} days into the future.")
        exit(1)

def print_tabulate(data):
    """
    Outputs a list of dictionaries in table format
    :param data: Dictionary to output
    :return:
    """
    print(tabulate(pd.DataFrame(data), headers='keys', tablefmt='fancy_grid'))

async def get_network_firmware_upgrades(aiomeraki, id):
    """
    Async function to obtain network upgrades
    :param aiomeraki: Async cleint of Dashboard API
    :param id: ID of network to check
    :return:
    """
    upg = await aiomeraki.networks.getNetworkFirmwareUpgrades(id)
    return {"net_id": id, "upgrade": upg}

async def get_upgrades(aiomeraki, net_ids_to_modify):
    """
    Iterate through list of networks to get Upgrade times
    :param aiomeraki: Async cleint of Dashboard API
    :param net_ids_to_modify: List of network IDs to check
    :return:
    """
    get_tasks = []
    results = []
    for id in net_ids_to_modify:
        get_tasks.append(get_network_firmware_upgrades(aiomeraki, id))
    for task in asyncio.as_completed(get_tasks):
        result = await task
        results.append(result)
    return results

if __name__ == "__main__":
    # Get network templates
    templates = dashboard.organizations.getOrganizationConfigTemplates(organizationId=config.org_id)
    if config.verbose==True:
        print("These are the templates in your organization:")
        print_tabulate(templates)
    # Get list of networks with tag fw-delay
    networks = dashboard.organizations.getOrganizationNetworks(organizationId=config.org_id, total_pages=-1,
                                                               tags=['fw-delay'])
    if config.verbose==True:
        print("These are the networks in your organization with the fw-delay tag:")
        print_tabulate(networks)
    # Get current list of upgrades with "Scheduled" status
    upgrades = dashboard.organizations.getOrganizationFirmwareUpgrades(organizationId=config.org_id, status="Scheduled")
    if config.verbose==True:
        print("These are the pending upgrades in your organization:")
        print_tabulate(upgrades)
    # Make list of networks bound to templates and their associated tags
    templated_networks = [
        {'net_name': net['name'],
         'net_id': net['id'],
         'template_id': net['configTemplateId'],
         'tags': net['tags']} for net in networks if net['isBoundToConfigTemplate'] == True]
    # These are the networks you currently have bound to templates
    if config.verbose==True:
        print("These are the templated networks in scope in your organization:")
        print_tabulate(templated_networks)
    # Find the unique templates with bound networks
    unique_templates_to_check = pd.DataFrame(templated_networks).template_id.unique()
    unique_templates_to_upgrade = []
    # Find if all networks bound to the template are tagged with fw-delay
    for id in unique_templates_to_check:
        nets = []
        for net in templated_networks:
            if net['template_id'] == id:
                nets.append(net)
        fw_tag = []
        for net in nets:
            if "fw-delay" in net['tags']:
                tag = "fw-delay"
            else:
                tag = ""
            fw_tag.append(tag)
        s = set(fw_tag)
        if len(s) == 1:
            unique_templates_to_upgrade.append(id)
    # Find standalone networks with the fw-delay tag
    standalone_net_ids = []
    for net in networks:
        if net['isBoundToConfigTemplate'] == False:
            standalone_net_ids.append(net['id'])

    # Combine both the unique templates to update and the standalone networks to update
    net_ids_to_modify = standalone_net_ids + unique_templates_to_upgrade

    # Filter list of upgrades with the previous list and check if the product to upgrade is listed in the config file
    network_upgrades = [
        upgrade for upgrade in upgrades if
        upgrade['network']['id'] in net_ids_to_modify and upgrade['productTypes'] in config.products
    ]
    if config.verbose==True:
        print("These are the upgrades to delay:")
        print_tabulate(network_upgrades)
    if config.supervised==True:
        print("These are the upgrades to delay:")
        print_tabulate(network_upgrades)
        proceed = input("Do you wish to proceed? (Y/N): ")
        if proceed == 'Y':
            # Start Async event loop
            loop = asyncio.get_event_loop()
            results = loop.run_until_complete(get_upgrades(aiomeraki, net_ids_to_modify))
            upgrades_to_delay = []
            # Create list of updates to upgrade settings per network and the date we wish to push to
            for result in results:
                for key in result['upgrade']["products"].keys():
                    for upgrade in network_upgrades:
                        if upgrade['network']['id'] == result['net_id'] and upgrade['productTypes'] == key:
                            if result['upgrade']['products'][key]['nextUpgrade']['time'] != "":
                                result['upgrade']['products'][key].pop('currentVersion')
                                result['upgrade']['products'][key].pop('lastUpgrade')
                                result['upgrade']['products'][key].pop('availableVersions')
                                upg_time = datetime.strptime(result['upgrade']['products'][key]['nextUpgrade']['time'],
                                                             "%Y-%m-%dT%H:%M:%SZ")
                                # If setting to a specific date and time
                                if config.delay_use_specific_date == True:
                                    new_upg_time = delay_date
                                # If delaying by a set number of days
                                else:
                                    delta = delay_date - upg_time
                                    new_upg_time = upg_time + timedelta(days=delta.days)
                                result['upgrade']['products'][key]['nextUpgrade'] = {
                                    'time': new_upg_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    'toVersion': result['upgrade']['products'][key]['nextUpgrade']['toVersion']}
                if config.verbose == True:
                    print("This upgrade will be added to the list of actions:")
                    print_tabulate(result['upgrade'])
                if config.supervised == True:
                    proceed = input("Proceed? Enter Y to proceed, and N to skip this upgrade: ")
                    if proceed == 'Y':
                        print("Adding upgrade to list of actions.")
                    elif proceed == 'N':
                        print("Skipping upgrade.")
                    else:
                        print("Invalid input. Skipping upgrade.")
                else:
                    upgrades_to_delay.append(result)

            # For the list of actions, generate action batches to delay the upgrades
            actions = []
            for upgrade in upgrades_to_delay:
                action = dashboard.batch.networks.updateNetworkFirmwareUpgrades(upgrade['net_id'], **upgrade['upgrade'])
                actions.append(action)

            # These are the actions to push as batches
            print("These are the actions that will be pushed.")
            print_tabulate(actions)
            test_helper = batch_helper.BatchHelper(dashboard, config.org_id, actions, linear_new_batches=False, actions_per_new_batch=100)
            test_helper.prepare()
            test_helper.generate_preview()
            test_helper.execute()

            print(f'helper status is {test_helper.status}')

            batches_report = dashboard.organizations.getOrganizationActionBatches(config.org_id)
            new_batches_statuses = [{'id': batch['id'], 'status': batch['status']} for batch in batches_report if
                                    batch['id'] in test_helper.submitted_new_batches_ids]
            failed_batch_ids = [batch['id'] for batch in new_batches_statuses if batch['status']['failed']]
            print(f'Failed batch IDs are as follows: {failed_batch_ids}')
        elif proceed == 'N':
            print("Aborted by user!")
            exit()
        else:
            print('Invalid input!')
            exit(1)
    else:
        # Start Async event loop
        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(get_upgrades(aiomeraki, net_ids_to_modify))
        upgrades_to_delay = []
        # Create list of updates to upgrade settings per network and the date we wish to push to
        for result in results:
            for key in result['upgrade']["products"].keys():
                for upgrade in network_upgrades:
                    if upgrade['network']['id'] == result['net_id'] and upgrade['productTypes'] == key:
                        if result['upgrade']['products'][key]['nextUpgrade']['time'] != "":
                            result['upgrade']['products'][key].pop('currentVersion')
                            result['upgrade']['products'][key].pop('lastUpgrade')
                            result['upgrade']['products'][key].pop('availableVersions')
                            upg_time = datetime.strptime(result['upgrade']['products'][key]['nextUpgrade']['time'],
                                                         "%Y-%m-%dT%H:%M:%SZ")
                            # If setting to a specific date and time
                            if config.delay_use_specific_date == True:
                                new_upg_time = delay_date
                            # If delaying by a set number of days
                            else:
                                delta = delay_date - upg_time
                                new_upg_time = upg_time + timedelta(days=delta.days)
                            result['upgrade']['products'][key]['nextUpgrade'] = {
                                'time': new_upg_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                'toVersion': result['upgrade']['products'][key]['nextUpgrade']['toVersion']}
            if config.verbose == True:
                print("This upgrade will be added to the list of actions:")
                print_tabulate(result['upgrade'])
            upgrades_to_delay.append(result)

        # For the list of actions, generate action batches to delay the upgrades
        actions = []
        for upgrade in upgrades_to_delay:
            action = dashboard.batch.networks.updateNetworkFirmwareUpgrades(upgrade['net_id'], **upgrade['upgrade'])
            actions.append(action)

        # These are the actions to push as batches
        print("These are the actions that will be pushed.")
        print_tabulate(actions)
        test_helper = batch_helper.BatchHelper(dashboard, config.org_id, actions, linear_new_batches=False,
                                               actions_per_new_batch=100)
        test_helper.prepare()
        test_helper.generate_preview()
        test_helper.execute()

        print(f'helper status is {test_helper.status}')

        batches_report = dashboard.organizations.getOrganizationActionBatches(config.org_id)
        new_batches_statuses = [{'id': batch['id'], 'status': batch['status']} for batch in batches_report if
                                batch['id'] in test_helper.submitted_new_batches_ids]
        failed_batch_ids = [batch['id'] for batch in new_batches_statuses if batch['status']['failed']]
        print(f'Failed batch IDs are as follows: {failed_batch_ids}')
