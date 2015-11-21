import os

from website.addons.onedrive import model, routes, utils


MODELS = [
    model.OnedriveUserSettings,
    model.OnedriveNodeSettings,
]

USER_SETTINGS_MODEL = model.OnedriveUserSettings
NODE_SETTINGS_MODEL = model.OnedriveNodeSettings

ROUTES = [routes.api_routes]

SHORT_NAME = 'onedrive'
FULL_NAME = 'Onedrive'

OWNERS = ['user', 'node']

ADDED_DEFAULT = []
ADDED_MANDATORY = []

VIEWS = []
CONFIGS = ['accounts', 'node']

CATEGORIES = ['storage']

# TODO: Deprecate in favor of webpack/CommonJS bundles
INCLUDE_JS = {
    'widget': [],
    'page': [],
    'files': []
}

INCLUDE_CSS = {
    'widget': [],
    'page': [],
}

HAS_HGRID_FILES = True
GET_HGRID_DATA = utils.onedrive_addon_folder

MAX_FILE_SIZE = 250  # MB

HERE = os.path.dirname(os.path.abspath(__file__))
NODE_SETTINGS_TEMPLATE = None  # use default node settings template
USER_SETTINGS_TEMPLATE = None  # use default user settings template
