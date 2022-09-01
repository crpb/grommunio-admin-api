# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2020-2021 grommunio GmbH

import api

from api.core import API, secure
from api.security import checkPermissions
from base64 import b64decode
from datetime import datetime
from flask import request, jsonify
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from .. import defaultListHandler, defaultObjectHandler

from services import Service

from tools import formats
from tools.config import Config
from tools.constants import PropTags, PropTypes, ExchangeErrors, PrivateFIDs, Permissions
from tools.misc import createMapping, loadPSO, GenericObject
from tools.permissions import SystemAdminPermission, DomainAdminPermission, DomainAdminROPermission
from tools.rop import nxTime, makeEidEx
from tools.storage import setDirectoryOwner, setDirectoryPermission

import json
import shutil

from orm import DB


@API.route(api.BaseRoute+"/domains/<int:domainID>/users", methods=["GET"])
@secure(requireDB=True)
def getUsers(domainID):
    checkPermissions(DomainAdminROPermission(domainID))
    from orm.users import Users, UserProperties
    verbosity = int(request.args.get("level", 1))
    query, limit, offset, count = defaultListHandler(Users, filters=(Users.domainID == domainID,), result="query")
    sorts = request.args.getlist("sort")
    for s in sorts:
        sprop, sorder = s.split(",", 1) if "," in s else (s, "asc")
        if hasattr(PropTags, sprop.upper()):
            up = aliased(UserProperties)
            query = query.join(up, (up.userID == Users.ID) & (up.tag == getattr(PropTags, sprop.upper())))\
                         .order_by(up._propvalstr.desc() if sorder == "desc" else up._propvalstr.asc())
    data = [user.todict(verbosity) for user in query.limit(limit).offset(offset).all()]
    if verbosity < 2 and "properties" in request.args:
        tags = [getattr(PropTags, prop.upper(), None) for prop in request.args["properties"].split(",")]
        for user in data:
            user["properties"] = {}
        usermap = createMapping(data, lambda x: x["ID"])
        properties = UserProperties.query.filter(UserProperties.userID.in_(usermap.keys()), UserProperties.tag.in_(tags)).all()
        for prop in properties:
            usermap[prop.userID]["properties"][prop.name] = prop.val
    return jsonify(count=count, data=data)


@API.route(api.BaseRoute+"/domains/<int:domainID>/users", methods=["POST"])
@secure(requireDB=True, authLevel="user")
def createUser(domainID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import Users
    data = request.get_json(silent=True) or {}
    data["domainID"] = domainID
    if SystemAdminPermission() not in request.auth["user"].permissions():
        data.pop("homeserver", None)
    result, code = Users.create(data, reloadGromoxHttp=True)
    if code != 201:
        return jsonify(message=result), code
    return jsonify(result.fulldesc()), 201


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>", methods=["GET", "PATCH"])
@secure(requireDB=True, authLevel="user")
def userObjectEndpoint(domainID, userID):
    checkPermissions(DomainAdminROPermission(domainID) if request.method == "GET" else DomainAdminPermission(domainID))
    if request.method == "PATCH" and SystemAdminPermission() not in request.auth["user"].permissions():
        data = request.get_json(silent=True) or {}
        data.pop("homeserver", None)
    from orm.users import Users
    return defaultObjectHandler(Users, userID, "User", filters=(Users.domainID == domainID,))


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>", methods=["DELETE"])
@secure(requireDB=True)
def deleteUserEndpoint(domainID, userID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User #{} not found".format(userID)), 404
    return deleteUser(user, not request.args.get("deleteChatUser") == "false")


def deleteUser(user, deleteChatUser):
    if user.ID == 0:
        return jsonify(message="Cannot delete superuser"), 400
    userdata = GenericObject(maildir=user.maildir, homeserver=user.homeserver)
    user.delete(deleteChatUser)
    try:
        DB.session.commit()
    except Exception:
        return jsonify(message="Cannot delete user: Database commit failed."), 500
    with Service("exmdb", Service.SUPPRESS_INOP) as exmdb:
        client = exmdb.user(userdata)
        client.unloadStore()
    if request.args.get("deleteFiles") == "true":
        shutil.rmtree(userdata.maildir, ignore_errors=True)
    return jsonify(message="isded")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/password", methods=["PUT"])
@secure(requireDB=True, authLevel="user")
def setUserPassword(domainID, userID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import Users
    if userID == request.auth["user"].ID:
        return jsonify(message="Cannot reset own password, use '/passwd' endpoint instead"), 400
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    if user.externID is not None:
        return jsonify(message="Cannot modify LDAP imported user"), 400
    data = request.get_json(silent=True)
    if data is None or "new" not in data:
        return jsonify(message="Incomplete data"), 400
    user.password = data["new"]
    DB.session.commit()
    return jsonify(message="Success")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/roles", methods=["PATCH"])
@secure(requireDB=True)
def updateUserRoles(domainID, userID):
    checkPermissions(SystemAdminPermission())
    from orm.roles import AdminUserRoleRelation, AdminRoles
    data = request.get_json(silent=True)
    if data is None or "roles" not in data:
        return jsonify(message="Missing roles array"), 400
    roles = {role.roleID for role in AdminUserRoleRelation.query.filter(AdminUserRoleRelation.userID == userID).all()}
    requested = set(data["roles"])
    remove = roles-requested
    add = requested-roles
    AdminUserRoleRelation.query.filter(AdminUserRoleRelation.userID == userID, AdminUserRoleRelation.roleID.in_(remove))\
                               .delete(synchronize_session=False)
    for ID in add:
        DB.session.add(AdminUserRoleRelation(userID, ID))
    try:
        DB.session.commit()
    except IntegrityError as err:
        return jsonify(message="Invalid data", error=err.orig.args[1]), 400
    roles = AdminRoles.query.join(AdminUserRoleRelation).filter(AdminUserRoleRelation.userID == userID).all()
    return jsonify(data=[role.ref() for role in roles])


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/storeProps", methods=["GET", "DELETE"])
@secure(requireDB=True)
def rdUserStoreProps(domainID, userID):
    checkPermissions(DomainAdminROPermission(domainID) if request.method == "GET" else DomainAdminPermission(domainID))
    from orm.users import DB, Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    props = [prop for prop in request.args.get("properties", "").split(",") if prop != ""]
    try:
        user.properties = {prop: None for prop in props}
    except ValueError as err:
        return jsonify(message=err.args[0])
    if len(props) == 0:
        return jsonify(data={}) if request.method == "GET" else jsonify(message="Nothing to delete")
    for i in range(len(props)):
        if not hasattr(PropTags, props[i].upper()) or not isinstance(getattr(PropTags, props[i].upper()), int):
            return jsonify(message="Unknown property '{}'".format(props[i])), 400
        props[i] = getattr(PropTags, props[i].upper())
    with Service("exmdb") as exmdb:
        client = exmdb.user(user)
        if request.method == "DELETE":
            client.removeStoreProperties(props)
            DB.session.commit()
            return jsonify(message="Success.")
        propvals = client.getStoreProperties(0, props)
    respData = {}
    for propval in propvals:
        propname = PropTags.lookup(propval.tag).lower()
        if propval.tag & 0xFFFF == PropTypes.FILETIME:
            respData[propname] = datetime.fromtimestamp(nxTime(propval.val)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            respData[propname] = propval.val
    return jsonify(data=respData)


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/storeProps", methods=["PATCH"])
@secure(requireDB=True)
def setUserStoreProps(domainID, userID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import DB, Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    data = request.get_json(silent=True)
    if data is None or len(data) == 0:
        return jsonify(message="Missing data"), 400
    if user is None:
        return jsonify(message="User not found"), 404
    if not user.maildir:
        return jsonify(message="User has no store"), 400
    errors = {}
    propvals = []
    with Service("exmdb") as exmdb:
        for prop, val in data.items():
            try:
                tag = PropTags.deriveTag(prop)
            except ValueError:
                errors[prop] = "Unknown tag"
                continue
            try:
                val = PropTags.convertValue(tag, val)
            except ValueError:
                errors[prop] = "Invalid type"
                continue
            try:
                propvals.append(exmdb.TaggedPropval(tag, val))
            except TypeError:
                errors[prop] = "Unsupported type"
        client = exmdb.user(user)
        problems = client.setStoreProperties(0, propvals)
        for entry in problems:
            tag = PropTags.lookup(entry.proptag, hex(entry.proptag)).lower()
            err = ExchangeErrors.lookup(entry.err, hex(entry.err))
            errors[tag] = err
        user.properties = data
        DB.session.commit()
        if len(errors) != 0:
            API.logger.warn("Failed to set proptags: "+", ".join("{} ({})".format(tag, err) for tag, err in errors.items()))
        return jsonify(message="Great success!" if len(errors) == 0 else "Some tags could not be set", errors=errors)


def decodeSyncState(data, username):
    data = b64decode(data)
    if len(data) >= 2 and data[1] == ord(":"):
        API.logger.warning("Loading PHP serialize objects is deprecated")
        return loadPSO(data, decode_strings=True)["StateObject"][1]["devices"][username]["ASDevice"][1]
    elif len(data) >= 1 and data[0] == ord("{"):
        data = json.loads(data)["data"]
        if "devices" in data:
            data = data["devices"][username]["data"]
        return data
    return None


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/sync", methods=["GET"])
@secure(requireDB=True)
def getUserSyncData(domainID, userID):
    checkPermissions(DomainAdminROPermission(domainID))
    props = ("deviceid", "devicetype", "useragent", "deviceuser", "firstsynctime", "lastupdatetime", "asversion")
    from orm.users import DB, Users, UserDevices
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    with Service("exmdb") as exmdb:
        devices = {}
        client = exmdb.user(user)
        data = client.getSyncData(Config["sync"].get("syncStateFolder", "GS-SyncState"))
    for device, state in data.items():
        try:
            stateobj = decodeSyncState(state, user.username)
            if stateobj is None:
                continue
            syncstate = {prop: stateobj[prop] for prop in props}
            syncstate["foldersSyncable"] = len(stateobj["contentdata"])
            syncstate["foldersSynced"] = len([folder for folder in stateobj["contentdata"].values() if 1 in folder])
            syncstate["wipeStatus"] = 0
            devices[syncstate["deviceid"]] = syncstate
        except Exception as err:
            API.logger.warn("Failed to decode sync state: {}({})".format(type(err).__name__, ", ".join(str(arg) for arg in err.args)))
    if DB.minVersion(93):
        for device in UserDevices.query.filter(UserDevices.userID == userID)\
                                       .with_entities(UserDevices.deviceID, UserDevices.status):
            if device.deviceID in devices:
                devices[device.deviceID]["wipeStatus"] = device.status
            else:
                devices[device.deviceID] = {"deviceid": device.deviceID, "wipeStatus": device.status}
    return jsonify(data=tuple(devices.values()))


def getUsernamesFromFile(domainID, userID, name):
    checkPermissions(DomainAdminROPermission(domainID))
    from orm.users import Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID)\
                      .with_entities(Users.username, Users.maildir).first()
    if user is None:
        return jsonify(message="User not found"), 404
    try:
        with open(user.maildir+"/config/"+name+".txt", encoding="utf-8") as file:
            content = [line.strip() for line in file if line.strip() != ""]
    except (FileNotFoundError, PermissionError, TypeError):
        content = []
    return jsonify(data=content)


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/delegates", methods=["GET"])
@secure(requireDB=True)
def getUserDelegates(domainID, userID):
    return getUsernamesFromFile(domainID, userID, "delegates")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/sendas", methods=["GET"])
@secure(requireDB=True)
def getUserSendas(domainID, userID):
    return getUsernamesFromFile(domainID, userID, "sendas")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/sendass", methods=["GET"])
def sendAss(*args, **kwargs):
    from random import choices
    from flask import Response
    content = ("                          /\\          /\\\n                         ( \\\\        // )\n                     "
               "     \\ \\\\      // /\n                           \\_\\\\||||//_/\n                            \\/ _  _ \\\n "
               "                          \\/|(O)(O)|\n                          \\/ |      |\n      ___________________\\/  "
               "\\      /\n     //                //     |____|\n    //                ||     /      \\\n   //|               "
               " \\|     \\ 0  0 /\n  // \\       )         V    / \\____/\n //   \\     /        (     /\n     \\   /________"
               "_|  |_/\n       /  /\\   /     |  ||\n      /  / /  /      \\  ||\n      | |  | |        | ||\n      | |  | | "
               "       | ||\n      |_|  |_|        |_||\n       \\_\\  \\_\\        \\_\\\\\n",
               "⠄⠄⠸⣿⣿⢣⢶⣟⣿⣖⣿⣷⣻⣮⡿⣽⣿⣻⣖⣶⣤⣭⡉⠄⠄⠄⠄⠄\n⠄⠄⠄⢹⠣⣛⣣⣭⣭⣭⣁⡛⠻⢽⣿⣿⣿⣿⢻⣿⣿⣿⣽⡧⡄⠄⠄⠄\n⠄⠄⠄⠄⣼⣿⣿⣿⣿⣿⣿⣿⣿⣶⣌⡛⢿⣽⢘⣿⣷⣿⡻⠏⣛⣀⠄⠄\n⠄⠄⠄⣼⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⠙⡅"
               "⣿⠚⣡⣴⣿⣿⣿⡆⠄\n⠄⠄⣰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⠄⣱⣾⣿⣿⣿⣿⣿⣿⠄\n⠄⢀⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢸⣿⣿⣿⣿⣿⣿⣿⣿⠄\n⠄⣸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠣⣿⣿⣿⣿⣿⣿⣿⣿⣿⠄\n⠄⣿⣿⣿⣿⣿⣿⣿"
               "⣿⣿⣿⣿⣿⣿⠿⠛⠑⣿⣮⣝⣛⠿⠿⣿⣿⣿⣿⠄\n⢠⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⠄⠄⠄⠄⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⠄\n⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠇⠄⠄⠄⠄⢹⣿⣿⣿⣿⣿⣿⣿⣿⠁⠄\n⣸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠏⠄⠄⠄⠄⠄⠸⣿⣿⣿⣿⣿⡿⢟⣣⣀"
               "\n")
    return Response(choices(content, (10, 1)), headers={"Content-Type": "text/plain"})


def writeUsernamesToFile(domainID, userID, name):
    checkPermissions(DomainAdminPermission(domainID))
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify(message="Invalid or missing data"), 400
    for entry in data:
        if not formats.email.match(entry):
            return jsonify(message="Invalid {} e-mail '{}'".format(name, entry))
    from orm.users import Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID)\
                      .with_entities(Users.username, Users.maildir).first()
    if user is None:
        return jsonify(message="User not found"), 404
    try:
        filename = user.maildir+"/config/"+name+".txt"
        with open(filename, "w", encoding="utf-8") as file:
            file.write("\n".join(data)+"\n")
    except (FileNotFoundError, PermissionError) as err:
        return jsonify(message="Failed to write {}: {}".format(name, " - ".join(str(arg) for arg in err.args))), 500
    except TypeError:
        return jsonify(message="User does not support "+name), 400
    try:
        setDirectoryOwner(filename, Config["options"].get("fileUid"), Config["options"].get("fileGid"))
        setDirectoryPermission(filename, Config["options"].get("filePermissions"))
    except Exception:
        pass
    return jsonify(message=name.capitalize()+" updated")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/delegates", methods=["PUT"])
@secure(requireDB=True)
def setUserDelegates(domainID, userID):
    return writeUsernamesToFile(domainID, userID, "delegates")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/sendas", methods=["PUT"])
@secure(requireDB=True)
def setUserSendas(domainID, userID):
    return writeUsernamesToFile(domainID, userID, "sendas")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/sync/<deviceID>", methods=["DELETE"])
@secure(requireDB=True)
def removeDevice(domainID, userID, deviceID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    with Service("exmdb") as exmdb:
        client = exmdb.user(user)
        client.removeDevice(Config["sync"]["syncStateFolder"], deviceID)
    return jsonify(message="Success")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/sync", methods=["DELETE"])
@secure(requireDB=True)
def removeSyncStates(domainID, userID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    with Service("exmdb") as exmdb:
        client = exmdb.user(user)
        client.removeSyncStates(Config["sync"]["syncStateFolder"])
    return jsonify(message="Success")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/sync/<deviceID>/resync", methods=["PUT"])
@secure(requireDB=True)
def resyncDevice(domainID, userID, deviceID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    with Service("exmdb") as exmdb:
        client = exmdb.user(user)
        res = client.resyncDevice(Config["sync"]["syncStateFolder"], deviceID, userID)
        return jsonify(message="Great success" if res else "Success")


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/sync/<deviceID>/wipe", methods=["POST", "DELETE"])
@secure(requireDB=True, authLevel="user")
def setDeviceWipe(domainID, userID, deviceID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import DB, Users, UserDevices, UserDeviceHistory
    if not DB.minVersion(93):
        return jsonify(message="Database schema too old - please update to at least n93"), 503
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    device = UserDevices.query.filter(UserDevices.userID == userID, UserDevices.deviceID == deviceID).first()
    status = device.status if device is not None else 0
    if (status < 2 and request.method == "DELETE") or \
       (status >= 2 and request.method == "POST"):
        return jsonify(message="Nothing to to")
    if request.method == "DELETE":
        device.status = 1
        DB.session.add(UserDeviceHistory(dict(userDeviceID=device.ID, time=datetime.utcnow(), remoteIP=request.remote_addr,
                                              status=0)))
        DB.session.commit()
        return jsonify(message="Wipe canceled")
    data = request.get_json(silent=True) or {}
    if "password" not in data or not request.auth["user"].chkPw(data["password"]):
        return jsonify(message="User password required"), 403
    if device is None:
        device = UserDevices(dict(userID=userID, deviceID=deviceID, status=2))
        DB.session.add(device)
        DB.session.flush()
    device.status = 2
    DB.session.add(UserDeviceHistory(dict(userDeviceID=device.ID, time=datetime.utcnow(), remoteIP=request.remote_addr,
                                          status=2)))
    DB.session.commit()
    return jsonify(message="Device wipe requested.")


@API.route(api.BaseRoute+"/domains/<int:domainID>/syncPolicy", methods=["GET"])
@secure(requireDB=True, requireAuth="optional")
def getDomainSyncPolicy(domainID):
    checkPermissions(DomainAdminROPermission(domainID))
    from orm.domains import Domains
    domain = Domains.query.filter(Domains.ID == domainID).first()
    if domain is None:
        return jsonify(message="Domain not found"), 404
    if domain.syncPolicy is None:
        return jsonify(data=Config["sync"]["defaultPolicy"])
    policy = dict(Config["sync"]["defaultPolicy"])
    policy.update(domain.syncPolicy)
    return jsonify(data=policy)


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/storeAccess", methods=["POST", "PATCH"])
@secure(requireDB=True)
def setUserStoreAccess(domainID, userID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import Users, DB, UserSecondaryStores
    from sqlalchemy import insert
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    if user.maildir is None:
        return jsonify(message="User has no store"), 400
    data = request.get_json(silent=True)
    if data is None or "username" not in data:
        return jsonify(message="Invalid data"), 400
    primary = Users.query.with_entities(Users.ID).filter(Users.username == data["username"],
                                                         Users.domainID == domainID).first()
    if primary is None:
        return jsonify(message="Could not find user to grant access to"), 404
    eid = makeEidEx(0, PrivateFIDs.IPMSUBTREE)
    with Service("exmdb") as exmdb:
        client = exmdb.user(user)
        client.setFolderMember(eid, data["username"], Permissions.STOREOWNER)
    if DB.minVersion(91):
        DB.session.execute(insert(UserSecondaryStores).values(primary=primary, secondary=user.ID).prefix_with("IGNORE"))
        DB.session.commit()
    return jsonify(message="Success."), 201 if request.method == "POST" else 200


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/storeAccess", methods=["PUT"])
@secure(requireDB=True)
def setUserStoreAccessMulti(domainID, userID):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import Users, DB, UserSecondaryStores
    from sqlalchemy import insert
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    if user.maildir is None:
        return jsonify(message="User has no store"), 400
    data = request.get_json(silent=True)
    if data is None or "usernames" not in data:
        return jsonify(message="Invalid data"), 400
    primary = Users.query.filter(Users.username.in_(data["usernames"]), Users.domainID == domainID)\
                         .with_entities(Users.ID).all()
    eid = makeEidEx(0, PrivateFIDs.IPMSUBTREE)
    with Service("exmdb") as exmdb:
        client = exmdb.user(user)
        res = client.setFolderMembers(eid, data["usernames"], Permissions.STOREOWNER)
    if DB.minVersion(91):
        UserSecondaryStores.query.filter(UserSecondaryStores.secondaryID == user.ID).delete(synchronize_session=False)
        if len(primary):
            DB.session.execute(insert(UserSecondaryStores).values([{"primary": prim.ID, "secondary": user.ID}
                                                                   for prim in primary]))
        DB.session.commit()
    return jsonify(message="{} user{} updated".format(res, "" if res == 1 else "s"))


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/storeAccess", methods=["GET"])
@secure(requireDB=True)
def getUserStoreAccess(domainID, userID):
    checkPermissions(DomainAdminROPermission(domainID))
    from orm.users import Users
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    if user.maildir is None:
        return jsonify(message="User has no store"), 400
    with Service("exmdb") as exmdb:
        client = exmdb.user(user)
        memberList = exmdb.FolderMemberList(client.getFolderMemberList(makeEidEx(0, PrivateFIDs.IPMSUBTREE)))
        members = [{"ID": member.id, "displayName": member.name, "username": member.mail} for member in memberList.members
                   if member.rights & Permissions.STOREOWNER]
    return jsonify(data=members)


@API.route(api.BaseRoute+"/domains/<int:domainID>/users/<int:userID>/storeAccess/<username>", methods=["DELETE"])
@secure(requireDB=True)
def deleteUserStoreAccess(domainID, userID, username):
    checkPermissions(DomainAdminPermission(domainID))
    from orm.users import DB, Users, UserSecondaryStores
    user = Users.query.filter(Users.ID == userID, Users.domainID == domainID).first()
    if user is None:
        return jsonify(message="User not found"), 404
    if user.maildir is None:
        return jsonify(message="User has no store"), 400
    with Service("exmdb") as exmdb:
        client = exmdb.user(user)
        client.setFolderMember(makeEidEx(0, PrivateFIDs.IPMSUBTREE), username, Permissions.STOREOWNER, client.REMOVE)
    if DB.minVersion(91):
        primary = Users.query.with_entities(Users.ID).filter(Users.username == username).first()
        if primary is not None:
            UserSecondaryStores.query.filter(UserSecondaryStores.primaryID == primary.ID,
                                             UserSecondaryStores.secondaryID == user.ID).delete()
        DB.session.commit()
    return jsonify(message="Success")
