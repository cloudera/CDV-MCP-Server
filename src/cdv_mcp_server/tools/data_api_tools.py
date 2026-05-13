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

from cdv_mcp_server.tools.api_client import cdv_get, cdv_post_form


def _normalize_dataapi_response(raw_text: str) -> str:
    """
    Normalize the CDV Data API wire format into a clean list-of-dicts response.

    CDV returns:
      { "colnames": [...], "coltypes": [...], "rows": "[[...]]", "rowcount": N, ... }

    where ``rows`` is a JSON string containing an array of value arrays.
    We convert this to:
      { "columns": [...], "rows": [{col: val, ...}, ...], "rowcount": N }

    Any response that is already a list or lacks ``colnames`` is returned as-is.
    """
    try:
        data = json.loads(raw_text)
    except Exception:
        return raw_text

    if not isinstance(data, dict) or "colnames" not in data:
        return raw_text

    colnames = data["colnames"]
    rows_raw = data.get("rows", "[]")
    if isinstance(rows_raw, str):
        try:
            rows_raw = json.loads(rows_raw)
        except Exception:
            rows_raw = []

    result: dict = {
        "columns": colnames,
        "rows": [dict(zip(colnames, row)) for row in rows_raw],
        "rowcount": data.get("rowcount", len(rows_raw)),
    }
    warnings = data.get("query_warnings", {})
    if warnings.get("inf") or warnings.get("nan"):
        result["warnings"] = warnings
    return json.dumps(result)


def query_dataapi_get(
    dataset: int | None = None,
    dataconnection_id: int | None = None,
    query: str | None = None,
    limit: int | None = None,
    dimensions: str | None = None,
    aggregates: str | None = None,
    filters: str | None = None,
) -> str:
    """
    Query data via the CDV Data API (GET).

    Dataset-based: provide dataset (ID), optionally limit, dimensions (comma-separated),
    aggregates (comma-separated), filters (comma-separated).

    Connection-based: provide dataconnection_id and query (SQL string).
    """
    params: dict = {}
    if dataset is not None:
        params["dataset"] = dataset
    if dataconnection_id is not None:
        params["dataconnection_id"] = dataconnection_id
    if query is not None:
        params["query"] = query
    if limit is not None:
        params["limit"] = limit
    if dimensions is not None:
        params["dimensions"] = dimensions
    if aggregates is not None:
        params["aggregates"] = aggregates
    if filters is not None:
        params["filters"] = filters
    return _normalize_dataapi_response(cdv_get("arc/apps/dataapi", params=params))


def query_dataapi_post(
    dataset: int | None = None,
    dataconnection_id: int | None = None,
    query: str | None = None,
    limit: int | None = None,
    dimensions: str | None = None,
    aggregates: str | None = None,
    filters: str | None = None,
) -> str:
    """
    Query data via the CDV Data API (POST). Same parameters as the GET version.
    """
    data: dict = {}
    if dataset is not None:
        data["dataset"] = dataset
    if dataconnection_id is not None:
        data["dataconnection_id"] = dataconnection_id
    if query is not None:
        data["query"] = query
    if limit is not None:
        data["limit"] = limit
    if dimensions is not None:
        data["dimensions"] = dimensions
    if aggregates is not None:
        data["aggregates"] = aggregates
    if filters is not None:
        data["filters"] = filters
    return _normalize_dataapi_response(cdv_post_form("arc/apps/dataapi", data=data))


def query_enhanced_data_api_get(
    version: str,
    dataset: int | None = None,
    dsreq: str | None = None,
    limit: int | None = None,
    dimensions: str | None = None,
    aggregates: str | None = None,
) -> str:
    """
    Query data via the CDV Enhanced Data API (GET /api/data).

    version: '0' for legacy API, '1' for enhanced API (uses dsreq JSON).

    Version 0: provide dataset, limit, dimensions (JSON list), aggregates (JSON list).
    Version 1: provide dsreq (JSON-formatted dataset request string).
    """
    params: dict = {"version": version}
    if dataset is not None:
        params["dataset"] = dataset
    if dsreq is not None:
        params["dsreq"] = dsreq
    if limit is not None:
        params["limit"] = limit
    if dimensions is not None:
        params["dimensions"] = dimensions
    if aggregates is not None:
        params["aggregates"] = aggregates
    return cdv_get("arc/api/data", params=params)


def query_enhanced_data_api_post(
    version: str,
    dataset: int | None = None,
    dsreq: str | None = None,
    limit: int | None = None,
    dimensions: str | None = None,
    aggregates: str | None = None,
) -> str:
    """
    Query data via the CDV Enhanced Data API (POST /api/data).
    Same parameters as the GET version.
    """
    data: dict = {"version": version}
    if dataset is not None:
        data["dataset"] = dataset
    if dsreq is not None:
        data["dsreq"] = dsreq
    if limit is not None:
        data["limit"] = limit
    if dimensions is not None:
        data["dimensions"] = dimensions
    if aggregates is not None:
        data["aggregates"] = aggregates
    return cdv_post_form("arc/api/data", data=data)
