from __future__ import absolute_import

import logging
import typing

from collections import defaultdict
from typing import List

import pyspark.sql as spark

from dbnd._core.tracking.schemas.column_stats import ColumnStatsArgs
from targets.value_meta import ValueMeta
from targets.values.builtins_values import DataValueType


if typing.TYPE_CHECKING:
    from targets.value_meta import ValueMetaConf

logger = logging.getLogger(__name__)


class SparkDataFrameValueType(DataValueType):
    type = spark.DataFrame
    type_str = "Spark.DataFrame"
    support_merge = False

    config_name = "spark_dataframe"

    is_lazy_evaluated = True

    def to_signature(self, x):
        id = "rdd-%s-at-%s" % (x.rdd.id(), x.rdd.context.applicationId)
        return id

    def to_preview(self, df, preview_size):  # type: (spark.DataFrame, int) -> str
        return (
            df.limit(1000)
            .toPandas()
            .to_string(index=False, max_rows=20, max_cols=1000)[:preview_size]
        )

    def get_value_meta(self, value, meta_conf):
        # type: (spark.DataFrame, ValueMetaConf) -> ValueMeta

        if meta_conf.log_schema:
            data_schema = {
                "type": self.type_str,
                "columns": list(value.schema.names),
                "dtypes": {f.name: str(f.dataType) for f in value.schema.fields},
            }
        else:
            data_schema = None

        if meta_conf.log_preview:
            data_preview = self.to_preview(value, meta_conf.get_preview_size())
        else:
            data_preview = None

        if meta_conf.log_size:
            data_schema = data_schema or {}
            rows = value.count()
            data_dimensions = (rows, len(value.columns))
            data_schema.update(
                {
                    "size.bytes": int(rows * len(value.columns)),
                    "shape": (rows, len(value.columns)),
                }
            )
        else:
            data_dimensions = None

        df_columns_stats, histogram_dict = [], {}
        hist_sys_metrics = None

        if meta_conf.log_histograms:
            logger.warning("log_histograms are not supported for spark dataframe")

        if meta_conf.log_stats:
            df_columns_stats = self.calculate_spark_stats(value)

        return ValueMeta(
            value_preview=data_preview,
            data_dimensions=data_dimensions,
            data_schema=data_schema,
            data_hash=self.to_signature(value),
            columns_stats=df_columns_stats,
            histogram_system_metrics=hist_sys_metrics,
            histograms=histogram_dict,
        )

    def calculate_spark_stats(
        self, df
    ):  # type: (spark.DataFrame) -> List[ColumnStatsArgs]
        """
        Calculate descriptive statistics for Spark Dataframe and return them in format consumable by tracker.
        Spark has built-in method for stats calculation, it returns table like this:
        +-------+-------------+--------------------+
        |summary|serial_number|      capacity_bytes|
        +-------+-------------+--------------------+
        |  count|        42390|               42389|
        |   mean|         null|2.549704589668174E12|
        | stddev|         null|7.415846913745422E11|
        |    min|     5XW004Q0|       1000204886016|
        |    25%|         null|       2000398934016|
        |    50%|         null|       3000592982016|
        |    75%|         null|       3000592982016|
        |    max|     Z2926ALH|       4000787030016|
        +-------+-------------+--------------------+
        Each row represents specific metric values for every column.
        We are iterating over this table and converting results to list of ColumnStatsArgs
        :param df:
        :return:
        """
        total_count = df.count()
        stats = defaultdict(dict)

        for row in df.summary().collect():
            metric_row = row.asDict()
            metric_name = metric_row["summary"]
            for col in df.columns:
                stats[col][metric_name] = metric_row.get(col)

        result: List[ColumnStatsArgs] = []
        for col in df.schema.fields:
            if not isinstance(
                col.dataType, (spark.types.NumericType, spark.types.StringType)
            ):
                # We calculate descriptive statistics only for numeric and string columns
                continue

            name = col.name
            col_stats = stats[name]
            if isinstance(col.dataType, spark.types.StringType):
                result.append(
                    ColumnStatsArgs(
                        column_name=name,
                        column_type=str(col.dataType),
                        records_count=total_count,
                        null_count=total_count - int(col_stats["count"]),
                    )
                )
            elif isinstance(col.dataType, spark.types.NumericType):
                result.append(
                    ColumnStatsArgs(
                        column_name=name,
                        column_type=str(col.dataType),
                        records_count=total_count,
                        null_count=total_count - int(col_stats["count"]),
                        min_value=col_stats["min"],
                        max_value=col_stats["max"],
                        std_value=col_stats["stddev"],
                        mean_value=col_stats["mean"],
                        quartile_1=col_stats["25%"],
                        quartile_2=col_stats["50%"],
                        quartile_3=col_stats["75%"],
                    )
                )

        return result

    def support_fast_count(self, target):
        from targets import FileTarget

        if not isinstance(target, FileTarget):
            return False
        from targets.target_config import FileFormat

        return target.config.format == FileFormat.parquet
