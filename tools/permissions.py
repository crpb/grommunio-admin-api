# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2020 grommunio GmbH

class Permissions:
    """Central Permissions class.

    Functions as a permission factory and provides easy permission checking.
    """

    preg = {}
    pregr = {}

    def __init__(self, *args):
        """Initialize permission object.

        Parameters
        ----------
        *args : Permission
            Permissions held by the object
        """
        self.permissions = args

    @classmethod
    def fromDB(cls, permissionsData=[]):
        """Initialize from database objects.

        Parameters
        ----------
        permissionsData : Iterable, optional
            List of objects with `name` and `param` attributes. The default is [].

        Returns
        -------
        Permissions
            Permissions object with permissions loaded from database
        """
        return Permissions(*(cls.preg[pData.permission](pData.params)
                             for pData in permissionsData if pData.permission in cls.preg))

    @classmethod
    def dump(cls, permission):
        """Create a permission representation that can be loaded with `load`.

        Parameters
        ----------
        permission : PermissionBase
            Permission to serialize

        Returns
        -------
        str
            String representation or None if serializaiton fails
        """
        if permission is None:
            return None
        try:
            import json
            data = {"permission": cls.pregr[permission] if type(permission) == type else cls.pregr[type(permission)]}
            if type(permission) != type and permission.params is not None:
                data["params"] = permission.params
            return json.dumps(data, separators=(",", ":"))
        except Exception:
            return None

    @classmethod
    def load(cls, permission=None, default=None):
        """Load a permission object.

        If permission is None, the return value is None, regardless of the default.

        Parameters
        ----------
        permission: str, optional
            Permission data, as created by dump(). The default is None.
        default : PermissionBase, optional
            Default permission if loading fails. The default is None.

        Returns
        -------
        PermissionBase
            A single permission constructed from the serialization
        """
        if permission is None:
            return
        try:
            import json
            data = json.loads(permission)
            return cls.preg[data["permission"]](data.get("params"))
        except Exception:
            return None

    def has(self, permission):
        """
        Check if permission is represented by permissions object.

        Parameters
        ----------
        permission : Permission
            Requested permission

        Returns
        -------
        bool
            True if the requested permission is represented, False otherwise
        """
        return permission is None or any(perm.permits(permission) for perm in self.permissions)

    def __contains__(self, permission):
        """Convenience alias for `has`.

        Parameters
        ----------
        permission : Permission
            Requested permission

        Returns
        -------
        bool
            True if the requested permission is represented, False otherwise
        """
        return self.has(permission)

    def __iter__(self):
        """Return permission iterator

        Returns
        -------
        iterator
            Iterator that iterates over the contained permission objects.
        """
        return self.permissions.__iter__()

    @classmethod
    def register(cls, name):
        """Class decorator to register a permission at the factory.

        Parameters
        ----------
        name : str
            Name of the permission

        Returns
        -------
        function
            Decorator function
        """
        def inner(obj):
            cls.preg[name] = obj
            cls.pregr[obj] = name
            return obj
        return inner

    @classmethod
    def knownPermissions(cls):
        """List names of registered permissions.

        Returns
        -------
        tuple
            List of registered permissions
        """
        return tuple(cls.preg.keys())

    @classmethod
    def create(cls, name, params=None):
        """Create permission by name.

        Parameters
        ----------
        name : str
            Name of the permission
        params : Any, optional
            Parameters passed to the permission. The default is None.

        Raises
        ------
        KeyError
            No permission with this name exists

        Returns
        -------
        Permission
            New permission.
        """
        if name not in cls.preg:
            raise KeyError("Unknown permission '{}'".format(name))
        return cls.preg[name](params)

    @staticmethod
    def sysadmin():
        """Create Permissions object with system admin permissions.

        Returns
        -------
        Permissions
            Permissions object with system admin permissions.
        """
        return Permissions(SystemAdminPermission())

    def capabilities(self):
        """Return set of capabilities from all represented permissions.

        Returns
        -------
        set
            Union of capabilities from all permissions
        """
        return set.union(*(permission.capabilities() for permission in self.permissions))


class PermissionBase:
    """Base class for permissions.

    Implements `permits` method, automatically dispatching the correct, permission specific, `_permits` method.
    """

    def __init__(self, *args, **kwargs):
        """Default constructor."""
        pass

    def permits(self, permission):
        """Check if `permission` is represented by the object.

        Checks if self is an instance of `permission` and, if so, dispatches the `_permits` method of the correct base class.

        Parameters
        ----------
        permission : PermissionBase
            Permission to check for.

        Returns
        -------
        bool
            True if `permission` is represented by this object, False otherwise
        """
        permission_t = type(permission)
        if type(self) == permission_t:
            self._permits(permission)
        if isinstance(self, permission_t):
            return permission_t._permits(self, permission)
        return False

    def _permits(self, permission):
        """Check if self contains requeusted permission.

        Called by the default `permits` method if `permission` and self are of the same type.
        By default, having the permission is sufficient, but it may be overridden to check permission parameters.

        Parameters
        ----------
        permission : same as type(self)
            Requested permission

        Returns
        -------
        bool:
            Whether permission matches
        """
        return True

    @classmethod
    def capabilities(cls):
        """Get a set of capabilities provided by this permission.

        Returns
        -------
        set
            Empty set
        """
        return set()

    def __repr__(self):
        """String representation.

        Generic implementation providing class name with appended braces.

        Returns
        -------
        str
            String representation
        """
        return type(self).__name__+"()"

    @property
    def params(self):
        """Parameters relevant for the permission."""
        return None


@Permissions.register("SystemAdmin")
class SystemAdminPermission:
    """System admin permission.

    Permits every action by default.
    """

    __capcache = None

    def __init__(self, *args, **kwargs):
        """Initialize permission.

        Parameters
        ----------
        *args : Any
            Ignored.
        **kwargs : Any
            Ignored.
        """
        pass

    def permits(self, permission):
        """Return True.

        Parameters
        ----------
        permission : PermissionBase
            Permission to check

        Returns
        -------
        bool
            Always True
        """
        return True

    def __repr__(self):
        """Return string representation."""
        return "SystemAdminPermission()"

    @classmethod
    def capabilities(cls):
        """Get a set of capabilities provided by this permission.

        Returns
        -------
        set
            Set containing all known capabilities.
        """
        if cls.__capcache is None:
            cls.__capcache = {"SystemAdminWrite"}
            for permission in Permissions.preg.values():
                cls.__capcache |= permission.capabilities()
        return cls.__capcache

    @property
    def params(self):
        """Parameters relevant for the permission."""
        return None


@Permissions.register("ResetPasswd")
class ResetPasswdPermission(PermissionBase):
    """Permission class representing the permission to reset any users's password.

    Currently only acts as system-wide permission. Domain or organization granularity may be added in the future.
    """
    @classmethod
    def capabilities(cls):
        """Get a set of capabilities provided by this permission.

        Returns
        -------
        set
            Set containing "ResetPasswd" capability.
        """
        return {"ResetPasswd"} | super().capabilities()


@Permissions.register("DomainAdminRO")
class DomainAdminROPermission(PermissionBase):
    """Permission class representing read only permissions for a domain.

    Can represent permission for a specific domain, or domains in general (when parameter is '*').

    Note that the special parameter '*' is permissive in both directions:
    Requesting a DomainAdminPermission with parameter '*' and
    requesting DomainAdminPermission for a specific domain from a permission with parameter '*' will both return True.
    """

    def __init__(self, domainID):
        """Initialize domain admin permission.

        Parameters
        ----------
        domainID : int or '*'
            Domain ID this permission is for, or '*' to match all domains

        Raises
        ------
        ValueError
            `domainID` is neither an integer nor special identifier '*'
        """
        if domainID != "*" and not isinstance(domainID, int):
            raise ValueError("DomainAdminROPermission parameter must be integer or '*'")
        self.__domain = domainID

    def _permits(self, permission):
        """Check if permission is represented.

        Parameters
        ----------
        permission : DomainAdminPermission
            Permission to check for equality

        Returns
        -------
        bool
            True if domain IDs match or either is a wildcard domain, False otherwise
        """
        return "*" in (self.__domain, permission.__domain) or self.__domain == permission.__domain

    def __repr__(self):
        """Return string representation."""
        return "DomainAdminROPermission({})".format(repr(self.__domain))

    @classmethod
    def capabilities(cls):
        """Get a set of capabilities provided by this permission.

        Returns
        -------
        set
            Set containing "DomainAdmin" capability.
        """
        return {"DomainAdminRead"} | super().capabilities()

    @property
    def domainID(self):
        """Return domain parameter."""
        return self.__domain

    @property
    def params(self):
        """Parameters relevant for the permission."""
        return self.__domain


@Permissions.register("DomainAdmin")
class DomainAdminPermission(DomainAdminROPermission, ResetPasswdPermission):
    """Permission class representing admin permissions for a domain.

    Can represent permission for a specific domain, or domains in general (when parameter is '*').

    Note that the special parameter '*' is permissive in both directions:
    Requesting a DomainAdminPermission with parameter '*' and
    requesting DomainAdminPermission for a specific domain from a permission with parameter '*' will both return True.
    """

    def __init__(self, domainID):
        """Initialize domain admin permission.

        Parameters
        ----------
        domainID : int or '*'
            Domain ID this permission is for, or '*' to match all domains

        Raises
        ------
        ValueError
            `domainID` is neither an integer nor special identifier '*'
        """
        if domainID != "*" and not isinstance(domainID, int):
            raise ValueError("DomainAdminPermission parameter must be integer or '*'")
        DomainAdminROPermission.__init__(self, domainID)

    def __repr__(self):
        """Return string representation."""
        return "DomainAdminPermission({})".format(repr(self.domainID))

    @classmethod
    def capabilities(cls):
        """Get a set of capabilities provided by this permission.

        Returns
        -------
        set
            Set containing "DomainAdmin" capability.
        """
        return {"DomainAdminWrite"} | super().capabilities()


@Permissions.register("SystemAdminRO")
class SystemAdminROPermission(DomainAdminROPermission):
    """Permission class representing read-only system admin permissions.

    The read-only system admin has access to all the data a normal system admin has,
    but cannot modify anything.
    """

    def __init__(self, *args, **kwargs):
        """Initialize permission.

        Parameters
        ----------
        *args : Any
            Ignored.
        **kwargs : Any
            Ignored.
        """
        DomainAdminROPermission.__init__(self, "*")

    def __repr__(self):
        """Return string representation."""
        return "SystemAdminROPermission()"

    @classmethod
    def capabilities(cls):
        """Get a set of capabilities provided by the permission.

        Returns
        -------
        set
            Set containing "SystemAdminRO" and "DomainAdminRO" capabilities.
        """
        return {"SystemAdminRead"} | super().capabilities()

    @property
    def params(self):
        """Parameters relevant for the permission."""
        return None


@Permissions.register("OrgAdmin")
class OrgAdminPermission(ResetPasswdPermission):
    """Permission class representing admin permissions for an organization.

    An organization admin automatically has DomainAdminPermission for each domain belonging to an organization.
    Additionally, an organization admin can modify and delete domains.

    Can represent permission for a specific organization, or organizations in general (when parameter is '*').

    Note that the special parameter '*' is permissive in both directions:
    Requesting a DomainAdminPermission with parameter '*' and
    requesting DomainAdminPermission for a specific domain from a permission with parameter '*' will both return True.
    """

    def __init__(self, orgID):
        """Initialize domain admin permission.

        Parameters
        ----------
        orgID : int or '*'
            Organization ID this permission is for, or '*' to match all domains

        Raises
        ------
        ValueError
            `orgID` is neither an integer nor special identifier '*'
        """
        if orgID != "*" and not isinstance(orgID, int):
            raise ValueError("OrgAdminPermission parameter must be integer or '*'")
        self.__org = orgID

    def permits(self, permission):
        """Check if `permission` is represented.


        Returns
        -------
        bool
            True if `permission` is represented by this object, False otherwise
        """
        if isinstance(permission, OrgAdminPermission):
            return self._permits(permission)
        # `isinstance()` does not compare the inheritance of DAP and DA-RO-P properly
        if isinstance(permission, DomainAdminPermission) or isinstance(permission, DomainAdminROPermission):
            if permission.domainID == "*" or self.__org == "*":
                return True
            from orm.domains import Domains
            domainIDs = (d.ID for d in Domains.query.filter(Domains.orgID == self.__org).with_entities(Domains.ID).all())
            return permission.domainID in domainIDs
        return PermissionBase.permits(self, permission)

    def _permits(self, permission):
        """Check if permission is represented.

        Parameters
        ----------
        permission : OrgAdminPermission
            Permission to check for equality

        Returns
        -------
        bool
            True if domain IDs match or either is a wildcard organization, False otherwise
        """
        return "*" in (self.__org, permission.__org) or self.__org == permission.__org

    def __repr__(self):
        """Return string representation."""
        return "OrgAdminPermission({})".format(repr(self.__org))

    @classmethod
    def capabilities(cls):
        """Get a set of capabilities provided by this permission.

        Returns
        -------
        set
            Set containing "DomainAdmin" and "OrgAdmin" capabilities.
        """
        return {"DomainAdminRead", "DomainAdminWrite", "OrgAdmin"} | super().capabilities()

    @property
    def orgID(self):
        """Return domain parameter."""
        return self.__org

    @property
    def params(self):
        """Parameters relevant for the permission."""
        return self.__org


@Permissions.register("DomainPurge")
class DomainPurgePermission(PermissionBase):
    """Permission to purge domains.

    Does not grant permission to delete a domain on its own and is only effective if combined with an OrgAdmin permission.
    """
    @classmethod
    def capabilities(cls):
        """Get a set of capabilities provided by this permission.

        Returns
        -------
        set
            Set containing "DomainPurge" capability.
        """
        return {"DomainPurge"} | super().capabilities()
