from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.liquidity_supply_discovery import compute_liquidity_score,executable_configuration_map,liquidity_configurations
from axiom_rift.research.liquidity_supply_study import build_liquidity_validation_plan
class LiquiditySupplyTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(liquidity_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_spread_state_is_prefix_invariant(self)->None:
        rows=240;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000+np.cumsum(np.sin(np.arange(rows)/7));frame=pd.DataFrame({"time":time,"open":close-0.2,"high":close+1,"low":close-1,"close":close,"spread":10+np.arange(rows)%7});full=compute_liquidity_score(frame,"spread_recovery_24");prefix=compute_liquidity_score(frame.iloc[:180].copy(),"spread_recovery_24")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:180],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_third_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_liquidity_validation_plan(eid)["mission_id"],"MIS-0003")
if __name__=="__main__":unittest.main()
