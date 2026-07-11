from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.path_roughness_discovery import compute_roughness_score,executable_configuration_map,path_roughness_configurations
from axiom_rift.research.path_roughness_study import build_path_roughness_validation_plan
class PathRoughnessDiscoveryTests(unittest.TestCase):
    def test_surface_has_twelve_unique_executables(self)->None:
        self.assertEqual(len(path_roughness_configurations()),12);self.assertEqual(len(executable_configuration_map()),12)
    def test_roughness_is_prefix_invariant(self)->None:
        rows=190;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000.0+np.cumsum(np.sin(np.arange(rows)/8.0)+0.1);frame=pd.DataFrame({"time":time,"open":close-0.2,"high":close+1.0,"low":close-1.0,"close":close});full=compute_roughness_score(frame,feature_kind="roughness",lookback=48);prefix=compute_roughness_score(frame.iloc[:150].copy(),feature_kind="roughness",lookback=48)
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:150],right,rtol=0.0,atol=0.0,equal_nan=True)
    def test_plan_is_successor_bound(self)->None:
        eid=next(iter(executable_configuration_map()));plan=build_path_roughness_validation_plan(eid);self.assertEqual(plan["mission_id"],"MIS-0002");self.assertFalse(plan["candidate_eligible_on_pass"])
if __name__=="__main__":unittest.main()
