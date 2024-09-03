# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2020 grommunio GmbH

__all__ = ["domain", "system", "defaults", "misc", "service", "tasq"]

from flask import request, jsonify
from orm import DB
from tools.DataModel import MissingRequiredAttributeError, InvalidAttributeError, MismatchROError
from tools.misc import damerau_levenshtein_distance as dldist
import re

from sqlalchemy.exc import IntegrityError

matchStringRe = re.compile(r"([\w\-]*)")


def defaultListQuery(Model, filters=(), order=None, result="response", automatch=True, autofilter=True, autosort=True,
                     include_count="count", query=None):
    """Process a listing query for specified model.

    Automatically uses 'limit' (50), 'offset' (0) and 'level' (1) parameters from the request.

    The return value can be influenced by `result`: `list` will return a list ob objects, while the default `response`
    will return the complete JSON encoded flask response.

    If `automatch` is enabled, the results are filtered by prefix-matching each word against the configured columns. If no
    other sorting is active (`order` is None and no "sort" query parameter is given), the results are ranked by the
    Damerau-Levenshtein distance to the search term. Note that ranking is done after the query and a low `limit` parameter
    may prevent a good match from being selected at all.

    Parameters
    ----------
    Model : SQLAlchemy model with DataModel extension
        Model to perform the query on
    filters : iterable, optional
        A list of filter expressions to apply to the query. The default is ().
    order : list or Column, optional
        Column(s) to use in an order_by expression. The default is None.
    result : str, optional
        Return type.
    automatch : str, optional
        Name of the column to match against.
    autofilter : list of str, optional
        Whether to apply autofiltering. See DataModel.autofilter for more information. Default is True.
    autosort: boolean, optional
        Whether to apply autosorting. See DataModel.autosort for more information. Default is True.
    include_count: str, optional
        Name of the property containing the total number of results (regardless of limit) or None to disable.
        Default is "count".
    query: BaseQuery, optional
        Specify a base query to build upon. Default is None.
    Returns
    -------
    Response
        Flask response containing the list data.
    """
    limit = request.args.get("limit", "50")
    if len(limit) == 0:
        limit = None
    offset = request.args.get("offset", "0")
    if len(offset) == 0:
        offset = None
    verbosity = int(request.args.get("level", 1))
    query = (Model.optimized_query(verbosity) if query is None else Model.optimize_query(query, verbosity)).filter(*filters)
    if autosort:
        query = Model.autosort(query, request.args.getlist("sort"))
    if order is not None:
        query = query.order_by(*(order if type(order) in (list, tuple) else (order,)))
    if autofilter:
        query = Model.autofilter(query, request.args)
    if automatch and "match" in request.args:
        matchStr = request.args["match"].lower()
        fields = set(request.args["matchFields"].split(",")) if "matchFields" in request.args else None
        query = Model.automatch(query, request.args["match"], fields)
    count = query.count() if include_count else None
    if result == "query":
        return query, limit, offset, count
    query = query.limit(limit).offset(offset)
    objects = query.all()
    if order is None and "sort" not in request.args and automatch and "match" in request.args:
        scored = ((min(dldist(str(field).lower(), matchStr) for field in obj.matchvalues(fields) if field is not None), obj)
                  for obj in objects)
        objects = [so[1] for so in sorted(scored, key=lambda entry: entry[0])]
    if result == "list":
        return objects
    data = [obj.todict(verbosity) for obj in objects]
    if result == "data":
        return data
    resp = dict(data=data)
    if include_count:
        resp[include_count] = count
    return jsonify(resp)


def defaultDetailQuery(Model, ID, errName, filters=()):
    """Process a detail query for specified model.

    Automatically uses 'level' (2) parameter from the request.
    Returns a 404 error response if no object with the given ID is found.

    Parameters
    ----------
    Model : SQLAlchemy model with DataModel extension
        Model to perform the query on.
    ID : int
        ID of the object.
    errName : str
        Object name to use in error messages.

    Returns
    -------
    Response
        Flask response containing the object data or an error message.
    """
    verbosity = request.args.get("level", 2)
    query = Model.query.filter(Model.ID == ID, *filters)
    query = Model.optimize_query(query, verbosity)
    obj = query.first()
    if obj is None:
        return jsonify(message=errName+" not found"), 404
    return jsonify(obj.todict(verbosity))


def defaultPatch(Model, ID, errName, obj=None, filters=(), result="response"):
    """Process a PATCH query for specified model.

    Performs an autopatch() call on the model.
    Returns a 404 error response if no object with the given ID is found.

    Parameters
    ----------
    Model : SQLAlchemy model with DataModel extension
        Model to perform the query on.
    ID : int
        ID of the object.
    errName : str
        Object name to use in error messages.
    obj : SQLAlchemy model instance, optional
        Object to patch (suppresses object retrieval query). The default is None.
    response: str
        Return value. "precommit" returns the patched object before committing the changes. Other values return the response.

    Returns
    -------
    <varies>
        Return value according to `result`
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify(message="Could not update: no valid JSON data"), 400
    if obj is None:
        obj = Model.query.filter(Model.ID == ID, *filters).first()
    if obj is None:
        return jsonify(message=errName+" not found"), 404
    try:
        obj.fromdict(data)
    except (InvalidAttributeError, MismatchROError, ValueError) as err:
        DB.session.rollback()
        return jsonify(message=err.args[0]), 400
    if result == "precommit":
        return obj
    try:
        DB.session.commit()
    except IntegrityError as err:
        DB.session.rollback()
        return jsonify(message="Could not update: invalid data", error=err.orig.args[1]), 400
    return jsonify(Model.optimized_query(2).filter(Model.ID == ID).first().fulldesc())


def defaultCreate(Model, result="response"):
    """Create a new object of the specified model.

    Performs a check on the input data, calls Model ctor and tries to insert the object into the database.
    Catches the following errors an returns an appropriate error message with HTTP 400 code:
        - The request does not contain a valid JSON object
        - Parameter check fails
        - Ctor raises a MissingRequiredAttributeError
        - Database commit raises an IntegrityError

    ParametersDefault
    ----------
    Model : SQLAlchemy model with DataModel extension
        Model to create a new instance from

    Returns
    -------
    Response
        Flask response containing the new object data or an error message.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify(message="Invalid JSON object"), 400
    error = Model.checkCreateParams(data)
    if error is not None:
        return jsonify(message=error), 400
    try:
        created = Model(props=data)
    except MissingRequiredAttributeError as err:
        return jsonify(message=err.args[0]), 400
    except (InvalidAttributeError, MismatchROError, ValueError) as err:
        return jsonify(message=err.args[0]), 400
    if result == "object":
        return created
    DB.session.add(created)
    try:
        DB.session.commit()
    except IntegrityError as err:
        DB.session.rollback()
        return jsonify(message="Object violates database constraints", error=err.orig.args[1]), 400
    ID = created.ID
    return jsonify(Model.optimized_query(2).filter(Model.ID == ID).first().fulldesc()), 201


def defaultDelete(Model, ID, name, filters=()):
    """Delete instance with specified ID from the model.

    If no object with the ID exists, a HTTP 404 error is returned.
    If deletion of the object would violate database constraints, a HTTP 400 error is returned.

    Parameters
    ----------
    Model : SQLAlchemy model with DataModel extension
        Model to delete from.
    ID : int
        ID of the object to delete.
    name : str
        Object name to use in messages.

    Returns
    -------
    Response
        Flask response containing the new object data or an error message.
    """
    obj = Model.query.filter(Model.ID == ID, *filters).first()
    if obj is None:
        return jsonify(message=name+" not found"), 404
    try:
        DB.session.delete(obj)
        DB.session.commit()
    except IntegrityError as err:
        return jsonify(message="Deletion violates database constraints.", error=err.args[0]), 400
    return jsonify(message="{} #{} deleted.".format(name, ID))


def defaultBatchDelete(Model, filters=()):
    """Delete a list of instances.

    If an ID is not found, it is ignored.
    If deletion of the object would violate database constraints, a HTTP 400 error is returned.

    Parameters
    ----------
    Model : SQLAlchemy model with DataModel extension
        Model to delete from.

    Returns
    -------
    Response
        Flask response containing the new object data or an error message.
    """
    if "ID" not in request.args:
        return jsonify(message="Missing ID list"), 400
    IDs = request.args["ID"].split(",")
    objs = Model.query.filter(Model.ID.in_(IDs), *filters).all()
    IDs = [obj.ID for obj in objs]
    try:
        for obj in objs:
            DB.session.delete(obj)
        DB.session.commit()
    except IntegrityError as err:
        return jsonify(message="Object deletion would violate database constraints", error=err.args[0]), 400
    return jsonify(message="Delete successful.", deleted=IDs)


def defaultListHandler(Model, filters=(), order=None, result="response", automatch=True, autofilter=True, autosort=True,
                       include_count="count", query=None):
    """Handle operations on lists.

    Handles list (GET), create (POST) and batch delete (DELETE) requests for the given model.
    Automatically delegates to appropriate default function according to request method.

    Parameters
    ----------
    Model : SQLAlchemy model with DataModel extension
        Model to perform the query on
    filters : iterable, optional
        A list of filter expressions to apply to the query. Only applicable for GET requests. The default is None.
    order : list or Column, optional
        Column(s) to use in an order_by expression. Only applicable for GET requests. The default is None.
    result : str, optional
        Return type. See defaultListQuery for more detail. Default is "response"
    automatch : bool, optional
        Whether to apply automatching. See defaultListQuery for more detail.
    autofilter : boolean, optional
        Whether to apply autofiltering. See DataModel.autofilter for more information. Default is True.
    autosort: boolean, optional
        Whether to apply autosorting. See DataModel.autosort for more information. Default is True.
    include_count: str, optional
        Forwarded to defaultListQuery. Default is "count"
    query: BaseQuery, optional
        Base query forwarded to defaultListQuery. Default is None.
    Returns
    -------
    Response
        Flask response containing data or error message.
    """
    if request.method == "GET":
        return defaultListQuery(Model, filters, order, result, automatch, autofilter, autosort, include_count, query)
    elif request.method == "POST":
        return defaultCreate(Model, result)
    elif request.method == "DELETE":
        return defaultBatchDelete(Model, filters)


def defaultObjectHandler(Model, ID, name, filters=()):
    """Handle operations on objects.

    Handles detail (GET), update (PATCH) or delete (DELETE) requests.
    Automatically delegates to appropriate default function according to request method.

    Parameters
    ----------
    Model : SQLAlchemy model with DataModel extension
        Model to perform query on.
    ID : int
        ID of the object to operate on.
    name : str
        Object name to use in messages.

    Returns
    -------
    Response
        Flask response containing data or error message.
    """
    if request.method == "GET":
        return defaultDetailQuery(Model, ID, name, filters)
    elif request.method == "PATCH":
        return defaultPatch(Model, ID, name, None, filters)
    elif request.method == "DELETE":
        return defaultDelete(Model, ID, name, filters)


def userQuery(domainID=None):
    """Query users.

    Parameters
    ----------
    domainID : int, optional
        Filter by domain ID. The default is None.

    Returns
    -------
    Response
        JSON response containing user data
    """
    from sqlalchemy import or_, String
    from sqlalchemy.orm import aliased
    from orm.users import Users, UserProperties
    from tools.constants import PropTags
    from tools.DataModel import DataModel
    from tools.misc import createMapping

    Users._init()
    verbosity = int(request.args.get("level", 1))
    filters = (Users.domainID == domainID,) if domainID is not None else ()
    filters += (Users.ID > 0,)
    query, limit, offset, _ = defaultListHandler(Users, filters=filters, result="query", include_count=None, automatch=False)
    sorts = request.args.getlist("sort")
    for s in sorts:
        sprop, sorder = s.split(",", 1) if "," in s else (s, "asc")
        if hasattr(PropTags, sprop.upper()):
            up = aliased(UserProperties)
            query = query.join(up, (up.userID == Users.ID) & (up.tag == getattr(PropTags, sprop.upper())))\
                         .order_by(up._propvalstr.desc() if sorder == "desc" else up._propvalstr.asc())

    if "match" in request.args:
        expr = request.args["match"]
        fields = set(request.args["matchFields"].split(",")) if "matchFields" in request.args else None
        isUnicode = any(ord(c) > 127 for c in expr)
        matchexpr = tuple("%"+substr+"%" for substr in expr.split())
        matchables = Users._meta.matchables if fields is None else (m for m in Users._meta.matchables if m.alias in fields)
        targets = []
        for prop in matchables:
            column, query = prop.resolve(Users, query)
            if not (isUnicode and isinstance(column.type, String) and column.type.charset == "ascii"):
                targets.append((prop, column))
        if "matchProps" in request.args:
            metaProp = DataModel.Prop(None)
            for prop in request.args["matchProps"].split(","):
                if hasattr(PropTags, prop.upper()):
                    up = aliased(UserProperties)
                    query = query.outerjoin(up, (up.userID == Users.ID) & (up.tag == getattr(PropTags, prop.upper())))
                    targets.append((metaProp, up._propvalstr))
        filters = [column.ilike(match) for match in matchexpr for prop, column in targets if prop.match == "default"] +\
                  [column == prop.tf(expr) for prop, column in targets if prop.match == "exact" and prop.tf(expr) is not None]
        query = query.filter(or_(filter for filter in filters) if filters else False).reset_joinpoint()

    if "filterProp" in request.args:
        for filter in request.args["filterProp"].split(";"):
            prop, value = filter.split(":")
            try:
                up = aliased(UserProperties)
                query = query.outerjoin(up, (up.userID == Users.ID) & (up.tag == PropTags.deriveTag(prop)))\
                             .filter(up._propvalstr == value if "," not in value else up._propvalstr.in_(value.split(",")))
            except ValueError:
                return jsonify(message=f"Unknown user property '{prop}'"), 400

    count = query.count()
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
