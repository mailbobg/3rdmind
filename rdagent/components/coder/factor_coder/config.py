import os
import sys
from pathlib import Path
from typing import Optional

from pydantic_settings import SettingsConfigDict

from rdagent.components.coder.CoSTEER.config import CoSTEERSettings
from rdagent.utils.env import CondaConf, Env, LocalConf, LocalEnv


class FactorCoSTEERSettings(CoSTEERSettings):
    model_config = SettingsConfigDict(env_prefix="FACTOR_CoSTEER_")

    data_folder: str = "git_ignore_folder/factor_implementation_source_data"
    """Path to the folder containing financial data (default is fundamental data in Qlib)"""

    data_folder_debug: str = "git_ignore_folder/factor_implementation_source_data_debug"
    """Path to the folder containing partial financial data (for debugging)"""

    simple_background: bool = False
    """Whether to use simple background information for code feedback"""

    file_based_execution_timeout: int = 3600
    """Timeout in seconds for each factor implementation execution"""

    select_method: str = "random"
    """Method for the selection of factors implementation"""

    python_bin: str = "python"
    env_type: str = "conda"
    with_knowledge: bool = True
    knowledge_self_gen: bool = True
    """Path to the Python binary"""


def get_factor_env(
    conf_type: Optional[str] = None,
    extra_volumes: dict = {},
    running_timeout_period: int = 600,
    enable_cache: Optional[bool] = None,
) -> Env:
    conf = FactorCoSTEERSettings()
    if conf.env_type == "venv":
        env = LocalEnv(conf=LocalConf(enable_cache=False, default_entry="python main.py", bin_path=str(Path(sys.executable).parent), live_output=False))
    elif conf.env_type == "conda":
        env = LocalEnv(conf=(CondaConf(conda_env_name=os.environ.get("CONDA_DEFAULT_ENV"))))
    else:
        raise ValueError(f"Unknown factor env type: {conf.env_type}")
    env.conf.extra_volumes = extra_volumes.copy()
    env.conf.running_timeout_period = running_timeout_period
    if enable_cache is not None:
        env.conf.enable_cache = enable_cache
    env.prepare()
    return env


FACTOR_COSTEER_SETTINGS = FactorCoSTEERSettings()
