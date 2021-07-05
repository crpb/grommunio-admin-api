# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2020 grammm GmbH

from flask import Flask, jsonify, request, make_response

import yaml
from sqlalchemy.exc import DatabaseError
from functools import wraps
import traceback

from orm import DB
from tools.config import Config

import openapi_core
from openapi_core.shortcuts import RequestValidator, ResponseValidator
if openapi_core.__version__.split(".") < ["0", "13", "0"]:
    from openapi_core.wrappers.flask import FlaskOpenAPIRequest, FlaskOpenAPIResponse
else:
    from openapi_core.contrib.flask import FlaskOpenAPIRequest, FlaskOpenAPIResponse

from . import apiSpec


if "servers" in Config["openapi"]:
    apiSpec["servers"] += Config["openapi"]["servers"]
apiSpec = openapi_core.create_spec(apiSpec)
requestValidator, responseValidator = RequestValidator(apiSpec), ResponseValidator(apiSpec)


API = Flask("grammm Admin API")  # Core API object
API.config["JSON_SORT_KEYS"] = False  # Do not sort response fields. Crashes when returning lists...
if DB is not None:
    DB.enableFlask(API)

if not Config["openapi"]["validateRequest"]:
    API.logger.warning("Request validation is disabled!")
if not Config["openapi"]["validateResponse"]:
    API.logger.warning("Response validation is disabled!")


def validateRequest(flask_request):
    """Validate the request

    Parameters
    ----------
    flask_request: flask.request
        The request sent by flask

    Returns
    -------
    Boolean
        True if the request is valid, False otherwise
    string
        Error message if validation failed, None otherwise"""
    result = requestValidator.validate(FlaskOpenAPIRequest(flask_request))
    if result.errors:
        return False, jsonify(message="Bad Request", errors=[type(error).__name__ for error in result.errors]), result.errors
    return True, None, None


def secure(requireDB=False, requireAuth=True, authLevel="basic"):
    """Decorator securing API functions.

       Arguments:
           - requireDB (boolean)
               Whether the database is needed for the call. If set to True and the database is not configured,
               and error message is returned without invoking the endpoint.

       Automatically validates the request using the OpenAPI specification and returns a HTTP 400 to the client if validation
       fails. Also validates the response generated by the endpoint and returns a HTTP 500 on error. This behavior can be
       deactivated in the configuration.

       If an exception is raised during execution, a HTTP 500 message is returned to the client and a short description of the
       error is sent in the 'error' field of the response.
       """
    from .security import getSecurityContext
    from .errors import InsufficientPermissions
    def inner(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            def call():
                ret = func(*args, **kwargs)
                response = make_response(ret)
                try:
                    result = responseValidator.validate(FlaskOpenAPIRequest(request), FlaskOpenAPIResponse(response))
                except AttributeError:
                    result = None
                if result is not None and result.errors:
                    if Config["openapi"]["validateResponse"]:
                        API.logger.error("Response validation failed: "+str(result.errors))
                        return jsonify(message="The server generated an invalid response."), 500
                    else:
                        API.logger.warn("Response validation failed: "+str(result.errors))
                return ret

            if requireAuth:
                error = getSecurityContext(authLevel)
                if error is not None and requireAuth != "optional":
                    return jsonify(message="Access denied", error=error), 401
            valid, message, errors = validateRequest(request)
            if not valid:
                if Config["openapi"]["validateRequest"]:
                    API.logger.info("Request validation failed: {}".format(errors))
                    return message, 400
                else:
                    API.logger.warn("Request validation failed: {}".format(errors))

            if requireDB:
                if DB is None:
                    return jsonify(message="Database not available."), 503
            try:
                return call()
            except DatabaseError as err:
                API.logger.error("Database query failed: {}".format(err))
                return jsonify(message="Database error."), 503
            except InsufficientPermissions as err:
                return jsonify(message="Insufficient permissions for this operation"), 403
            except:
                API.logger.error(traceback.format_exc())
                return jsonify(message="The server encountered an error while processing the request."), 500
        return wrapper
    return inner


@API.after_request
def noCache(response):
    """Add no-cache headers to the response"""
    response.cache_control.no_cache = True
    response.cache_control.no_store = True
    response.cache_control.max_age = 1
    return response


from . import errors
