import json
from pathlib import Path

import pandas as pd
import pytest

from rdagent.core.experiment import Experiment, FBWorkspace, Task
from rdagent.log.ui.storage import WebStorage


class _FactorTask(Task):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description="")
        self.factor_name = name

    def get_task_information(self) -> str:
        return self.name


def _experiment_with_workspaces(tmp_path: Path) -> Experiment:
    tasks = [_FactorTask("STR_5"), _FactorTask("RVOL_20")]
    exp = Experiment(sub_tasks=tasks)
    exp.experiment_workspace = FBWorkspace()
    exp.experiment_workspace.workspace_path = tmp_path / "exp"
    for index, task in enumerate(tasks):
        ws = FBWorkspace(target_task=task)
        ws.workspace_path = tmp_path / f"factor{index}"
        exp.sub_workspace_list[index] = ws
    exp.result = pd.Series({"IC": 0.01})
    return exp


@pytest.mark.offline
def test_metric_event_carries_workspaces(tmp_path: Path) -> None:
    exp = _experiment_with_workspaces(tmp_path)
    data = WebStorage(port=1, path=tmp_path)._obj_to_json(
        obj=exp, tag="Loop_0.running", id="trace", timestamp="2026-09-14T00:00:00"
    )
    content = data["msg"]["content"]
    assert data["msg"]["tag"] == "feedback.metric"
    assert json.loads(content["result"]) == {"IC": 0.01}
    assert content["workspaces"] == {
        "experiment": str(tmp_path / "exp"),
        "factors": [
            {"name": "STR_5", "path": str(tmp_path / "factor0")},
            {"name": "RVOL_20", "path": str(tmp_path / "factor1")},
        ],
    }


@pytest.mark.offline
def test_metric_event_without_sub_workspaces(tmp_path: Path) -> None:
    exp = Experiment(sub_tasks=[])
    exp.result = pd.Series({"IC": 0.0})
    data = WebStorage(port=1, path=tmp_path)._obj_to_json(
        obj=exp, tag="Loop_0.running", id="trace", timestamp="2026-09-14T00:00:00"
    )
    assert data["msg"]["content"]["workspaces"] == {"experiment": None, "factors": []}
