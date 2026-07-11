from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.candle_geometry_discovery import candle_configurations,compute_candle_score,executable_configuration_map
from axiom_rift.research.candle_geometry_study import build_candle_validation_plan
class CandleGeometryTests(unittest.TestCase):
    def test_surface_has_six_unique_executables(self)->None:self.assertEqual(len(candle_configurations()),6);self.assertEqual(len(executable_configuration_map()),6)
    def test_geometry_is_prefix_invariant(self)->None:
        rows=160;time=pd.date_range("2025-01-01",periods=rows,freq="5min");base=20_000+np.cumsum(np.sin(np.arange(rows)/7));frame=pd.DataFrame({"time":time,"open":base-0.2,"high":base+1.2,"low":base-1.0,"close":base+0.1});full=compute_candle_score(frame,"wick_balance_24");prefix=compute_candle_score(frame.iloc[:120].copy(),"wick_balance_24")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:120],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_third_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_candle_validation_plan(eid)["mission_id"],"MIS-0003")
if __name__=="__main__":unittest.main()
