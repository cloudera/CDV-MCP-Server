## Copyright (c) 2025 Cloudera, Inc. All Rights Reserved.
##
## This file is licensed under the Apache License Version 2.0 (the "License").
## You may not use this file except in compliance with the License.
## You may obtain a copy of the License at http:##www.apache.org/licenses/LICENSE-2.0.
##
## This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS
## OF ANY KIND, either express or implied. Refer to the License for the specific
## permissions and limitations governing your use of the file.

import json

from cdv_mcp_server.tools.api_client import cdv_post_form


def run_job(schedule_ids: str | None = None, schedule_names: str | None = None) -> str:
    """
    Trigger a rerun of scheduled CDV jobs.

    Provide exactly one of:
      - schedule_ids: comma-separated list of schedule IDs
      - schedule_names: comma-separated list of schedule names
    """
    if schedule_ids and schedule_names:
        return json.dumps({"error": "Provide only one of schedule_ids or schedule_names, not both."})
    if not schedule_ids and not schedule_names:
        return json.dumps({"error": "One of schedule_ids or schedule_names must be provided."})

    data: dict = {}
    if schedule_ids:
        data["schedule_ids"] = schedule_ids
    if schedule_names:
        data["schedule_names"] = schedule_names
    return cdv_post_form("arc/jobs/api/run/", data=data)


def run_extract(extract_ids: str) -> str:
    """
    Run one or more CDV data extract jobs.

    Args:
        extract_ids: Comma-separated list of extract IDs to run.
    """
    return cdv_post_form("arc/jobs/api/extracts/run", data={"extract_ids": extract_ids})


def create_extract(
    src_dataset_id: int,
    tgt_dataconnection_id: int,
    tgt_dbname: str,
    tgt_tablename: str,
    dim_data: str,
    agg_data: str,
    partition_data: str = "[]",
    schedule_id: int | None = None,
) -> str:
    """
    Create a CDV data extract job.

    Args:
        src_dataset_id: ID of the source dataset.
        tgt_dataconnection_id: ID of the target data connection.
        tgt_dbname: Target database name.
        tgt_tablename: Target table name.
        dim_data: JSON string of dimension columns.
                  Example: '[{"expr":"[col_name]","alias":"col_name"}]'
        agg_data: JSON string of aggregate columns.
                  Example: '[{"expr":"sum([col_name])","alias":"col_name"}]'
        partition_data: JSON string of partition columns for incremental refresh (default '[]').
        schedule_id: Optional schedule ID to associate a job with the extract.
    """
    config: dict = {
        "srcDatasetId": src_dataset_id,
        "tgtDataconnectionId": tgt_dataconnection_id,
        "tgtDbname": tgt_dbname,
        "tgtTablename": tgt_tablename,
        "dimData": dim_data,
        "aggData": agg_data,
        "partitionData": partition_data,
    }
    if schedule_id is not None:
        config["scheduleId"] = schedule_id

    return cdv_post_form("arc/jobs/api/extracts/create", data={"data": json.dumps(config)})
