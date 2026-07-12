from __future__ import annotations
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from axiom_rift.research.analog_state_discovery import analog_configurations,executable_configuration_map,fit_fold_analog
from axiom_rift.research.analog_state_study import build_analog_validation_plan
from axiom_rift.research.data import load_observed_development
class AnalogStateTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:self.assertEqual(len(analog_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_fold_analog_is_prefix_invariant(self)->None:
        frame=load_observed_development(Path(__file__).resolve().parents[2]).frame;time=pd.to_datetime(frame["time"]);start=time.iloc[500];end=time.iloc[10000];full=fit_fold_analog(frame.iloc[:15000].copy(),"knn_return_magnitude_control_15",start,end);prefix=fit_fold_analog(frame.iloc[:14000].copy(),"knn_return_magnitude_control_15",start,end)
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:14000],right,rtol=0,atol=0,equal_nan=True)
    def test_plan_is_fifth_mission_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_analog_validation_plan(eid)["mission_id"],"MIS-0005")
if __name__=="__main__":unittest.main()
