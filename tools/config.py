# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2020 grommunio GmbH

import yaml
import logging
from os import scandir

logger = logging.getLogger("config")


def _defaultConfig():
    _defaultSyncPolicy = {
      "allowbluetooth": 2,
      "allowbrowser": 1,
      "allowcam": 1,
      "allowconsumeremail": 1,
      "allowdesktopsync": 1,
      "allowhtmlemail": 1,
      "allowinternetsharing": 1,
      "allowirda": 1,
      "allowpopimapemail": 1,
      "allowremotedesk": 1,
      "allowsimpledevpw": 1,
      "allowsmimeencalgneg": 2,
      "allowsmimesoftcerts": 1,
      "allowstoragecard": 1,
      "allowtextmessaging": 1,
      "allowunsignedapps": 1,
      "allowunsigninstallpacks": 1,
      "allowwifi": 1,
      "alphanumpwreq": 0,
      "approvedapplist": [],
      "attenabled": 1,
      "devencenabled": 0,
      "devpwenabled": 0,
      "devpwexpiration": 0,
      "devpwhistory": 0,
      "maxattsize": "",
      "maxcalagefilter": 0,
      "maxdevpwfailedattempts": 8,
      "maxemailagefilter": 0,
      "maxemailbodytruncsize": -1,
      "maxemailhtmlbodytruncsize": -1,
      "maxinacttimedevlock": 900,
      "mindevcomplexchars": 3,
      "mindevpwlenngth": 4,
      "pwrecoveryenabled": 0,
      "reqdevenc": 0,
      "reqencsmimealgorithm": 0,
      "reqencsmimemessages": 0,
      "reqmansyncroam": 0,
      "reqsignedsmimealgorithm": 0,
      "reqsignedsmimemessages": 0,
      "reqstoragecardenc": 0,
      "unapprovedinromapplist": []
    }
    return {
        "DB": {
            "sessionTimout": 28800,
            },
        "dns": {
            "dudIP": "172.16.254.254",
            "externalResolvers": ["1.1.1.1", "1.0.0.1"]
            },
        "openapi": {
            "validateRequest": True,
            "validateResponse": True
            },
        "options": {
            "antispamUrl": "http://localhost:11334",
            "disableDB": False,
            "dataPath": "/usr/share/grommunio-admin-common",
            "portrait": "portrait.jpg",
            "domainStoreRatio": 10,
            "domainPrefix": "/var/lib/gromox/domain/",
            "userPrefix": "/var/lib/gromox/user/",
            "exmdbHost": "::1",
            "exmdbPort": "5000",
            "domainStorageLevels": 1,
            "userStorageLevels": 2,
            "domainAcceleratedStorage": None,
            "userAcceleratedStorage": None,
            "dashboard": {
                "services": []
                },
            "serverPolicy": "round-robin",
            "updateLogPath": "/var/log/grommunio-update.log",
            "updateSkriptPath": "/usr/sbin/grommunio-update",
            },
        "security": {
            "jwtPrivateKeyFile": "/var/lib/grommunio-admin-api/auth-private.pem",
            "jwtPublicKeyFile": "/var/lib/grommunio-admin-api/auth-public.pem",
            "rsaKeySize": 4096,
            },
        "mconf": {
          "ldapPath": "/etc/gromox/ldap_adaptor.cfg",
          "authmgrPath": "/etc/gromox/authmgr.cfg"
          },
        "logs": {},
        "sync": {
            "syncStateFolder": "GS-SyncState",
            "defaultPolicy": _defaultSyncPolicy,
            "policyHosts": ["127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"]
            },
        "chat": {
            "connection": {},
            },
        "tasq": {},
        }


def initLoggers():
    if "logging" not in Config:
        return
    logconf = Config["logging"]
    logging.getLogger().setLevel(logconf.get("level", logging.WARNING))
    for logger, conf in logconf.get("loggers", {}).items():
        logging.getLogger(logger).setLevel(conf.get("level", logging.NOTSET))


def _recursiveMerge_(dst, add):
    """Recursively merge two dictionaries.

    Add values from `src` to `dst`. If a key from `src` is already present in `dst`,
    the merge strategy depends on their types:
        - If both are lists, the lists are concatenated
        - If both are dicts, they are merged recursively
        - Otherwise the value from `dst` is overwritten
    """
    assert type(dst) is dict and type(add) is dict
    for key in add.keys():
        if key in dst:
            if type(dst[key]) is list and type(add[key]) is list:
                dst[key] += add[key]
            elif type(dst[key]) is dict and type(add[key]) is dict:
                _recursiveMerge_(dst[key], add[key])
            else:
                dst[key] = add[key]
        else:
            dst[key] = add[key]


def _loadConfig_():
    """Load configuration file.

    Try to load configuration from './config.yaml'.
    If the file exists, the default configuration is updated.

    If the optional value 'confdir' is present,
    the specified directory is searched for further YAML files,
    which are recursively merged into the config.
    """
    config = _defaultConfig()
    try:
        with open("config.yaml", "r", encoding="utf-8") as file:
            _recursiveMerge_(config, yaml.load(file, Loader=yaml.SafeLoader))
    except Exception as err:
        logger.error("Failed to load 'config.yaml': {}".format(" - ".join(str(arg) for arg in err.args)))
    if "confdir" in config:
        try:
            configFiles = sorted([file.path for file in scandir(config["confdir"]) if file.name.endswith(".yaml")])
        except Exception as err:
            logger.error("Failed to stat '{}': ".format(config["confdir"])+" - ".join(str(arg) for arg in err.args))
            configFiles = ()
        for configFile in configFiles:
            try:
                with open(configFile, encoding="utf-8") as file:
                    confd = yaml.load(file, Loader=yaml.SafeLoader)
                if confd is not None:
                    _recursiveMerge_(config, confd)
            except Exception as err:
                logger.error("Failed to load '{}': {}".format(configFile, " - ".join(str(arg) for arg in err.args)))
    return config


Config = _loadConfig_()


def validate():
    """Verify configuration validity.

    Returns
    -------
    str
        Error message, or None if validation succeeds
    """
    import openapi_spec_validator
    from openapi_schema_validator import OAS30Validator
    version = [int(part) for part in openapi_spec_validator.__version__.split(".")]
    if version < [0, 5, 0]:
        from openapi_spec_validator.exceptions import ValidationError
    else:
        from openapi_spec_validator.validation.exceptions import ValidationError
    try:
        with open("res/config.yaml", encoding="utf-8") as file:
            configSchema = yaml.load(file, yaml.loader.SafeLoader)
    except Exception:
        return "Could not open schema file"
    validator = OAS30Validator(configSchema)
    try:
        validator.validate(Config)
    except ValidationError as err:
        return err.args[0]
