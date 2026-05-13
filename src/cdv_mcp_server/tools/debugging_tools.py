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

import requests

from cdv_mcp_server.tools.api_client import _build_url, _form_headers, _json_headers, cdv_get, cdv_post_form


def get_gc_monitor() -> str:
    """Retrieve whether GC monitoring is enabled on the CDV server."""
    return cdv_get("arc/adminapi/gcmonitor")


def set_gc_monitor(enabled: bool) -> str:
    """Enable or disable GC monitoring on the CDV server."""
    return cdv_post_form("arc/adminapi/gcmonitor", data={"enabled": str(enabled).lower()})


def get_gc_stats() -> str:
    """Retrieve the current GC debug flags from the CDV server."""
    return cdv_get("arc/adminapi/gcstats")


def set_gc_stats(debug_flags: str) -> str:
    """
    Set GC debug flags on the CDV server. Requires sys_viewlogs permission.

    Args:
        debug_flags: Name of the gc debug flag to set (e.g. 'DEBUG_SAVEALL').
    """
    return cdv_post_form("arc/adminapi/gcstats", data={"debug_flags": debug_flags})


def get_log_levels() -> str:
    """Retrieve the current log level for the root logger on the CDV server."""
    return cdv_get("arc/adminapi/loglevel")


def set_log_level(level: str) -> str:
    """
    Set the log level for the root logger on the CDV server. Requires sys_viewlogs permission.

    Args:
        level: One of CRITICAL, DEBUG, ERROR, FATAL, INFO, WARN, WARNING.
    """
    return cdv_post_form("arc/adminapi/loglevel", data={"level": level})


def get_logger_level(logger_name: str) -> str:
    """Retrieve the current log level for a specific logger by name."""
    return cdv_get(f"arc/adminapi/loglevel/{logger_name}")


def set_logger_level(logger_name: str, level: str) -> str:
    """
    Set the log level for a specific named logger. Requires sys_viewlogs permission.

    Args:
        logger_name: Name of the logger to update.
        level: One of CRITICAL, DEBUG, ERROR, FATAL, INFO, WARN, WARNING.
    """
    try:
        response = requests.post(
            _build_url(f"arc/adminapi/loglevel/{logger_name}"),
            headers=_json_headers(),
            json={"level": level},
            timeout=60,
        )
        response.raise_for_status()
        return response.text
    except requests.HTTPError as e:
        return json.dumps({"error": str(e), "status_code": e.response.status_code, "detail": e.response.text})
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_toggle_cprofile(
    module: str | None = None,
    owner: str | None = None,
    func: str | None = None,
) -> str:
    """
    Check whether cProfile profiling is enabled for a function on the CDV server.

    Args:
        module: Module containing the function (defaults to sqlrun.views_jsonselect).
        owner: Class or owner of the function.
        func: Function name (defaults to jsonselect_parallel).
    """
    params: dict = {}
    if module:
        params["module"] = module
    if owner:
        params["owner"] = owner
    if func:
        params["func"] = func
    return cdv_get("arc/adminapi/toggle_cprofile", params=params or None)


def toggle_cprofile(
    module: str | None = None,
    owner: str | None = None,
    func: str | None = None,
    strip_dirnames: str | None = None,
    print_callees: str | None = None,
    print_callers: str | None = None,
) -> str:
    """
    Toggle cProfile profiling for a function on the CDV server. Requires sys_viewlogs permission.
    If profiling is already enabled, this call disables it.

    Args:
        module: Module containing the function.
        owner: Class or owner of the function.
        func: Function name.
        strip_dirnames: 'yes' or 'no' — whether to strip directory names in output.
        print_callees: 'yes' or 'no' — include callee info in output.
        print_callers: 'yes' or 'no' — include caller info in output.
    """
    params: dict = {}
    if module:
        params["module"] = module
    if owner:
        params["owner"] = owner
    if func:
        params["func"] = func
    if strip_dirnames:
        params["strip_dirnames"] = strip_dirnames
    if print_callees:
        params["print_callees"] = print_callees
    if print_callers:
        params["print_callers"] = print_callers
    try:
        response = requests.post(
            _build_url("arc/adminapi/toggle_cprofile"),
            headers=_form_headers(),
            params=params or None,
            timeout=60,
        )
        response.raise_for_status()
        return response.text
    except requests.HTTPError as e:
        return json.dumps({"error": str(e), "status_code": e.response.status_code, "detail": e.response.text})
    except Exception as e:
        return json.dumps({"error": str(e)})


def reset_dataset_cache(dataset_id: int) -> str:
    """Reset the result cache for a specific dataset. Requires ds_manage permission."""
    return cdv_post_form(f"arc/datasets/dataset/cache_reset/{dataset_id}", data={})


def reset_dataconnection_cache(connection_id: int) -> str:
    """Reset the result cache for a specific data connection. Requires ds_manage permission."""
    return cdv_post_form(f"arc/datasets/dataconnection/cache_reset/{connection_id}", data={})
