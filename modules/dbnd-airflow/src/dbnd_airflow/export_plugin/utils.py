import datetime
import json

from distutils.version import LooseVersion

import airflow

from flask import Response


class JsonEncoder(json.JSONEncoder):
    def default(self, obj):
        # convert dates and numpy objects in a json serializable format
        if isinstance(obj, datetime.datetime):
            return obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        elif isinstance(obj, datetime.date):
            return obj.strftime("%Y-%m-%d")

        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)


def json_response(obj):
    return Response(
        response=json.dumps(obj, indent=4, cls=JsonEncoder),
        status=200,
        mimetype="application/json",
    )


AIRFLOW_VERSION_2 = LooseVersion(airflow.version.version) >= LooseVersion("2.0.0")
AIRFLOW_VERSION_BEFORE_2_2 = LooseVersion(airflow.version.version) < LooseVersion(
    "2.2.0"
)
