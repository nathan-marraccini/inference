from enum import Enum
from typing import Any, Callable, Type, Union

import requests
from requests import Response

from inference.core import logger
from inference.core.entities.types import (
    DatasetID,
    ModelType,
    TaskType,
    VersionID,
    WorkspaceID,
)
from inference.core.env import API_BASE_URL
from inference.core.exceptions import (
    DatasetLoadError,
    MalformedRoboflowAPIResponseError,
    MissingDefaultModelError,
    ModelDataFetchingError,
    RoboflowAPIConnectionError,
    RoboflowAPIRequestError,
    WorkspaceLoadError,
)
from inference.core.utils.url_utils import wrap_url

MODEL_TYPE_DEFAULTS = {
    "object-detection": "yolov5v2s",
    "instance-segmentation": "yolact",
    "classification": "vit",
}
PROJECT_TASK_TYPE_KEY = "project_task_type"
MODEL_TYPE_KEY = "model_type"


def wrap_roboflow_api_errors(
    on_connection_error: Callable[
        [Union[requests.exceptions.ConnectionError, ConnectionError]], None
    ],
    on_http_error: Callable[[Union[requests.exceptions.HTTPError]], None],
) -> callable:
    def decorator(function: callable) -> callable:
        def wrapper(*args, **kwargs) -> Any:
            try:
                return function(*args, **kwargs)
            except (requests.exceptions.ConnectionError, ConnectionError) as error:
                logger.error(f"Could not connect to Roboflow API. Error: {error}")
                on_connection_error(error)
            except requests.exceptions.HTTPError as error:
                logger.error(
                    f"HTTP error encountered while requesting Roboflow API response: {error}"
                )
                on_http_error(error)
            except requests.exceptions.InvalidJSONError as error:
                logger.error(
                    f"Could not decode JSON response from Roboflow API. Error: {error}."
                )
                raise MalformedRoboflowAPIResponseError(
                    "Could not decode JSON response from Roboflow API."
                ) from error

        return wrapper

    return decorator


def raise_from_lambda(
    inner_error: Exception, exception_type: Type[Exception], message: str
) -> None:
    raise exception_type(message) from inner_error


@wrap_roboflow_api_errors(
    on_connection_error=lambda e: raise_from_lambda(
        e, RoboflowAPIConnectionError, "Could not connect to Roboflow API."
    ),
    on_http_error=lambda e: raise_from_lambda(
        e, WorkspaceLoadError, "Could not load workspace, check your API key"
    ),
)
def get_roboflow_workspace(api_key: str) -> WorkspaceID:
    api_url = wrap_url("/".join([API_BASE_URL, f"?api_key={api_key}"]))
    api_key_info = requests.get(api_url)
    api_key_info.raise_for_status()
    workspace_id = api_key_info.json().get("workspace")
    if workspace_id is None:
        raise WorkspaceLoadError(f"Empty workspace encountered, check your API key.")
    return workspace_id


@wrap_roboflow_api_errors(
    on_connection_error=lambda e: raise_from_lambda(
        e, RoboflowAPIConnectionError, "Could not connect to Roboflow API."
    ),
    on_http_error=lambda e: raise_from_lambda(
        e,
        DatasetLoadError,
        "Could not load dataset info, check your API key and workspace.",
    ),
)
def get_roboflow_dataset_type(
    api_key: str, workspace_id: WorkspaceID, dataset_id: DatasetID
) -> TaskType:
    api_url = wrap_url(
        "/".join(
            [API_BASE_URL, workspace_id, dataset_id, f"?api_key={api_key}&nocache=true"]
        )
    )
    dataset_info = requests.get(api_url)
    dataset_info.raise_for_status()
    project_task_type = dataset_info.json().get("project", {})
    if "type" not in project_task_type:
        logger.warning(
            f"Project task type not defined for workspace={workspace_id} and dataset={dataset_id}, defaulting "
            f"to object-detection."
        )
    return project_task_type.get("type", "object-detection")


@wrap_roboflow_api_errors(
    on_connection_error=lambda e: raise_from_lambda(
        e, RoboflowAPIConnectionError, "Could not connect to Roboflow API."
    ),
    on_http_error=lambda e: raise_from_lambda(
        e,
        DatasetLoadError,
        "Could not load version info, check your API key and workspace.",
    ),
)
def get_roboflow_model_type(
    api_key: str,
    workspace_id: WorkspaceID,
    dataset_id: DatasetID,
    version_id: VersionID,
    project_task_type: ModelType,
) -> ModelType:
    api_url = wrap_url(
        "/".join(
            [
                API_BASE_URL,
                workspace_id,
                dataset_id,
                version_id,
                f"?api_key={api_key}&nocache=true",
            ]
        )
    )
    version_info = requests.get(api_url)
    version_info.raise_for_status()
    model_type = version_info.json()["version"]
    if "modelType" not in model_type:
        if project_task_type not in MODEL_TYPE_DEFAULTS:
            raise MissingDefaultModelError(
                f"Could not set default model for {project_task_type}"
            )
        logger.warning(
            f"Model type not defined - using default for {project_task_type} task."
        )
    return model_type.get("modelType", MODEL_TYPE_DEFAULTS[project_task_type])


class ModelEndpointType(Enum):
    ORT = "ort"
    CORE_MODEL = "core_model"


def handle_model_data_fetching_error(error: requests.exceptions.HTTPError) -> None:
    message = f"An error occurred when calling the Roboflow API to acquire the model artifacts."
    try:
        response_error = error.response.json().get("error")
        if response_error is not None:
            message = f"{message} The error was: {error}."
    except Exception:
        pass
    raise ModelDataFetchingError(message) from error


@wrap_roboflow_api_errors(
    on_connection_error=lambda e: raise_from_lambda(
        e, RoboflowAPIConnectionError, "Could not connect to Roboflow API."
    ),
    on_http_error=handle_model_data_fetching_error,
)
def get_roboflow_model_data(
    api_key: str,
    model_id: str,
    endpoint_type: ModelEndpointType,
    device_id: str,
) -> dict:
    api_url = wrap_url(
        f"{API_BASE_URL}/{endpoint_type.value}/{model_id}?api_key={api_key}&device={device_id}&nocache=true&dynamic=true"
    )
    model_data = requests.get(api_url)
    model_data.raise_for_status()
    return model_data.json()


@wrap_roboflow_api_errors(
    on_connection_error=lambda e: raise_from_lambda(
        e, RoboflowAPIConnectionError, "Could not connect to Roboflow API."
    ),
    on_http_error=lambda e: raise_from_lambda(
        e, RoboflowAPIRequestError, "Could not execute GET request to Roboflow API."
    ),
)
def get_from_roboflow_api(
    url: str, json_response: bool = False
) -> Union[Response, dict]:
    response = requests.get(wrap_url(url))
    if json_response:
        return response.json()
    return response
