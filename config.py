# Authentication Config
api_key = 'ENTER_YOUR_API_KEY'
base_url = 'https://api.meraki.cn/api/v1'

# Orgs and Networks
org_id = 'ENTER_YOUR_ORG_ID'

# Products to check
# Valid products are appliance, camera, cellularGateway, wireless, switch and sensor
# Any non-listed products will not have their update settings modified
products = ['appliance', 'camera', 'cellularGateway', 'wireless', 'switch', 'sensor']

# Delay Config
delay_tag = 'fw-delay'
delay_use_days = False # If delay_use_specific_date is True, this cannot be True, and delay_days must have a value
delay_use_specific_date = True # If delay_use_days is True, this cannot be True, and delay_specific_date must
# have a value
# These dates need to be further into the future than the currently scheduled upgrade
delay_days = 15 # cannot be greater than 30
delay_specific_date = "%Y-%m-%dT%H:%M:%SZ" # Replace %Y with year, %m with month, %d with day, %H with hour, %M with
# minute and %S with seconds, without removing anything else including the Z. The date cannot not be farther than
# 30 days into the future. This time and date will be applied to the specific network in their local time zone.

# Logging, Verbosity and Supervision
verbose = True # Will display information gathered about networks
supervised = True # Will ask before applying any configuration changes
console_logging = True # Will print API output to the console
max_retries = 100 # Number of times the API will retry when finding errors like 429
max_requests = 10 # Number of concurrent requests to the API