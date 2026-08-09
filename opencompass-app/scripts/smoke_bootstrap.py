"""Smoke test bootstrap: 预填白名单 + 启动 uvicorn。

仅用于开发期验证全链路。在生产环境 OC 完整安装后不需要此脚本。
"""
import os
import sys


def _bootstrap_whitelist():
    """预填白名单（MVP 环境缺 mmengine 导致动态扫描回退 empty）。"""
    from app.core.model_whitelist import ModelWhitelist
    ModelWhitelist._TYPES = frozenset({
        "opencompass.models.openai_api.OpenAISDK",
        "opencompass.models.huggingface.HuggingFace",
        "opencompass.models.huggingface_above_v4_33.HuggingFaceAboveV4_33",
    })
    print(f"[smoke-bootstrap] model whitelist preset: {len(ModelWhitelist._TYPES)} types")


def main():
    os.environ.setdefault("INSTANCE_ID", "smoke-dev")
    os.environ.setdefault("PORT", "8080")
    os.environ.setdefault("OC_DATA_ROOT", "/tmp/opencompass-dev")
    os.environ.setdefault("MAX_CONCURRENT", "4")
    os.environ.setdefault("LOG_LEVEL", "INFO")

    _bootstrap_whitelist()

    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ["PORT"]),
        reload=False,
    )


if __name__ == "__main__":
    sys.exit(main())
