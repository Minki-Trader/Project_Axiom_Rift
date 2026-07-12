from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.drawdown_state_discovery import compute_drawdown_score,drawdown_configurations,executable_configuration_map
from axiom_rift.research.drawdown_state_study import build_drawdown_validation_plan
class DrawdownStateTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(drawdown_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_drawdown_features_are_prefix_invariant(self)->None:
        rows=800;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000+np.cumsum(np.sin(np.arange(rows)/17)-.01);frame=pd.DataFrame({"time":time,"close":close});full=compute_drawdown_score(frame,"depth_duration_interaction_576");prefix=compute_drawdown_score(frame.iloc[:720].copy(),"depth_duration_interaction_576")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:720],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fourth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_drawdown_validation_plan(eid)["mission_id"],"MIS-0004")
if __name__=="__main__":unittest.main()
