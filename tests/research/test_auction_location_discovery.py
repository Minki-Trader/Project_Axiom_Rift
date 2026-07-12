from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.auction_location_discovery import auction_configurations,compute_auction_score,executable_configuration_map
from axiom_rift.research.auction_location_study import build_auction_validation_plan
class AuctionLocationTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(auction_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_feature_is_prefix_invariant(self)->None:
        rows=1800;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000+np.cumsum(np.sin(np.arange(rows)/19)+0.05);frame=pd.DataFrame({"time":time,"open":close-0.2,"high":close+1,"low":close-1,"close":close});full=compute_auction_score(frame,"prior_day_range_location");prefix=compute_auction_score(frame.iloc[:1600].copy(),"prior_day_range_location")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:1600],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fifth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_auction_validation_plan(eid)["mission_id"],"MIS-0005")
if __name__=="__main__":unittest.main()
