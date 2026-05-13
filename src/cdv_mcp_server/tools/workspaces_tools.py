## Copyright (c) 2025 Cloudera, Inc. All Rights Reserved.
##
## This file is licensed under the Apache License Version 2.0 (the "License").
## You may not use this file except in compliance with the License.
## You may obtain a copy of the License at http:##www.apache.org/licenses/LICENSE-2.0.
##
## This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS
## OF ANY KIND, either express or implied. Refer to the License for the specific
## permissions and limitations governing your use of the file.

from cdv_mcp_server.tools.api_client import cdv_delete, cdv_get, cdv_post_admin

_BASE = "arc/adminapi/v1/workspaces"


def list_workspaces() -> str:
    return cdv_get(_BASE)


def get_workspace(object_id: int) -> str:
    return cdv_get(f"{_BASE}/{object_id}")


def create_workspace(body: dict) -> str:
    return cdv_post_admin(_BASE, body)


def update_workspace(object_id: int, body: dict) -> str:
    return cdv_post_admin(f"{_BASE}/{object_id}", body)


def delete_workspace(object_id: int) -> str:
    return cdv_delete(f"{_BASE}/{object_id}")
