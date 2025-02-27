from airflow_monitor.shared.runners.base_runner import BaseRunner
from airflow_monitor.shared.runners.multi_process_runner import MultiProcessRunner
from airflow_monitor.shared.runners.sequential_runner import SequentialRunner


RUNNER_FACTORY = {
    "seq": SequentialRunner,
    "mp": MultiProcessRunner,
}
