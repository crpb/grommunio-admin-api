..
	SPDX-License-Identifier: CC-BY-SA-4.0 or-later
	SPDX-FileCopyrightText: 2021-2022 grommunio GmbH

=========================
grommunio-admin-domain(1)
=========================

Name
====

grommunio-admin domain — Domain management

Synopsis
========

| **grommunio-admin domain** **create** [*--create-role*] [*--homeserver HOMESERVER*]
  [*--no-defaults*] [*--skip-adaptor-reload*] [*<FIELDS>*] *-u MAXUSER* *DOMAINNAME*
| **grommunio-admin domain** **delete** *DOMAINSPEC*
| **grommunio-admin domain** **list** [*-f FIELD=<value>*] [*-s FIELD*]
  [*DOMAINSPEC*]
| **grommunio-admin domain** **modify** [*<FIELDS>*] *DOMAINSPEC*
| **grommunio-admin domain** **purge** [*--files*] [*-y*] *DOMAINSPEC*
| **grommunio-admin domain** **query** [*-f ATTRIBUTE=<value>*] [*--format FORMAT*]
  [*--separator SEPARATOR*] [*-s FIELD*] [*ATTRIBUTE* …]
| **grommunio-admin domain** **recover** *DOMAINSPEC*
| **grommunio-admin domain** **show** [*-f FIELD=<value>*] [*-s FIELD*]
  *DOMAINSPEC*

Description
===========

Subcommand to show and manipulate domains.

Commands
========

``create``
   Create a new domain
``delete``
   Soft-delete a domain
``list``
   List domains
``modify``
   Modify domain
``purge``
   Permanently delete domain
``query``
   Query domain attributes
``recover``
   Recover a soft-deleted domain
``show``
   Show detailed information about a domain

Options
=======

``ATTRIBUTE``
   Attributes to query. Available attributes are *ID*, *activeUsers*,
   *address*, *adminName*, *chat*, *displayname*, *domainStatus*, *domainname*,
   *endDay*, *inactiveUsers*, *maxUser*, *orgID*, *tel* and *title*

   If no attributes are specified, *ID*, *domainname* and *domainStatus* are shown.
``DOMAINNAME``
   Complete name of the domain
``DOMAINSPEC``
   Domain name prefix or domain ID
``--create-role``
   Automatically create a domain administrator role for the new domain
``--files``
   Also delete files from disk
``-f FIELD=<value>``, ``--filter FIELD=<value>``
   Filter expression in the form of ‘field=value’. Can be specified
   multiple times to refine filter
``--format FORMAT``
   Output format. Can be one of *csv*, *json-flat*, *json-structured* and
   *pretty*. Default is *pretty*.
`` --homeserver HOMESERVER``
   ID of the homeserver to place the domain on
``--no-defaults``
   Do not apply configured default values
``--separator SEPARATOR``
   String to use for column separation (*csv* and *pretty* only). Must have
   length 1 if format is *csv*. Default is "," for *csv* and "  " for pretty.
``-s FIELD``, ``--sort FIELD``
   Sort by field. Can be given multiple times
``-y``, ``--yes``
   Assume yes instead of prompting

Fields
======

``--address ADDRESS``
   Content of address field
``--adminName ADMINNAME``
   Name of the domain administrator or primary contact
``--endDay ENDDAY``
   Date of domain expiration in YYYY-MM-DD format
``--orgID ID``
   ID of the organization to assign the domain to
``--tel TEL``
   Telephone number of domain administrator or primary contact
``-u MAXUSER``, ``--maxUser MAXUSER``
   Maximum number of users in the domain

See Also
========

**grommunio-admin**\ (1), **grommunio-admin-exmdb**\ (1),
**grommunio-admin-fs**\ (1), **grommunio-admin-server**\ (1),
**grommunio-admin-user**\ (1)
