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

from cdv_mcp_server.tools.api_client import cdv_get, cdv_post_multipart


def export_migration() -> str:
    """Export all CDV visual artifacts as a migration bundle (JSON)."""
    return cdv_get("arc/migration/api/export")


def import_migration(dataconnection_name: str, json_data: str | None = None, sanity_check: bool = True) -> str:
    """
    Import a CDV migration bundle.

    Args:
        dataconnection_name: Name of the data connection to associate imported artifacts with.
        json_data: Stringified JSON migration payload (alternative to uploading a file).
        sanity_check: Whether to run sanity checks before import (default True).
    """
    fields: dict = {
        "dataconnection_name": dataconnection_name,
        "sanity_check": "true" if sanity_check else "false",
    }
    if json_data is not None:
        fields["json_data"] = json_data
    return cdv_post_multipart("arc/migration/api/import", fields=fields)
