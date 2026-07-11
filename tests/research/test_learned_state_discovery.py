from __future__ import annotations
import unittest
from pathlib import Path
import pandas as pd
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.learned_state_discovery import executable_configuration_map,fit_fold_model,learned_configurations
from axiom_rift.research.learned_state_study import build_learned_validation_plan
class LearnedStateTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(learned_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_fold_model_is_prefix_invariant(self)->None:
        frame=load_observed_development(Path(__file__).resolve().parents[2]).frame;time=pd.to_datetime(frame["time"]);start=time.iloc[500];end=time.iloc[5000];full=fit_fold_model(frame.iloc[:8000].copy(),"ridge_interaction",start,end);prefix=fit_fold_model(frame.iloc[:7000].copy(),"ridge_interaction",start,end)
        import numpy as np
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:7000],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_third_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_learned_validation_plan(eid)["mission_id"],"MIS-0003")
if __name__=="__main__":unittest.main()
