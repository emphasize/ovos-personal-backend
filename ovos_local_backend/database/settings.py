import json

from json_database import JsonStorageXDG

from ovos_local_backend.configuration import CONFIGURATION


class SkillSettings:
    """ represents skill settings for a individual skill"""
    def __init__(self, skill_id, skill_settings=None, meta=None, display_name=None):
        self.skill_id = skill_id
        self.display_name = display_name or self.skill_id
        self.settings = skill_settings or {}
        self.meta = meta or {}

    def serialize(self):
        # settings meta with updated placeholder values from settings
        # old style selene db stored skill settings this way
        meta = dict(self.meta)
        for idx, section in enumerate(meta.get('sections', [])):
            for idx2, field in enumerate(section["fields"]):
                if "value" not in field:
                    continue
                if field["name"] in self.settings:
                    meta['sections'][idx]["fields"][idx2]["value"] = self.settings[field["name"]]
        return {'skillMetadata': meta,
                "uuid": self.skill_id,  # the uuid from selene is not device id (?)
                "skill_gid": self.skill_id,
                "display_name": self.display_name,
                "identifier": self.skill_id}

    @staticmethod
    def deserialize(data):
        if isinstance(data, str):
            data = json.loads(data)

        skill_json = {}
        skill_meta = data.get("skillMetadata")
        for s in skill_meta.get("sections", []):
            for f in s.get("fields", []):
                if "name" in f and "value" in f:
                    skill_json[f["name"]] = f["value"]

        skill_id = data.get("skill_gid") or data.get("identifier")
        # skill_id = skill_id.split("|")[0]
        display_name = data.get("display_name")

        return SkillSettings(skill_id, skill_json, skill_meta, display_name)


class DeviceSettings:
    """ global device settings
    represent some fields from mycroft.conf but also contain some extra fields
    """

    def __init__(self, uuid, token, name=None, device_location=None, opt_in=False,
                 location=None, lang=None, date_format=None, system_unit=None, time_format=None,
                 email=None, isolated_skills=False):
        self.uuid = uuid
        self.token = token

        # ovos exclusive
        # TODO - endpoints/minimal UI to toggle
        # TODO - refactor this to work per skill instead of per device
        self.isolated_skills = isolated_skills  # control if skill settings should be shared across all devices

        # extra device info
        self.name = name or f"Device-{self.uuid}"  # friendly device name
        self.device_location = device_location or "somewhere"  # indoor location
        self.email = email or CONFIGURATION.get("email", {}).get("username")  # email sending api

        # mycroft.conf values
        self.date_format = date_format or CONFIGURATION.get("date_format") or "DMY"
        self.system_unit = system_unit or CONFIGURATION.get("system_unit") or "device"
        self.time_format = time_format or CONFIGURATION.get("time_format") or "full"
        self.opt_in = opt_in
        self.lang = lang or CONFIGURATION.get("lang") or "en-us"
        self.location = location or CONFIGURATION["default_location"]

    @property
    def selene_device(self):
        return {
            "description": self.device_location,
            "uuid": self.uuid,
            "name": self.name,

            # not tracked / meaningless
            # just for api compliance with selene
            'coreVersion': "unknown",
            'platform': 'unknown',
            'enclosureVersion': "",
            "user": {"uuid": self.uuid}  # users not tracked
        }

    @property
    def selene_settings(self):
        return {
            "dateFormat": self.date_format,
            "optIn": self.opt_in,
            "systemUnit": self.system_unit,
            "timeFormat": self.time_format,
            "uuid": self.uuid
        }

    def serialize(self):
        return self.__dict__

    @staticmethod
    def deserialize(data):
        if isinstance(data, str):
            data = json.loads(data)
        return DeviceSettings(**data)


class DeviceDatabase(JsonStorageXDG):
    """ database of paired devices, used to keep track of individual device settings"""
    def __init__(self):
        super().__init__("ovos_devices")

    def add_device(self, uuid, token, name=None, device_location=None, opt_in=False,
                   location=None, lang=None, date_format=None, system_unit=None,
                   time_format=None, email=None, isolated_skills=False):
        device = DeviceSettings(uuid, token, name, device_location, opt_in,
                                location, lang, date_format, system_unit,
                                time_format, email, isolated_skills)
        self[uuid] = device.serialize()
        return device

    def get_device(self, uuid):
        dev = self.get(uuid)
        if dev:
            return DeviceSettings.deserialize(dev)
        return None

    def total_devices(self):
        return len(self)

    def __iter__(self):
        for dev in self.values():
            yield DeviceSettings.deserialize(dev)

    def __enter__(self):
        """ Context handler """
        return self

    def __exit__(self, _type, value, traceback):
        """ Commits changes and Closes the session """
        try:
            self.store()
        except Exception as e:
            print(e)


class SettingsDatabase(JsonStorageXDG):
    """ database of device specific skill settings """
    def __init__(self):
        super().__init__("ovos_skill_settings")

    def add_setting(self, uuid, skill_id, setting, meta, display_name=None):
        # check if this device is using "isolated_skills" flag
        # this flag controls if the device keeps it's own unique
        # settings or if skill settings are synced across all devices
        with DeviceDatabase() as db:
            dev = db.get_device(uuid)
            if dev and not dev.isolated_skills:
                # add setting to shared db
                with SharedSettingsDatabase() as sdb:
                    return sdb.add_setting(skill_id, setting, meta, display_name)

        # add setting to device specific db
        skill = SkillSettings(skill_id, setting, meta, display_name)
        if uuid not in self:
            self[uuid] = {}
        self[uuid][skill_id] = skill.serialize()
        return skill

    def get_setting(self, skill_id, uuid):
        # check if this device is using "isolated_skills" flag
        # this flag controls if the device keeps it's own unique
        # settings or if skill settings are synced across all devices
        with DeviceDatabase() as db:
            dev = db.get_device(uuid)
            # get setting from shared db
            if dev and not dev.isolated_skills:
                with SharedSettingsDatabase() as sdb:
                    return sdb.get_setting(skill_id)

        # get setting from device specific db
        if uuid in self:
            skill = self[uuid].get(skill_id)
            if skill:
                return SkillSettings.deserialize(skill)
        return None

    def get_device_settings(self, uuid):
        # check if this device is using "isolated_skills" flag
        # this flag controls if the device keeps it's own unique
        # settings or if skill settings are synced across all devices
        with DeviceDatabase() as db:
            dev = db.get_device(uuid)
            # get settings from shared db
            if dev and not dev.isolated_skills:
                return [s for s in SharedSettingsDatabase()]

        # get setting from device specific db
        if uuid not in self:
            return []
        return [SkillSettings.deserialize(skill)
                for skill in self[uuid].values()]

    def __enter__(self):
        """ Context handler """
        return self

    def __exit__(self, _type, value, traceback):
        """ Commits changes and Closes the session """
        try:
            self.store()
        except Exception as e:
            print(e)


class SharedSettingsDatabase(JsonStorageXDG):
    """ database of skill settings shared across all devices """
    def __init__(self):
        super().__init__("ovos_shared_skill_settings")

    def add_setting(self, skill_id, setting, meta, display_name=None):
        skill = SkillSettings(skill_id, setting, meta, display_name)
        self[skill_id] = skill.serialize()
        return skill

    def get_setting(self, skill_id):
        skill = self.get(skill_id)
        if skill:
            return SkillSettings.deserialize(skill)
        return None

    def __iter__(self):
        for skill in self.values():
            yield SkillSettings.deserialize(skill)

    def __enter__(self):
        """ Context handler """
        return self

    def __exit__(self, _type, value, traceback):
        """ Commits changes and Closes the session """
        try:
            self.store()
        except Exception as e:
            print(e)