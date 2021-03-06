"""Views for the node settings page."""
# -*- coding: utf-8 -*-
import os
import httplib as http

from flask import request
from onedrive.client import OnedriveClient, OnedriveClientException
from urllib3.exceptions import MaxRetryError

from framework.exceptions import HTTPError, PermissionsError
from framework.auth.decorators import must_be_logged_in

from website.oauth.models import ExternalAccount

from website.util import permissions
from website.project.decorators import (
    must_have_addon, must_be_addon_authorizer,
    must_have_permission, must_not_be_registration,
)

from website.addons.onedrive.utils import refresh_oauth_key
from website.addons.onedrive.serializer import OnedriveSerializer


@must_be_logged_in
def onedrive_get_user_settings(auth):
    """ Returns the list of all of the current user's authorized Onedrive accounts """
    serializer = OnedriveSerializer(user_settings=auth.user.get_addon('onedrive'))
    return serializer.serialized_user_settings


@must_have_addon('onedrive', 'node')
@must_have_permission(permissions.WRITE)
def onedrive_get_config(node_addon, auth, **kwargs):
    """API that returns the serialized node settings."""
    if node_addon.external_account:
        refresh_oauth_key(node_addon.external_account)
    return {
        'result': OnedriveSerializer().serialize_settings(node_addon, auth.user),
    }


@must_not_be_registration
@must_have_addon('onedrive', 'user')
@must_have_addon('onedrive', 'node')
@must_be_addon_authorizer('onedrive')
@must_have_permission(permissions.WRITE)
def onedrive_set_config(node_addon, user_addon, auth, **kwargs):
    """View for changing a node's linked onedrive folder."""
    folder = request.json.get('selected')
    serializer = OnedriveSerializer(node_settings=node_addon)

    uid = folder['id']
    path = folder['path']

    node_addon.set_folder(uid, auth=auth)

    return {
        'result': {
            'folder': {
                'name': path.replace('All Files', '') if path != 'All Files' else '/ (Full Onedrive)',
                'path': path,
            },
            'urls': serializer.addon_serialized_urls,
        },
        'message': 'Successfully updated settings.',
    }


@must_have_addon('onedrive', 'user')
@must_have_addon('onedrive', 'node')
@must_have_permission(permissions.WRITE)
def onedrive_add_user_auth(auth, node_addon, user_addon, **kwargs):
    """Import onedrive credentials from the currently logged-in user to a node.
    """
    external_account = ExternalAccount.load(
        request.json['external_account_id']
    )

    if external_account not in user_addon.external_accounts:
        raise HTTPError(http.FORBIDDEN)

    try:
        node_addon.set_auth(external_account, user_addon.owner)
    except PermissionsError:
        raise HTTPError(http.FORBIDDEN)

    node_addon.set_user_auth(user_addon)
    node_addon.save()

    return {
        'result': OnedriveSerializer().serialize_settings(node_addon, auth.user),
        'message': 'Successfully imported access token from profile.',
    }


@must_not_be_registration
@must_have_addon('onedrive', 'node')
@must_have_permission(permissions.WRITE)
def onedrive_remove_user_auth(auth, node_addon, **kwargs):
    node_addon.deauthorize(auth=auth)
    node_addon.save()


@must_have_addon('onedrive', 'user')
@must_have_addon('onedrive', 'node')
@must_have_permission(permissions.WRITE)
def onedrive_get_share_emails(auth, user_addon, node_addon, **kwargs):
    """Return a list of emails of the contributors on a project.

    The current user MUST be the user who authenticated Onedrive for the node.
    """
    if not node_addon.user_settings:
        raise HTTPError(http.BAD_REQUEST)
    # Current user must be the user who authorized the addon
    if node_addon.user_settings.owner != auth.user:
        raise HTTPError(http.FORBIDDEN)

    return {
        'result': {
            'emails': [
                contrib.username
                for contrib in node_addon.owner.contributors
                if contrib != auth.user
            ],
        }
    }


@must_have_addon('onedrive', 'node')
@must_be_addon_authorizer('onedrive')
def onedrive_folder_list(node_addon, **kwargs):
    """Returns a list of folders in Onedrive"""
    if not node_addon.has_auth:
        raise HTTPError(http.FORBIDDEN)

    node = node_addon.owner
    folder_id = request.args.get('folderId')

    if folder_id is None:
        return [{
            'id': '0',
            'path': 'All Files',
            'addon': 'onedrive',
            'kind': 'folder',
            'name': '/ (Full Onedrive)',
            'urls': {
                'folders': node.api_url_for('onedrive_folder_list', folderId=0),
            }
        }]

    try:
        refresh_oauth_key(node_addon.external_account)
        client = OnedriveClient(node_addon.external_account.oauth_key)
    except OnedriveClientException:
        raise HTTPError(http.FORBIDDEN)

    try:
        metadata = client.get_folder(folder_id)
    except OnedriveClientException:
        raise HTTPError(http.NOT_FOUND)
    except MaxRetryError:
        raise HTTPError(http.BAD_REQUEST)

    # Raise error if folder was deleted
    if metadata.get('is_deleted'):
        raise HTTPError(http.NOT_FOUND)

    folder_path = '/'.join(
        [
            x['name']
            for x in metadata['path_collection']['entries']
        ] + [metadata['name']]
    )

    return [
        {
            'addon': 'onedrive',
            'kind': 'folder',
            'id': item['id'],
            'name': item['name'],
            'path': os.path.join(folder_path, item['name']),
            'urls': {
                'folders': node.api_url_for('onedrive_folder_list', folderId=item['id']),
            }
        }
        for item in metadata['item_collection']['entries']
        if item['type'] == 'folder'
    ]
