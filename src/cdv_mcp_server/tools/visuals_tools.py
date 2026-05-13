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
from typing import Optional
from urllib.parse import urljoin

from cdv_mcp_server.tools.api_client import (
    cdv_delete,
    cdv_get,
    cdv_post_admin,
    cdv_post_form,
    cdv_save_visual_config,
    get_base_url,
)

_BASE = "arc/adminapi/v1/visuals"

# Visual types confirmed to render correctly via the API.
# Other CDV visual types exist but require CDV's interactive builder to configure
# their shelves properly — they are not exposed here to avoid broken charts.
VALID_VISUAL_TYPES = {
    "trellis-bars",        # Horizontal bar: measure on x, dimension on y — most reliable
    "trellis-groupedbars", # Grouped/stacked bars: single SUM measure, multiple dimensions
    "pie",                 # Pie/donut: SUM measure on theta, dimension on color
    "dashboard",           # Container for grouping multiple chart visuals
}

# Aggregate functions that reliably produce valid Impala SQL through CDV's
# internal SQL generator.  "count" is excluded because CDV wraps it in bracket
# notation ([col]) that it cannot convert → ParseException.
VALID_AGGS = {"sum", "avg", "min", "max"}

# Column name prefixes that collide with CDV's aggregate-function tokenizer.
# When a column name starts with one of these strings, CDV may confuse the
# column reference with a function call and generate broken bracket SQL.
_AGG_PREFIX_COLLISION = ("avg_", "sum_", "min_", "max_", "count_")

# CDV always uses fn_type=1 for all standard aggregate functions.
# The actual SQL function is determined by fn_name (e.g. "sum", "avg", "count").
# Using any other fn_type triggers a different SQL generation path in CDV's
# frontend that produces bracket notation [col] instead of `col` backtick
# notation, causing Impala ParseExceptions.
_AGG_FN_TYPE: dict[str, int] = {
    "avg": 1,
    "sum": 1,
    "min": 1,
    "max": 1,
}


def _infer_col_type(col_name: str, agg: str | None = None) -> str:
    """
    Return a CDV ``dataset_coltype`` string for a shelf entry.

    CDV's frontend calls ``o.dataset_coltype().toUpperCase()`` on every shelf
    entry.  A missing or undefined field raises::

        TypeError: Cannot read properties of undefined (reading 'toUpperCase')

    CDV's SQL generator uses ``fn_type`` (not ``dataset_coltype``) to choose its
    code path.  ``dataset_coltype`` is only used for the toUpperCase call.
    Using STRING for all dimensions avoids TIMESTAMP-related bracket conversion
    failures; DOUBLE for aggregates is accurate and safe.
    """
    if agg:
        return "DOUBLE"
    return "STRING"


def _shelf_entry(col_name: str, agg: str | None = None) -> dict:
    """
    Build a CDV shelf entry dict that produces valid Impala SQL via CDV's query engine.

    CDV SQL Generation Rules (discovered through extensive testing):

    1. ``fn_type`` MUST be 1 for all aggregates (sum, avg, min, max, count).
       Any other fn_type value (2=avg, 3=sum, 4=min, 5=max in some docs) triggers
       a different internal SQL generation path that wraps column names in ``[col]``
       bracket notation.  CDV's bracket-to-backtick conversion does not run for that
       path, producing Impala ParseExceptions like::
           SELECT [supplier_name] as `supplier_name` ...
                   ^Encountered: AS

    2. ``expression_for_trigger`` is NOT used for SQL generation by CDV.  CDV builds
       SQL independently from ``fn_name + dataset_colname``.  We store it as a
       human-readable hint, but changing it does not affect the generated SQL.

    3. CDV's bracket-to-backtick conversion does not run for all column names.
       Columns that reliably work as dimensions (y_shelf for trellis-bars):
         - Typical STRING columns: supplier_name, shipping_code, item_description
       Columns known to cause bracket conversion failures:
         - Columns whose name starts with an aggregate prefix (avg_, sum_, etc.)
         - TIMESTAMP columns used as y_shelf dimensions
         - Some column names that happen to collide with CDV's SQL keywords
       If a dimension fails to render, replace it with a known-safe STRING column.

    4. Filters (``filters_shelf``) always generate bracket notation in the WHERE
       clause that CDV cannot convert.  Chart-level filters created via the API
       will cause Impala ParseExceptions in the WHERE clause.  Avoid ``filters``
       in ``create_smart_visual``; apply filters interactively in CDV's builder.
    """
    col_type = _infer_col_type(col_name, agg)
    if agg:
        return {
            "dataset_colname": col_name,
            "col_alias": col_name,
            "fn_type": _AGG_FN_TYPE.get(agg, 1),
            "fn_name": agg,
            "dataset_coltype": col_type,
            # Use backtick (Impala) notation so CDV can use this verbatim as valid SQL.
            # Some visual types (trellis-groupedbars, trellis-lines, count aggregates)
            # use expression_for_trigger literally; backticks work correctly there.
            "expression_for_trigger": f"{agg}(`{col_name}`)",
            "expr_hasagg": True,
        }
    else:
        return {
            "dataset_colname": col_name,
            "dataset_coltype": col_type,
            # Backtick notation: valid Impala SQL when used verbatim by CDV
            "expression_for_trigger": f"`{col_name}`",
        }


def _filter_entry(f: dict) -> dict:
    """
    Convert a user-supplied filter dict to a CDV filters_shelf entry.

    Accepted input shapes::

        {"column_name": "item", "value": "Turbine Oil"}
        {"column_name": "status", "values": ["A", "B"]}
        {"column_name": "status", "values": ["C"], "exclude": true}

    ``column`` is accepted as an alias for ``column_name`` for convenience.

    **WARNING:** CDV's SQL generator always wraps filter columns in bracket
    notation ``([col])`` in the Impala WHERE clause.  CDV's bracket-to-backtick
    conversion does not run for WHERE clauses, producing::

        ParseException: Syntax error in line N: WHERE ([col_name])

    Filters via the API consistently fail.  Apply filters in CDV's interactive
    builder instead.
    """
    col_name = f.get("column_name") or f.get("column", "")
    values = f.get("values") or ([f["value"]] if "value" in f else [])
    exclude = bool(f.get("exclude", False))
    return {
        "dataset_colname": col_name,
        "dataset_coltype": _infer_col_type(col_name),
        "expression_for_trigger": f"`{col_name}`",
        "values": [str(v) for v in values],
        "exclude": exclude,
    }


def _build_report_data(
    visual_type: str,
    title: str,
    columns: list[dict],
    filters: list[dict] | None = None,
) -> dict:
    """
    Construct a complete CDV ``data`` payload from a normalised column list.

    Each column dict may contain:
    * ``column_name``        (str, required)
    * ``aggregate_function`` (str, optional) — makes the column a measure
    * ``shelf``              (str, optional) — explicit shelf override:
                             ``"x"`` | ``"y"`` | ``"color"`` | ``"theta"``
                             Overrides the automatic shelf assignment below.

    Default shelf assignment when no ``shelf`` override is given:

    * ``table`` / ``crosstab`` / ``sparklines`` — all columns → x_shelf
    * ``pie``                                   — dimensions → color_shelf, measures → theta_shelf
    * ``trellis-bars`` / ``trellis-groupedbars`` — dimensions → y_shelf, measures → x_shelf
    * everything else                            — dimensions → x_shelf, measures → y_shelf

    **Compatibility notes:**
    Filters converted to ``filters_shelf`` entries generate bracket notation in the
    Impala WHERE clause that CDV cannot convert, causing ParseExceptions.  Avoid
    using ``filters`` unless you can verify the column works via CDV's own builder.

    Proven reliable visual_type + aggregate combinations (dataset-dependent):
    * ``trellis-bars`` with ``sum`` or ``avg`` on non-``avg_``/``sum_`` prefixed columns
    * ``trellis-groupedbars`` with a single ``sum`` aggregate
    * ``pie`` with ``sum``
    """
    x_shelf: list[dict] = []
    y_shelf: list[dict] = []
    color_shelf: list[dict] = []
    theta_shelf: list[dict] = []

    auto_dims: list[dict] = []
    auto_measures: list[dict] = []

    for col in columns:
        name = col["column_name"]
        agg = col.get("aggregate_function") or None
        entry = _shelf_entry(name, agg)
        override = col.get("shelf")

        if override == "x":
            x_shelf.append(entry)
        elif override == "y":
            y_shelf.append(entry)
        elif override == "color":
            color_shelf.append(entry)
        elif override == "theta":
            theta_shelf.append(entry)
        elif agg:
            auto_measures.append(entry)
        else:
            auto_dims.append(entry)

    # Apply default shelf assignment for columns without an explicit override.
    # CDV trellis-bars/trellis-groupedbars are HORIZONTAL: x=measure, y=dimension.
    # trellis-lines / scatter: x=dimension (category/time), y=measure (value).
    if visual_type in {"table", "crosstab", "sparklines"}:
        x_shelf = x_shelf + auto_dims + auto_measures
    elif visual_type == "pie":
        color_shelf = color_shelf + auto_dims
        theta_shelf = theta_shelf + auto_measures
    elif visual_type in {"trellis-bars", "trellis-groupedbars", "kpi", "gauge", "bullet"}:
        # Horizontal bars: x-axis is the VALUE (measure), y-axis is the CATEGORY (dimension)
        x_shelf = x_shelf + auto_measures
        y_shelf = y_shelf + auto_dims
    else:
        # Lines, scatter, etc.: x-axis is category/time (dimension), y-axis is value (measure)
        x_shelf = x_shelf + auto_dims
        y_shelf = y_shelf + auto_measures

    filters_shelf = [_filter_entry(f) for f in (filters or [])]

    report_data = {
        "report_title": title,
        "report_subtitle": "",
        "selected_segments": [],
        "filters_shelf": filters_shelf,
        "x_shelf": x_shelf,
        "y_shelf": y_shelf,
        "color_shelf": color_shelf,
        "theta_shelf": theta_shelf,
        "tooltip_shelf": [],
        "dimensions_shelf": [],
        "aggregates_shelf": [],
        "sort_orders_asc": [],
        "limit": 50,
        "sample_pct": 100,
        "settings": {},
        "user_settings": {},
        "click_behaviors": [],
    }
    return {
        "report_data": report_data,
        "report_type": visual_type,
    }


def _enrich_visual_response(result_text: str) -> str:
    """Attach ``visual_id`` and ``url`` fields to a visual API response when an ``id`` is present."""
    try:
        result = json.loads(result_text)
        if isinstance(result, list) and result:
            result = result[0]
        if isinstance(result, dict) and "id" in result and "error" not in result:
            result["visual_id"] = result["id"]
            try:
                result["url"] = urljoin(get_base_url(), f"arc/apps/app/{result['id']}")
            except Exception:
                pass
        return json.dumps(result)
    except Exception:
        return result_text


def list_visuals(dataset_id: int | None = None, workspace_id: int | None = None) -> str:
    """
    IMPORTANT — CDV API LIMITATION:
    The /adminapi/v1/visuals endpoint only returns dashboard-type visuals (type="dashboard").
    Standalone chart visuals created with create_smart_visual() or create_visual() are NOT
    returned by this listing even though they exist in the workspace.

    To access standalone chart visuals:
      - Retrieve them individually with get_visual(object_id=<id>) using the id returned
        at creation time.
      - Or call create_dashboard() with their IDs to group them into a visible dashboard.

    Filters: dataset_id or workspace_id narrow results within the dashboard list.
    """
    params: dict = {}
    if dataset_id is not None:
        params["dataset_id"] = dataset_id
    if workspace_id is not None:
        params["workspace_id"] = workspace_id
    return cdv_get(_BASE, params=params or None)


def get_visual(object_id: int) -> str:
    return cdv_get(f"{_BASE}/{object_id}")


def create_dashboard(
    title: str,
    workspace_id: int,
    visual_ids: list[int],
    dataset_id: Optional[int] = None,
    description: str = "",
) -> str:
    """
    Create a CDV dashboard from a list of existing chart visual IDs.

    Visuals are automatically tiled in a 2-column grid (64-unit wide canvas,
    32 units per column, 12 rows per row).  Odd trailing visuals span the full width.

    dataset_id sets the dashboard's primary dataset context. If omitted, the first
    visual's dataset is fetched automatically. When visuals span multiple datasets,
    supply the dataset_id of the primary/most representative dataset.

    Returns the new dashboard's id, visual_id, and url.
    """
    # Auto-discover dataset_id from the first visual if not supplied
    if dataset_id is None and visual_ids:
        try:
            first_visual = json.loads(cdv_get(f"{_BASE}/{visual_ids[0]}"))
            if isinstance(first_visual, list):
                first_visual = first_visual[0]
            dataset_id = first_visual.get("dataset_id")
        except Exception:
            pass
    widgets: list[dict] = []
    for idx, vid in enumerate(visual_ids):
        row = (idx // 2) * 12
        col = (idx % 2) * 32
        is_last_odd = (idx == len(visual_ids) - 1) and (len(visual_ids) % 2 == 1)
        size_x = 64 if is_last_odd else 32
        widgets.append({
            "id": f"uri-1-widget-{vid}",
            "visual_id": vid,
            "col": col,
            "row": row,
            "size_x": size_x,
            "size_y": 12,
        })

    dashboard_data: dict = {
        "report_title": title,
        "report_subtitle": "",
        "numColumns": 64,
        "control_widgets": [],
        "global_control_widgets": [],
        "click_behavior": [],
        "metadataVersion": 1,
        "dashboard_sheets": [{
            "order": 1,
            "sheet_id": 1,
            "sheet_handle_title": "Sheet 1",
            "sheet_title": title,
            "behaviors": {},
            "visual_widgets": widgets,
            "control_widgets": [],
        }],
        "dashboard_widgets": widgets,
    }

    body: dict = {
        "title": title,
        "type": "dashboard",
        "description": description,
        "workspace_id": workspace_id,
        "data": dashboard_data,
    }
    if dataset_id is not None:
        body["dataset_id"] = dataset_id

    return _enrich_visual_response(cdv_post_admin(_BASE, body))


def create_visual(body: dict) -> str:
    """
    Create a visual using the raw admin API.
    Required body fields: title, type, dataset_id, workspace_id.
    Optional: description, data (visual spec JSON object), perm.

    If 'data' contains a valid report_data dict and CDV_USERNAME/CDV_PASSWORD are set,
    the shelf configuration is also saved via the session-based reports endpoint so the
    visual renders correctly.
    """
    result_text = _enrich_visual_response(cdv_post_admin(_BASE, body))
    try:
        result = json.loads(result_text)
        vid = result.get("visual_id") or result.get("id")
        data_spec = body.get("data", {})
        if vid and isinstance(data_spec, dict) and "report_data" in data_spec:
            cdv_save_visual_config(
                visual_id=int(vid),
                report_type=body.get("type", result.get("type", "")),
                report_data=data_spec["report_data"],
                dataset_id=int(body.get("dataset_id", result.get("dataset_id", 0))),
                workspace_id=int(body.get("workspace_id", result.get("workspace_id", 0))),
                description=body.get("description", ""),
            )
    except Exception:
        pass
    return result_text


def update_visual(object_id: int, body: dict) -> str:
    return _enrich_visual_response(cdv_post_admin(f"{_BASE}/{object_id}", body))


def delete_visual(object_id: int) -> str:
    """
    Delete a visual or dashboard by its admin API object_id.

    **WARNING — Cascade deletion:**  Deleting a ``dashboard``-type visual also
    deletes ALL chart visuals linked to it as widgets.  Save the child visual IDs
    before calling this function on any dashboard to avoid accidental data loss.
    """
    return cdv_delete(f"{_BASE}/{object_id}")


def create_smart_visual(
    dataset_id: str,
    visual_type: str,
    title: str,
    columns: list[dict],
    workspace_id: Optional[int] = None,
) -> str:
    """
    Create a CDV chart visual that reliably renders data without SQL errors.

    Only visual types and configurations that are confirmed to work via the CDV API
    are accepted.  Other visual types and aggregation patterns are blocked because
    CDV's internal SQL generator produces bracket notation that Impala cannot parse.

    Parameters
    ----------
    dataset_id : str
        ID of the dataset to visualize.  Use ``list_datasets`` to discover available
        datasets.  Always confirm with the user before choosing a dataset.
    visual_type : str
        One of the supported types: ``trellis-bars``, ``trellis-groupedbars``,
        ``pie``.  (``dashboard`` is supported by ``create_dashboard``.)

        * ``trellis-bars`` — horizontal bar chart; best for single measure vs. dimension.
        * ``trellis-groupedbars`` — grouped bars; use a single ``sum`` measure with an
          additional dimension on ``color_shelf`` for grouping.
        * ``pie`` — pie/donut chart; use a single ``sum`` measure with a dimension on
          ``color_shelf`` (added automatically if not specified).

    columns : list[dict]
        Column specifications.  Each dict must have:

        * ``column_name`` (str, required) — exact column name in the dataset.
        * ``aggregate_function`` (str, optional) — one of ``sum``, ``avg``, ``min``,
          ``max``.  Columns *without* this field are dimensions; columns *with* it are
          measures.
        * ``shelf`` (str, optional) — explicit shelf override: ``"x"``, ``"y"``,
          ``"color_shelf"``, or ``"theta_shelf"``.  Use ``color_shelf`` to split a bar
          chart by a second dimension.

        **Column compatibility rules** (CDV-side, enforced here):

        * At least one measure (column with ``aggregate_function``) is required.
        * Column names that start with an aggregate prefix (``avg_``, ``sum_``,
          ``min_``, ``max_``, ``count_``) **cannot** be used as aggregate targets —
          CDV's tokenizer confuses them with function calls.  Use a different column
          or a different aggregation.
        * Date/timestamp columns (names containing ``date``, ``time``, ``year``,
          etc.) should **not** be used as dimensions — CDV's bracket-to-backtick
          conversion fails for them.  Use CDV's interactive builder for time-series.
        * ``count`` is **not** supported — CDV wraps count arguments in brackets that
          Impala cannot parse.  Use ``sum`` on a numeric column instead.

    workspace_id : int, optional
        Required when CDV's Smart Visual API is unavailable (HTTP 404) so the fallback
        admin-API path can place the visual in the right workspace.  Use
        ``list_workspaces`` to find the correct ID.

    **Filters are not supported via this tool.**  CDV's filter SQL generator always
    produces bracket notation in the WHERE clause that Impala cannot parse.  To filter
    data on a visual, open CDV's interactive builder after creation and add filters there.

    Returns
    -------
    str
        JSON with the created visual's ``id``, ``visual_id``, and ``url``.
    """
    if not columns:
        return json.dumps({"error": "`columns` cannot be empty."})

    if visual_type not in VALID_VISUAL_TYPES or visual_type == "dashboard":
        supported = sorted(t for t in VALID_VISUAL_TYPES if t != "dashboard")
        return json.dumps({
            "error": f"Unsupported visual_type '{visual_type}'.",
            "supported_types": supported,
            "guidance": (
                "Only trellis-bars, trellis-groupedbars, and pie are confirmed to "
                "work via the API.  Other chart types require CDV's interactive "
                "builder.  Use create_dashboard to group chart visuals."
            ),
        })

    # Validate columns and enforce compatibility rules
    validated: list[dict] = []
    has_measure = False
    _DATE_KW = ("date", "time", "year", "month", "day", "week", "quarter", "timestamp", "period")

    for col in columns:
        if "column_name" not in col:
            return json.dumps({"error": f"Each column must have a 'column_name'. Got: {col}"})

        col_name: str = col["column_name"]
        agg = col.get("aggregate_function")

        if agg is not None and agg not in VALID_AGGS:
            return json.dumps({
                "error": f"Unsupported aggregate_function '{agg}'.",
                "supported": sorted(VALID_AGGS),
                "guidance": (
                    "'count' is not supported — CDV generates bracket SQL for COUNT "
                    "that Impala cannot parse.  Use 'sum' on a numeric column instead.  "
                    f"Supported aggregations: {sorted(VALID_AGGS)}"
                ),
            })

        if agg:
            has_measure = True
            # Block columns whose names start with an aggregate prefix when used as
            # aggregate targets — CDV's tokenizer confuses the name with a function call.
            col_lower = col_name.lower()
            collision = next((p for p in _AGG_PREFIX_COLLISION if col_lower.startswith(p)), None)
            if collision:
                return json.dumps({
                    "error": (
                        f"Column '{col_name}' starts with '{collision}' which collides "
                        f"with CDV's aggregate tokenizer when used as a measure target. "
                        f"CDV generates broken SQL like '{agg}([{col_name}])' for this "
                        f"combination."
                    ),
                    "guidance": (
                        "Choose a different column that does not start with an aggregate "
                        "function prefix (avg_, sum_, min_, max_, count_), or use a "
                        "different aggregation on a plain numeric column."
                    ),
                })
        else:
            # Block date/timestamp columns as dimensions — CDV's bracket conversion fails.
            col_lower = col_name.lower()
            if any(kw in col_lower for kw in _DATE_KW):
                return json.dumps({
                    "error": (
                        f"Column '{col_name}' appears to be a date/timestamp column. "
                        f"Using timestamp columns as chart dimensions via the API causes "
                        f"CDV to generate bracket SQL that Impala cannot parse."
                    ),
                    "guidance": (
                        "Time-series visuals must be configured in CDV's interactive "
                        "builder.  For non-time-series use, choose a STRING dimension "
                        "like a category or supplier name."
                    ),
                })

        entry: dict = {"column_name": col_name}
        if agg:
            entry["aggregate_function"] = agg
        shelf = col.get("shelf")
        if shelf:
            entry["shelf"] = shelf
        validated.append(entry)

    if not has_measure:
        return json.dumps({
            "error": "At least one column must have an 'aggregate_function' (measure).",
            "guidance": f"Add 'aggregate_function': 'sum' (or avg/min/max) to one of your columns. Supported: {sorted(VALID_AGGS)}",
        })

    # --- Attempt the Smart Visual API endpoint first ---
    form_data = {
        "dataset_id": str(dataset_id),
        "columns": json.dumps(validated),
        "filters": json.dumps([]),  # filters intentionally empty — see docstring
        "type": visual_type,
        "title": title,
    }
    result_text = cdv_post_form("arc/adminapi/v1/visuals/smart", data=form_data)

    try:
        result = json.loads(result_text)
    except Exception:
        return result_text

    # If the Smart Visual endpoint is not available on this instance, fall back to
    # the standard admin API and build the report_data shelf spec ourselves.
    if isinstance(result, dict) and result.get("status_code") == 404:
        if workspace_id is None:
            return json.dumps({
                "error": (
                    "Smart Visual API is not available on this CDV instance (HTTP 404). "
                    "Please provide workspace_id so the fallback admin-API path can be used."
                ),
                "hint": "Call list_workspaces() to find the correct workspace_id, then retry with workspace_id set.",
            })

        data_spec = _build_report_data(visual_type, title, validated, [])
        body: dict = {
            "title": title,
            "type": visual_type,
            "description": "",
            "dataset_id": int(dataset_id),
            "workspace_id": workspace_id,
            "data": data_spec,
        }
        result_text = cdv_post_admin(_BASE, body)
        try:
            result = json.loads(result_text)
        except Exception:
            return result_text

        # Save the shelf configuration via the session-authenticated reports endpoint.
        # The admin API creates the visual skeleton but does NOT persist shelf data.
        # cdv_save_visual_config is a no-op when CDV_USERNAME/CDV_PASSWORD are unset.
        if isinstance(result, list) and result:
            new_id = result[0].get("id")
        elif isinstance(result, dict):
            new_id = result.get("id")
        else:
            new_id = None

        if new_id:
            cdv_save_visual_config(
                visual_id=new_id,
                report_type=visual_type,
                report_data=data_spec["report_data"],
                dataset_id=int(dataset_id),
                workspace_id=workspace_id,
                description="",
            )

    # Enrich the response with a direct URL regardless of which path was taken.
    if isinstance(result, list) and result:
        result = result[0]
    if isinstance(result, dict) and "id" in result and "error" not in result:
        result["visual_id"] = result["id"]
        result["url"] = urljoin(get_base_url(), f"arc/apps/app/{result['id']}")
    return json.dumps(result)
