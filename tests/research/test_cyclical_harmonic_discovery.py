from __future__ import annotations
import unittest
import numpy as np
import pandas as pd
from axiom_rift.research.cyclical_harmonic_discovery import compute_harmonic_score,harmonic_configurations,executable_configuration_map
from axiom_rift.research.cyclical_harmonic_study import build_harmonic_validation_plan
class CyclicalHarmonicTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self)->None:
        self.assertEqual(len(harmonic_configurations()),4);self.assertEqual(len(executable_configuration_map()),4)
    def test_harmonic_agreement_is_prefix_invariant(self)->None:
        rows=200;time=pd.date_range("2025-01-01",periods=rows,freq="5min");close=20_000.0*np.exp(np.cumsum(0.001*np.sin(2*np.pi*np.arange(rows)/24)));frame=pd.DataFrame({"time":time,"open":close-0.2,"high":close+1.0,"low":close-1.0,"close":close});full=compute_harmonic_score(frame,"harmonic_agreement");prefix=compute_harmonic_score(frame.iloc[:160].copy(),"harmonic_agreement")
        for left,right in zip(full,prefix,strict=True):np.testing.assert_allclose(left[:160],right,rtol=0.0,atol=0.0,equal_nan=True)
    def test_plan_is_successor_bound(self)->None:
        eid=next(iter(executable_configuration_map()));self.assertEqual(build_harmonic_validation_plan(eid)["mission_id"],"MIS-0002")
if __name__=="__main__":unittest.main()
