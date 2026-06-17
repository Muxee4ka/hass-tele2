"""Constants for the Tele2 (t2) integration."""

DOMAIN = "tele2"

CONF_PHONE = "phone"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_IMPERSONATE = "impersonate"
CONF_BOOST_INTERVAL = "boost_interval"
CONF_BOOST_COST = "boost_cost"
CONF_MANAGE_SLAVES = "manage_slaves"
CONF_SLAVE_MARKET = "slave_market"
CONF_MANAGE_SERVICES = "manage_services"

DEFAULT_SCAN_INTERVAL = 600  # seconds (10 minutes)
DEFAULT_BOOST_INTERVAL = 15  # minutes between marketplace boosts (for analytics)
DEFAULT_BOOST_COST = 5  # rubles per boost («ракета»)
DEFAULT_MANAGE_SLAVES = True  # auto-discover and expose linked (slave) numbers
DEFAULT_SLAVE_MARKET = False  # fetch marketplace lots for slave numbers too
DEFAULT_MANAGE_SERVICES = True  # fetch connected services and expose service switches
TOKEN_REFRESH_MARGIN = 300  # refresh access token this many seconds before exp
# curl_cffi TLS profile used by tele2api to pass t2's anti-bot (NGENIX/WAF).
# The library default (chrome131_android) is currently blocked; firefox passes.
DEFAULT_IMPERSONATE = "firefox133"

PLATFORMS = ["sensor", "switch"]

TRAFFIC_TYPES = ["voice", "data", "sms"]
EMOJIS = ["cat", "scream", "bomb", "rich", "zipped", "tongue", "cool", "devil"]
