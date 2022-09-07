from uuid import uuid4

from flask import request
from ovos_utils.log import LOG
from selene_api.api import DeviceApi
from selene_api.identity import IdentityManager
from selene_api.pairing import has_been_paired

from ovos_local_backend.configuration import CONFIGURATION, BACKEND_IDENTITY

_selene_pairing_data = None
_selene_uuid = uuid4()
_selene_cfg = CONFIGURATION.get("selene") or {}

_ident_file = _selene_cfg.get("identity_file", "")
if _ident_file != IdentityManager.IDENTITY_FILE:
    IdentityManager.set_identity_file(_ident_file)

_device_api = DeviceApi(_selene_cfg.get("url"),
                        _selene_cfg.get("version") or "v1",
                        _selene_cfg.get("identity_file"))


def requires_selene_pairing(func_name):
    enabled = _selene_cfg.get("enabled")
    check_pairing = False
    if enabled:
        # identity file settings
        check_pairing = True

        # individual selene integration settings
        if "wolfie" in func_name and not _selene_cfg.get("proxy_wolfram"):
            check_pairing = False
        elif "owm" in func_name and not _selene_cfg.get("proxy_weather"):
            check_pairing = False
        elif func_name == "geolocation" and not _selene_cfg.get("proxy_geolocation"):
            check_pairing = False
        elif func_name == "send_mail" and not _selene_cfg.get("proxy_email"):
            check_pairing = False
        elif func_name == "location" and not _selene_cfg.get("download_location"):
            check_pairing = False
        elif func_name in ["get_uuid", "setting"] and \
                (not _selene_cfg.get("download_prefs") or request.method == 'PATCH'):
            check_pairing = False
        elif func_name == "setting" and not _selene_cfg.get("download_prefs"):
            check_pairing = False
        elif func_name == "settingsmeta" and not _selene_cfg.get("upload_settings"):
            check_pairing = False
        elif "skill_settings" in func_name:
            if request.method == 'PUT':
                if not _selene_cfg.get("upload_settings"):
                    check_pairing = False
            elif not _selene_cfg.get("download_settings"):
                check_pairing = False

        # check global opt in settings
        opt_in = _selene_cfg.get("opt_in")
        opts = ["precise_upload", "stt", "metric"]
        if not opt_in and func_name in opts:
            check_pairing = False
        else:
            if func_name == "precise_upload" and not _selene_cfg.get("upload_wakewords"):
                check_pairing = False
            if func_name == "stt" and not _selene_cfg.get("upload_utterances"):
                check_pairing = False
            if func_name == "metric" and not _selene_cfg.get("upload_metrics"):
                check_pairing = False

    return check_pairing


def get_selene_code():
    _selene_pairing_data = get_selene_pairing_data()
    return _selene_pairing_data.get("code")


def get_selene_pairing_data():
    global _selene_pairing_data
    if not _selene_pairing_data:
        try:
            _selene_pairing_data = _device_api.get_code(_selene_uuid)
        except:
            LOG.exception("Failed to get selene pairing data")
    return _selene_pairing_data or {}


def attempt_selene_pairing():
    backend_version = "0.0.1"
    platform = "ovos-local-backend"
    ident_file = _selene_cfg.get("identity_file") or BACKEND_IDENTITY
    if ident_file != IdentityManager.IDENTITY_FILE:
        IdentityManager.set_identity_file(ident_file)
    if _selene_cfg.get("enabled") and not has_been_paired():
        data = get_selene_pairing_data()
        if data:
            tok = data["token"]
            try:
                _device_api.activate(_selene_uuid, tok,
                                     platform=platform,
                                     platform_build=backend_version,
                                     core_version=backend_version,
                                     enclosure_version=backend_version)
            except:
                LOG.exception("Failed to pair with selene")