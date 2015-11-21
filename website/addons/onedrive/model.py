# -*- coding: utf-8 -*-
import logging

from onedrive import CredentialsV2, OnedriveClient
from onedrive.client import OnedriveClientException
from modularodm import fields

from framework.auth import Auth
from framework.exceptions import HTTPError

from website.addons.base import exceptions
from website.addons.base import AddonOAuthUserSettingsBase, AddonOAuthNodeSettingsBase
from website.addons.base import StorageAddonBase

from website.addons.onedrive import settings
from website.addons.onedrive.utils import OnedriveNodeLogger, refresh_oauth_key
from website.addons.onedrive.serializer import OnedriveSerializer
from website.oauth.models import ExternalProvider

logger = logging.getLogger(__name__)


class Onedrive(ExternalProvider):
    name = 'Onedrive'
    short_name = 'onedrive'

    client_id = settings.BOX_KEY
    client_secret = settings.BOX_SECRET

    auth_url_base = settings.BOX_OAUTH_AUTH_ENDPOINT
    callback_url = settings.BOX_OAUTH_TOKEN_ENDPOINT
    auto_refresh_url = settings.BOX_OAUTH_TOKEN_ENDPOINT
    default_scopes = ['root_readwrite']

    def handle_callback(self, response):
        """View called when the Oauth flow is completed. Adds a new OnedriveUserSettings
        record to the user and saves the user's access token and account info.
        """

        client = OnedriveClient(CredentialsV2(
            response['access_token'],
            response['refresh_token'],
            settings.BOX_KEY,
            settings.BOX_SECRET,
        ))

        about = client.get_user_info()

        return {
            'provider_id': about['id'],
            'display_name': about['name'],
            'profile_url': 'https://app.onedrive.com/profile/{0}'.format(about['id'])
        }

class OnedriveUserSettings(AddonOAuthUserSettingsBase):
    """Stores user-specific onedrive information
    """
    oauth_provider = Onedrive
    serializer = OnedriveSerializer


class OnedriveNodeSettings(StorageAddonBase, AddonOAuthNodeSettingsBase):

    oauth_provider = Onedrive
    serializer = OnedriveSerializer

    foreign_user_settings = fields.ForeignField(
        'onedriveusersettings', backref='authorized'
    )
    folder_id = fields.StringField(default=None)
    folder_name = fields.StringField()
    folder_path = fields.StringField()

    _folder_data = None

    _api = None

    @property
    def api(self):
        """authenticated ExternalProvider instance"""
        if self._api is None:
            self._api = Onedrive(self.external_account)
        return self._api

    @property
    def display_name(self):
        return '{0}: {1}'.format(self.config.full_name, self.folder_id)

    @property
    def has_auth(self):
        """Whether an access token is associated with this node."""
        return bool(self.user_settings and self.user_settings.has_auth)

    @property
    def complete(self):
        return bool(self.has_auth and self.user_settings.verify_oauth_access(
            node=self.owner,
            external_account=self.external_account,
        ))

    def fetch_folder_name(self):
        self._update_folder_data()
        return self.folder_name.replace('All Files', '/ (Full Onedrive)')

    def fetch_full_folder_path(self):
        self._update_folder_data()
        return self.folder_path

    def _update_folder_data(self):
        if self.folder_id is None:
            return None

        if not self._folder_data:
            try:
                refresh_oauth_key(self.external_account)
                client = OnedriveClient(self.external_account.oauth_key)
                self._folder_data = client.get_folder(self.folder_id)
            except OnedriveClientException:
                return

            self.folder_name = self._folder_data['name']
            self.folder_path = '/'.join(
                [x['name'] for x in self._folder_data['path_collection']['entries']]
                + [self._folder_data['name']]
            )
            self.save()

    def set_folder(self, folder_id, auth):
        self.folder_id = str(folder_id)
        self._update_folder_data()
        self.save()

        if not self.complete:
            self.user_settings.grant_oauth_access(
                node=self.owner,
                external_account=self.external_account,
                metadata={'folder': self.folder_id}
            )
            self.user_settings.save()

        # Add log to node
        nodelogger = OnedriveNodeLogger(node=self.owner, auth=auth)
        nodelogger.log(action="folder_selected", save=True)

    def set_user_auth(self, user_settings):
        """Import a user's Onedrive authentication and create a NodeLog.

        :param OnedriveUserSettings user_settings: The user settings to link.
        """
        self.user_settings = user_settings
        nodelogger = OnedriveNodeLogger(node=self.owner, auth=Auth(user_settings.owner))
        nodelogger.log(action="node_authorized", save=True)

    def deauthorize(self, auth=None, add_log=True):
        """Remove user authorization from this node and log the event."""
        node = self.owner

        if add_log:
            extra = {'folder_id': self.folder_id}
            nodelogger = OnedriveNodeLogger(node=node, auth=auth)
            nodelogger.log(action="node_deauthorized", extra=extra, save=True)

        self.folder_id = None
        self._update_folder_data()
        self.user_settings = None
        self.clear_auth()

        self.save()

    def serialize_waterbutler_credentials(self):
        if not self.has_auth:
            raise exceptions.AddonError('Addon is not authorized')
        try:
            refresh_oauth_key(self.external_account)
            return {'token': self.external_account.oauth_key}
        except OnedriveClientException as error:
            raise HTTPError(error.status_code, data={'message_long': error.message})

    def serialize_waterbutler_settings(self):
        if self.folder_id is None:
            raise exceptions.AddonError('Folder is not configured')
        return {'folder': self.folder_id}

    def create_waterbutler_log(self, auth, action, metadata):
        self.owner.add_log(
            'onedrive_{0}'.format(action),
            auth=auth,
            params={
                'path': metadata['materialized'],
                'project': self.owner.parent_id,
                'node': self.owner._id,
                'folder': self.folder_id,
                'urls': {
                    'view': self.owner.web_url_for('addon_view_or_download_file', provider='onedrive', action='view', path=metadata['path']),
                    'download': self.owner.web_url_for('addon_view_or_download_file', provider='onedrive', action='download', path=metadata['path']),
                },
            },
        )

    ##### Callback overrides #####
    def after_delete(self, node=None, user=None):
        self.deauthorize(Auth(user=user), add_log=True)
        self.save()

    def on_delete(self):
        self.deauthorize(add_log=False)
        self.clear_auth()
        self.save()
