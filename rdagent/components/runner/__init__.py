from rdagent.core.developer import Developer
from rdagent.core.experiment import ASpecificExp, Experiment
from rdagent.oai.llm_utils import md5_hash


class CachedRunner(Developer[ASpecificExp]):
    def get_cache_key(self, exp: Experiment) -> str:
        all_tasks = []
        for based_exp in exp.based_experiments:
            all_tasks.extend(based_exp.sub_tasks)
        all_tasks.extend(exp.sub_tasks)
        task_info_list = [task.get_task_information() for task in all_tasks]
        task_info_str = "\n".join(task_info_list)
        # Runners whose results depend on the data they ran on (market, region, data directory) add that
        # scope here, so the same factor evaluated on two markets never shares a cache entry.
        scope = getattr(self, "cache_scope", "")
        return md5_hash(task_info_str + (f"\n@{scope}" if scope else ""))

    def assign_cached_result(self, exp: Experiment, cached_res: Experiment) -> Experiment:
        if exp.based_experiments and exp.based_experiments[-1].result is None:
            exp.based_experiments[-1].result = cached_res.based_experiments[-1].result
        exp.result = cached_res.result
        return exp
