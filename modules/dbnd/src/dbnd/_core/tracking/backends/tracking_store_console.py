import logging
import typing

from collections import Callable
from datetime import timedelta
from itertools import chain
from math import floor, log10

import six

from more_itertools import collapse, partition

from dbnd._core.configuration.dbnd_config import config as dbnd_config
from dbnd._core.configuration.environ_config import in_airflow_tracking_mode
from dbnd._core.constants import SystemTaskName, TaskRunState
from dbnd._core.current import is_verbose
from dbnd._core.tracking.backends import TrackingStore
from dbnd._core.tracking.schemas.metrics import Metric
from dbnd._core.utils.basics.text_banner import safe_tabulate
from dbnd._core.utils.timezone import utcnow
from dbnd._vendor.ascii_graph import Pyasciigraph


try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest


if typing.TYPE_CHECKING:
    from typing import Any, Dict, Iterable, List, Tuple

    from dbnd._core.task_run.task_run import TaskRun
    from targets.value_meta import ValueMeta

logger = logging.getLogger(__name__)


def is_describe_stat(item):
    name, _ = item
    return name in ["min_value", "quartile_1", "quartile_2", "quartile_3", "max_value"]


def two_columns_table(stats, split_by):
    # type: (Dict, Callable[Tuple[Any,Any], bool]) -> str
    """
    Split the items by a filter function "split_by" and merge
    Example:
        two_columns_table({1: "a", 2: "b", 3: "c", 4: "d"}, is_odd)
        [ 2 , b , 1 , a ]
        [ 3 , d , 3 , c ]
    """
    splatted = partition(split_by, stats.items())
    flatten_merged_rows = map(collapse, zip_longest(*splatted))
    return safe_tabulate(flatten_merged_rows, headers=())


class ConsoleStore(TrackingStore):
    def __init__(self, *args, **kwargs):
        super(ConsoleStore, self).__init__(*args, **kwargs)
        self.max_log_value_len = 50
        self.verbose = is_verbose()
        self.ascii_graph = Pyasciigraph()
        self._is_in_airflow_tracking_mode = in_airflow_tracking_mode()

    def init_run(self, run):
        if run.is_orchestration:
            logger.info(
                run.describe.run_banner(
                    "Running Databand v%s" % run.context.task_run_env.databand_version,
                    color="cyan",
                    show_run_info=True,
                )
            )

            if run.context.name == "interactive":
                from dbnd._core.tools import ipython

                ipython.show_run_url(run.run_url)

    def set_task_reused(self, task_run):
        task = task_run.task
        logger.info(
            task.ctrl.visualiser.banner(
                "Task %s has been completed already!" % task.task_id,
                "magenta",
                task_run=task_run,
            )
        )

    def set_task_run_state(self, task_run, state, error=None, timestamp=None):
        super(ConsoleStore, self).set_task_run_state(task_run=task_run, state=state)

        task = task_run.task

        if self._is_in_airflow_tracking_mode:
            if state == TaskRunState.RUNNING:
                logger.info(
                    "Tracking %s task at %s",
                    task.task_name,
                    dbnd_config.get("core", "databand_url"),
                )
            return

        # optimize, don't print success banner for fast running tasks
        start_time = task_run.start_time or utcnow()
        quick_task = task_run.finished_time and (
            task_run.finished_time - start_time
        ) < timedelta(seconds=5)

        show_simple_log = not self.verbose and (
            task_run.task.task_is_system or quick_task
        )

        level = logging.INFO
        color = "cyan"
        task_friendly_id = task_run.task_af_id
        task_id_str = "%s(%s)" % (task.task_id, task_friendly_id)
        if state in [TaskRunState.RUNNING, TaskRunState.QUEUED]:
            task_msg = "Running task %s" % task_id_str

        elif state == TaskRunState.SUCCESS:
            task_msg = "Task %s has been completed!" % task_id_str
            color = "green"

        elif state == TaskRunState.FAILED:
            task_msg = "Task %s has failed!" % task_id_str
            color = "red"
            level = logging.WARNING
            if task_run.task.task_name in SystemTaskName.driver_and_submitter:
                show_simple_log = True

        elif state == TaskRunState.CANCELLED:
            task_msg = "Task %s has been canceled!" % task_id_str
            color = "red"
            level = logging.WARNING
            show_simple_log = True

        else:
            task_msg = "Task %s moved to %s state" % (task_friendly_id, state)

        if show_simple_log:
            logger.log(level, task_msg)
            return

        try:
            logger.log(
                level, task.ctrl.visualiser.banner(task_msg, color, task_run=task_run)
            )
        except Exception as ex:
            logger.log(level, "%s , failed to create banner: %s" % (task_msg, ex))

    def add_task_runs(self, run, task_runs):
        pass

    def save_external_links(self, task_run, external_links_dict):
        task = task_run.task
        attempt_uid = task_run.task_run_attempt_uid

        logger.info(
            "%s %s has registered URLs to external resources: %s",
            task,
            attempt_uid,
            ", ".join("%s: %s" % (k, v) for k, v in six.iteritems(external_links_dict)),
        )

    def is_ready(self):
        return True

    def log_histograms(self, task_run, key, value_meta, timestamp):
        # type: (TaskRun, str, ValueMeta, datetime) -> None

        for graph in self.get_console_histograms(key, value_meta):
            for line in graph:
                # we add one line at a time using the logger to keep the output aligned together
                logger.info(line)

        if not self.verbose:
            return

        for key, value in value_meta.histogram_system_metrics.items():
            if isinstance(value, float):
                value = round(value, 3)
            logger.info("%s: %s", key, value)

    def get_console_histograms(self, key, value_meta):
        # type: (str, ValueMeta) -> Iterable[Iterable[str]]
        """
        Iterate over histograms and for each its build a all the lines to print to the console
        """
        for column_name, hist_values in value_meta.histograms.items():
            console_graph = self.ascii_graph.graph(
                label=f"Histogram logged: {key}.{column_name}",
                data=list(zip(*reversed(hist_values))),
            )

            # not will exists, but when it does - we need to add the stats as a table to the console
            if value_meta.columns_stats:
                column_stats = value_meta.get_column_stats_by_col_name(column_name)
                if column_stats:
                    stats_table = two_columns_table(
                        column_stats.as_dict(), is_describe_stat
                    )
                    # channing the printable graph and status table
                    console_graph = chain(console_graph, stats_table.splitlines())

            # separation line between one histogram and the other
            console_graph = chain(console_graph, [""])
            yield console_graph

    @staticmethod
    def _format_value(value):
        """
        Convert value to string.
        Additionally forces float values to NOT use scientific notation.
        """
        if isinstance(value, float):
            value_width = 1 if value == 0.0 else abs(floor(log10(abs(value))))
            # default python precision threshold to switch to scientific representation of floats
            if value > 1 or value_width < 4:
                return str(value)
            return "{:{width}.{prec}f}".format(
                value, width=value_width, prec=value_width + 4
            )
        return str(value)

    def log_metrics(self, task_run, metrics):
        # type: (TaskRun, List[Metric]) -> None
        if len(metrics) == 1:
            m = metrics[0]
            logger.info(
                "Task {name} metric: {key}={value}".format(
                    name=task_run.task_af_id,
                    key=m.key,
                    value=self._format_value(m.value),
                )
            )
        else:
            metrics_str = ", ".join(
                ["{}={}".format(m.key, self._format_value(m.value)) for m in metrics]
            )
            logger.info("Task %s metrics: %s", task_run.task_af_id, metrics_str)
