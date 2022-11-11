# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2021 grommunio GmbH

from flask import request, jsonify
from sqlalchemy.exc import IntegrityError

from .. import defaultListHandler, defaultObjectHandler, defaultPatch

import api
from api.core import API, secure
from api.security import checkPermissions

from services import ServiceHub, Service
from services.ldap import LdapService

from tools.permissions import SystemAdminPermission, SystemAdminROPermission
from tools.permissions import DomainAdminROPermission, OrgAdminPermission, DomainPurgePermission

from orm import DB


@API.route(api.BaseRoute+"/system/orgs", methods=["GET", "POST"])
@secure(requireDB=True)
def orgListEndpoint():
    checkPermissions(SystemAdminROPermission() if request.method == "GET" else SystemAdminPermission())
    from orm.domains import Orgs
    return defaultListHandler(Orgs)


@API.route(api.BaseRoute+"/system/orgs/<int:ID>", methods=["GET", "PATCH"])
@secure(requireDB=True)
def orgObjectEndpoint(ID):
    checkPermissions(SystemAdminROPermission() if request.method == "GET" else SystemAdminPermission())
    from orm.domains import Orgs
    return defaultObjectHandler(Orgs, ID, "Organization")


@API.route(api.BaseRoute+"/system/orgs/<int:ID>", methods=["DELETE"])
@secure(requireDB=True)
def orgDeleteEndpoint(ID):
    checkPermissions(SystemAdminPermission())
    from orm.domains import Domains, Orgs
    Domains.query.filter(Domains.orgID == ID).update({Domains.orgID: 0}, synchronize_session=False)
    return defaultObjectHandler(Orgs, ID, "Organization")


###################################################################################################

@API.route(api.BaseRoute+"/system/orgs/<int:ID>/ldap", methods=["GET"])
@secure(requireDB=109)
def getOrgLdapConfig(ID):
    checkPermissions(OrgAdminPermission(ID))
    from orm.domains import OrgParam
    config = OrgParam.loadLdap(ID) or {}
    return jsonify(ldapAvailable=Service.available("ldap", ID) if config else False, data=config)


@API.route(api.BaseRoute+"/system/orgs/<int:ID>/ldap", methods=["PUT"])
@secure(requireDB=109)
def updateOrgLdapConfig(ID):
    checkPermissions(OrgAdminPermission(ID))
    data = request.get_json(silent=True)
    if data is None:
        return jsonify(message="Missing configuration"), 400
    error = LdapService.testConfig(data)
    forced = False
    if error:
        if request.args.get("force") == "true":
            forced = True
        else:
            return jsonify(message=error), 400
    from orm.domains import OrgParam
    OrgParam.saveLdap(ID, data)
    ServiceHub.load("ldap", ID, force_reload=True)
    return jsonify(message="Force updated LDAP configuration" if forced else "LDAP configuration updated")


@API.route(api.BaseRoute+"/system/orgs/<int:ID>/ldap", methods=["DELETE"])
@secure(requireDB=109)
def deleteOrgLdapConfig(ID):
    checkPermissions(OrgAdminPermission(ID))
    from orm.domains import OrgParam
    OrgParam.wipeLdap(ID)
    ServiceHub.load("ldap", ID, force_reload=True)
    return jsonify(message="Success.")

###################################################################################################

@API.route(api.BaseRoute+"/system/domains", methods=["GET"])
@secure(requireDB=True)
def domainListEndpoint():
    checkPermissions(SystemAdminROPermission())
    from orm.domains import Domains
    return defaultListHandler(Domains)


@API.route(api.BaseRoute+"/system/domains", methods=["POST"])
@secure(requireDB=True)
def domainCreate():
    checkPermissions(SystemAdminPermission())
    from orm.domains import Domains
    data = request.get_json(silent=True)
    if data is None:
        return jsonify(message="Missing data"), 400
    if SystemAdminPermission not in request.auth["user"].permissions():
        data.pop("homeserver", None)
    result, code = Domains.create(data, request.args.get("createRole", "false") == "true")
    if code != 201:
        return jsonify(message=result), code
    return jsonify(result.fulldesc()), 201


@API.route(api.BaseRoute+"/system/domains/<int:domainID>", methods=["GET"])
@secure(requireDB=True)
def getDomain(domainID):
    checkPermissions(DomainAdminROPermission(domainID))
    from orm.domains import Domains
    return defaultObjectHandler(Domains, domainID, "Domain")


@API.route(api.BaseRoute+"/system/domains/<int:domainID>", methods=["PATCH"])
@secure(requireDB=True)
def updateDomain(domainID):
    checkPermissions(OrgAdminPermission("*"))
    from orm.domains import Domains
    from orm.users import Users
    domain: Domains = Domains.query.filter(Domains.ID == domainID).first()
    if domain is None:
        return jsonify(message="Domain not found"), 404
    checkPermissions(OrgAdminPermission(domain.orgID))
    oldStatus = domain.domainStatus
    patched = defaultPatch(Domains, domainID, "Domain", obj=domain, result="precommit")
    if isinstance(patched, tuple):  # Return value is not the domain, but an error response
        return patched
    if oldStatus != domain.domainStatus:
        Users.query.filter(Users.domainID == domainID)\
                   .update({Users.addressStatus: Users.addressStatus.op("&")(0xF)+(domain.domainStatus << 4)},
                           synchronize_session=False)
    try:
        DB.session.commit()
    except IntegrityError as err:
        DB.session.rollback()
        return jsonify(message="Domain update failed", error=err.orig.args[1])
    return jsonify(domain.fulldesc())


@API.route(api.BaseRoute+"/system/domains/<int:domainID>", methods=["DELETE"])
@secure(requireDB=True)
def deleteDomain(domainID):
    checkPermissions(OrgAdminPermission("*"))
    from orm.domains import Domains
    domain = Domains.query.filter(Domains.ID == domainID).first()
    if domain is None:
        return jsonify(message="Domain not found"), 404
    checkPermissions(OrgAdminPermission(domain.orgID))
    if request.args.get("purge") == "true":
        checkPermissions(DomainPurgePermission())
        domain.purge(request.args.get("deleteFiles") == "true")
        msg = "removed."
    else:
        domain.delete()
        msg = "marked as deleted."
    DB.session.commit()
    return jsonify(message="Domain "+msg)
