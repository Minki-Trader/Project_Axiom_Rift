from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.adaptive_lifecycle_discovery import adaptive_lifecycle_configurations,compute_entry_score,executable_configuration_map
from axiom_rift.research.adaptive_lifecycle_study import build_adaptive_lifecycle_validation_plan
class AdaptiveLifecycleTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(adaptive_lifecycle_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_shared_entry_feature_is_prefix_invariant(self)->None:
        rows=1000;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000+np.cumsum(np.sin(np.arange(rows)/17)+0.1);frame=pd.DataFrame({"time":time,"close":close});full=compute_entry_score(frame,"opposite_state_exit_96");control=compute_entry_score(frame,"fixed_hold_control_96");prefix=compute_entry_score(frame.iloc[:900].copy(),"opposite_state_exit_96")
        for left,right in zip(full,control,strict=True):np.testing.assert_allclose(left,right,rtol=0,atol=0,equal_nan=True)
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:900],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fifth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_adaptive_lifecycle_validation_plan(eid)["mission_id"],"MIS-0005")
if __name__=="__main__":unittest.main()
