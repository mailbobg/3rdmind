from typing import Optional

from pydantic_settings import SettingsConfigDict

from rdagent.components.workflow.conf import BasePropSetting


class ModelBasePropSetting(BasePropSetting):
    model_config = SettingsConfigDict(env_prefix="QLIB_MODEL_", protected_namespaces=())


    market: str = "csi300"
    """Qlib instrument universe the experiments train and backtest on (an instruments/*.txt name)"""

    benchmark: str = "SH000300"
    """Benchmark index for the backtest report"""

    region: str = "cn"
    """Qlib region of the data (cn / us): trading calendar and default exchange rules"""

    provider_uri: str = "~/.qlib/qlib_data/cn_data"
    """Qlib data directory the experiments read"""

    limit_threshold: str = "0.095"
    """Price-limit rule for the backtest exchange (rendered into the Qlib yaml; "null" for markets without one)"""

    open_cost: str = "0.0005"
    close_cost: str = "0.0015"
    """Backtest commission rates rendered into the Qlib yaml (A-share defaults; the Studio sets them per market)"""

    lgb_lambda_l1: str = "205.6999"
    lgb_lambda_l2: str = "580.9768"
    """LightGBM leaf penalties of the factor-evaluation model. Tuned for CSI300; a smaller universe has fewer
    rows per leaf, so a penalty this size leaves no split and the model predicts a constant."""

    n_jobs: str = "20"
    """DataLoader worker processes of the PyTorch model (GeneralPTNN ``n_jobs``). 20 suits the Docker image;
    on macOS the forked workers crash the training with a segmentation fault, so the Studio sets 0 there."""
    # 1) override base settings
    scen: str = "rdagent.scenarios.qlib.experiment.model_experiment.QlibModelScenario"
    """Scenario class for Qlib Model"""

    hypothesis_gen: str = "rdagent.scenarios.qlib.proposal.model_proposal.QlibModelHypothesisGen"
    """Hypothesis generation class"""

    hypothesis2experiment: str = "rdagent.scenarios.qlib.proposal.model_proposal.QlibModelHypothesis2Experiment"
    """Hypothesis to experiment class"""

    coder: str = "rdagent.scenarios.qlib.developer.model_coder.QlibModelCoSTEER"
    """Coder class"""

    runner: str = "rdagent.scenarios.qlib.developer.model_runner.QlibModelRunner"
    """Runner class"""

    summarizer: str = "rdagent.scenarios.qlib.developer.feedback.QlibModelExperiment2Feedback"
    """Summarizer class"""

    evolving_n: int = 10
    """Number of evolutions"""

    train_start: str = "2008-01-01"
    """Start date of the training segment"""

    train_end: str = "2014-12-31"
    """End date of the training segment"""

    valid_start: str = "2015-01-01"
    """Start date of the validation segment"""

    valid_end: str = "2016-12-31"
    """End date of the validation segment"""

    test_start: str = "2017-01-01"
    """Start date of the test / backtest segment"""

    test_end: Optional[str] = "2020-08-01"
    """End date of the test / backtest segment"""


class FactorBasePropSetting(BasePropSetting):
    model_config = SettingsConfigDict(env_prefix="QLIB_FACTOR_", protected_namespaces=())


    market: str = "csi300"
    """Qlib instrument universe the experiments train and backtest on (an instruments/*.txt name)"""

    benchmark: str = "SH000300"
    """Benchmark index for the backtest report"""

    region: str = "cn"
    """Qlib region of the data (cn / us): trading calendar and default exchange rules"""

    provider_uri: str = "~/.qlib/qlib_data/cn_data"
    """Qlib data directory the experiments read"""

    limit_threshold: str = "0.095"
    """Price-limit rule for the backtest exchange (rendered into the Qlib yaml; "null" for markets without one)"""

    open_cost: str = "0.0005"
    close_cost: str = "0.0015"
    """Backtest commission rates rendered into the Qlib yaml (A-share defaults; the Studio sets them per market)"""

    lgb_lambda_l1: str = "205.6999"
    lgb_lambda_l2: str = "580.9768"
    """LightGBM leaf penalties of the factor-evaluation model. Tuned for CSI300; a smaller universe has fewer
    rows per leaf, so a penalty this size leaves no split and the model predicts a constant."""

    n_jobs: str = "20"
    """DataLoader worker processes of the PyTorch model (GeneralPTNN ``n_jobs``). 20 suits the Docker image;
    on macOS the forked workers crash the training with a segmentation fault, so the Studio sets 0 there."""
    # 1) override base settings
    scen: str = "rdagent.scenarios.qlib.experiment.factor_experiment.QlibFactorScenario"
    """Scenario class for Qlib Factor"""

    hypothesis_gen: str = "rdagent.scenarios.qlib.proposal.factor_proposal.QlibFactorHypothesisGen"
    """Hypothesis generation class"""

    hypothesis2experiment: str = "rdagent.scenarios.qlib.proposal.factor_proposal.QlibFactorHypothesis2Experiment"
    """Hypothesis to experiment class"""

    coder: str = "rdagent.scenarios.qlib.developer.factor_coder.QlibFactorCoSTEER"
    """Coder class"""

    runner: str = "rdagent.scenarios.qlib.developer.factor_runner.QlibFactorRunner"
    """Runner class"""

    summarizer: str = "rdagent.scenarios.qlib.developer.feedback.QlibFactorExperiment2Feedback"
    """Summarizer class"""

    evolving_n: int = 10
    """Number of evolutions"""

    train_start: str = "2008-01-01"
    """Start date of the training segment"""

    train_end: str = "2014-12-31"
    """End date of the training segment"""

    valid_start: str = "2015-01-01"
    """Start date of the validation segment"""

    valid_end: str = "2016-12-31"
    """End date of the validation segment"""

    test_start: str = "2017-01-01"
    """Start date of the test / backtest segment"""

    test_end: Optional[str] = "2020-08-01"
    """End date of the test / backtest segment"""


class FactorFromReportPropSetting(FactorBasePropSetting):
    # 1) override the scen attribute
    scen: str = "rdagent.scenarios.qlib.experiment.factor_from_report_experiment.QlibFactorFromReportScenario"
    """Scenario class for Qlib Factor from Report"""

    # 2) sub task specific:
    report_result_json_file_path: str = "git_ignore_folder/report_list.json"
    """Path to the JSON file listing research reports for factor extraction"""

    max_factors_per_exp: int = 6
    """Maximum number of factors implemented per experiment"""

    report_limit: int = 20
    """Maximum number of reports to process"""


class QuantBasePropSetting(BasePropSetting):
    model_config = SettingsConfigDict(env_prefix="QLIB_QUANT_", protected_namespaces=())


    market: str = "csi300"
    """Qlib instrument universe the experiments train and backtest on (an instruments/*.txt name)"""

    benchmark: str = "SH000300"
    """Benchmark index for the backtest report"""

    region: str = "cn"
    """Qlib region of the data (cn / us): trading calendar and default exchange rules"""

    provider_uri: str = "~/.qlib/qlib_data/cn_data"
    """Qlib data directory the experiments read"""

    limit_threshold: str = "0.095"
    """Price-limit rule for the backtest exchange (rendered into the Qlib yaml; "null" for markets without one)"""

    open_cost: str = "0.0005"
    close_cost: str = "0.0015"
    """Backtest commission rates rendered into the Qlib yaml (A-share defaults; the Studio sets them per market)"""

    lgb_lambda_l1: str = "205.6999"
    lgb_lambda_l2: str = "580.9768"
    """LightGBM leaf penalties of the factor-evaluation model. Tuned for CSI300; a smaller universe has fewer
    rows per leaf, so a penalty this size leaves no split and the model predicts a constant."""

    n_jobs: str = "20"
    """DataLoader worker processes of the PyTorch model (GeneralPTNN ``n_jobs``). 20 suits the Docker image;
    on macOS the forked workers crash the training with a segmentation fault, so the Studio sets 0 there."""
    # 1) override base settings
    scen: str = "rdagent.scenarios.qlib.experiment.quant_experiment.QlibQuantScenario"
    """Scenario class for Qlib Model"""

    quant_hypothesis_gen: str = "rdagent.scenarios.qlib.proposal.quant_proposal.QlibQuantHypothesisGen"
    """Hypothesis generation class"""

    model_hypothesis2experiment: str = "rdagent.scenarios.qlib.proposal.model_proposal.QlibModelHypothesis2Experiment"
    """Hypothesis to experiment class"""

    model_coder: str = "rdagent.scenarios.qlib.developer.model_coder.QlibModelCoSTEER"
    """Coder class"""

    model_runner: str = "rdagent.scenarios.qlib.developer.model_runner.QlibModelRunner"
    """Runner class"""

    model_summarizer: str = "rdagent.scenarios.qlib.developer.feedback.QlibModelExperiment2Feedback"
    """Summarizer class"""

    factor_hypothesis2experiment: str = (
        "rdagent.scenarios.qlib.proposal.factor_proposal.QlibFactorHypothesis2Experiment"
    )
    """Hypothesis to experiment class"""

    factor_coder: str = "rdagent.scenarios.qlib.developer.factor_coder.QlibFactorCoSTEER"
    """Coder class"""

    factor_runner: str = "rdagent.scenarios.qlib.developer.factor_runner.QlibFactorRunner"
    """Runner class"""

    factor_summarizer: str = "rdagent.scenarios.qlib.developer.feedback.QlibFactorExperiment2Feedback"
    """Summarizer class"""

    evolving_n: int = 10
    """Number of evolutions"""

    action_selection: str = "bandit"
    """Action selection strategy: 'bandit' for bandit-based selection, 'llm' for LLM-based selection, 'random' for random selection"""

    train_start: str = "2008-01-01"
    """Start date of the training segment"""

    train_end: str = "2014-12-31"
    """End date of the training segment"""

    valid_start: str = "2015-01-01"
    """Start date of the validation segment"""

    valid_end: str = "2016-12-31"
    """End date of the validation segment"""

    test_start: str = "2017-01-01"
    """Start date of the test / backtest segment"""

    test_end: Optional[str] = "2020-08-01"
    """End date of the test / backtest segment"""


FACTOR_PROP_SETTING = FactorBasePropSetting()
FACTOR_FROM_REPORT_PROP_SETTING = FactorFromReportPropSetting()
MODEL_PROP_SETTING = ModelBasePropSetting()
QUANT_PROP_SETTING = QuantBasePropSetting()
