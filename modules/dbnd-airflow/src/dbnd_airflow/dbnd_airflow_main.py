#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
# -*- coding: utf-8 -*-
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import logging
import os
import subprocess
import sys

from airflow import settings as airflow_settings

import argcomplete

from dbnd._core.utils.timeout import wait_until


# DO NOT IMPORT ANYTHING FROM AIRFLOW
# we need to initialize some config values first
from dbnd import dbnd_config  # isort:skip
from dbnd._core.context.bootstrap import dbnd_system_bootstrap  # isort:skip

logger = logging.getLogger(__name__)


def subprocess_airflow(args):
    """Forward arguments to airflow command line"""

    from airflow.configuration import conf
    from sqlalchemy.engine.url import make_url

    # let's make sure that we user correct connection string
    airflow_sql_conn = conf.get("core", "SQL_ALCHEMY_CONN")
    env = os.environ.copy()
    env["AIRFLOW__CORE__SQL_ALCHEMY_CONN"] = airflow_sql_conn
    env["AIRFLOW__CORE__FERNET_KEY"] = conf.get("core", "FERNET_KEY")

    # if we use airflow, we can get airflow from external env
    args = [sys.executable, "-m", "dbnd_airflow"] + args
    logging.info(
        "Running airflow command at subprocess: '%s" " with DB=%s",
        subprocess.list2cmdline(args),
        repr(make_url(airflow_sql_conn)),
    )
    try:
        subprocess.check_call(args=args, env=env)
    except Exception:
        logging.error(
            "Failed to run airflow command %s with path=%s",
            subprocess.list2cmdline(args),
            sys.path,
        )
        raise
    logging.info("Airflow command has been successfully executed")


def subprocess_airflow_initdb():
    logging.info("Initializing Airflow DB")
    return subprocess_airflow(args=["initdb"])


def wait_for_airflow_db(args):
    logger.info(
        "Waiting {} seconds for Airflow DB to become ready:".format(args.timeout)
    )

    check_alive_query = "SELECT now();"
    if repr(airflow_settings.engine.url).startswith("sqlite:///"):
        check_alive_query = "SELECT date();"

    def is_db_ready():
        try:
            airflow_settings.engine.execute(check_alive_query)
            return True
        except Exception as exc:
            return False

    is_ready = wait_until(is_db_ready, args.timeout)
    if not is_ready:
        logger.error("Airflow DB is not ready after {} seconds.".format(args.timeout))
        sys.exit(1)
    logger.info("Airflow DB is ready.")


def main(args=None):
    # from dbnd._core.log.config import configure_basic_logging
    # configure_basic_logging(None)

    dbnd_system_bootstrap()

    # LET'S PATCH AIRFLOW FIRST
    from dbnd_airflow.bootstrap import dbnd_airflow_bootstrap

    dbnd_airflow_bootstrap()

    from airflow.bin.cli import CLIFactory
    from airflow.configuration import conf
    from dbnd_airflow.plugins.setup_plugins import (
        setup_scheduled_dags,
        setup_versioned_dags,
    )

    # ORIGINAL CODE from  airflow/bin/airflow
    if conf.get("core", "security") == "kerberos":
        os.environ["KRB5CCNAME"] = conf.get("kerberos", "ccache")
        os.environ["KRB5_KTNAME"] = conf.get("kerberos", "keytab")

    parser = CLIFactory.get_parser()
    initdb_parser = parser._subparsers._group_actions[0]._name_parser_map["initdb"]
    initdb_parser.add_argument(
        "--wait", action="store_true", help="Wait airflow DB to become available",
    )
    initdb_parser.add_argument(
        "--timeout", default=120, type=int, help="Timeout for waiting airflow DB",
    )
    argcomplete.autocomplete(parser)
    args = parser.parse_args(args=args)
    func_name = args.func.__name__

    # DBND PATCH:
    if dbnd_config.getboolean("airflow", "auto_add_scheduled_dags") and func_name in [
        "scheduler",
        "webserver",
    ]:
        setup_scheduled_dags()
    if dbnd_config.getboolean("airflow", "auto_add_versioned_dags") and func_name in [
        "webserver"
    ]:
        setup_versioned_dags()

    if args.subcommand == "initdb" and args.wait:
        wait_for_airflow_db(args)

    args.func(args)


if __name__ == "__main__":
    main()
