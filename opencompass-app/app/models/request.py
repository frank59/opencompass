from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelItem(BaseModel):
    """单个模型配置。type 在白名单内；path 为模型名；其他字段透传给 OC 类初始化。"""
    type: str
    path: str
    model_config = ConfigDict(extra="allow")


class DatasetItem(BaseModel):
    """单个数据集配置。
    - 内置数据集：仅含 abbr。
    - 自定义数据集：含 type/path/reader_cfg/infer_cfg/eval_cfg。
    """
    abbr: str
    type: str | None = None
    path: str | None = None
    reader_cfg: dict[str, Any] | None = None
    infer_cfg: dict[str, Any] | None = None
    eval_cfg: dict[str, Any] | None = None


class CreateJobRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=64)
    datasets: list[DatasetItem] = Field(min_length=1)
    models: list[ModelItem] = Field(min_length=1)
    priority: int = 5
    max_runtime_seconds: int = 7200
    created_by: str | None = None
