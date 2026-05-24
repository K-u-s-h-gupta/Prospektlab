"""Download TimesFM 2.5 200M model weights from HuggingFace at Docker build time."""
import os
import sys

from huggingface_hub import snapshot_download
from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError

token = os.environ.get("HF_TOKEN")
cache_dir = os.environ.get("HF_HOME", "/app/.cache/huggingface")

try:
    snapshot_download(
        repo_id="google/timesfm-2.5-200m-pytorch",
        cache_dir=cache_dir,
        token=token,
        local_files_only=False,
    )
    print("SUCCESS: model files baked into image", file=sys.stderr)
except GatedRepoError:
    print(
        "ERROR: Gated repository. Accept terms at "
        "https://huggingface.co/google/timesfm-2.5-200m-pytorch "
        "and provide HF_TOKEN.",
        file=sys.stderr,
    )
    sys.exit(1)
except RepositoryNotFoundError:
    print(
        "ERROR: Repository not found or no access.",
        file=sys.stderr,
    )
    sys.exit(1)
