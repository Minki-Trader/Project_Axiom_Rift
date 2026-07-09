#ifndef AXIOM_V2_FEATURES_MQH
#define AXIOM_V2_FEATURES_MQH

#define AXIOM_V2_FEATURE_COUNT 12
#define AXIOM_V2_WARMUP_BARS 48

string AxiomV2FeatureOrderHash()
{
   return "36c24bfec2f73634af87daaa9906d597f8502c743c40c581f4eb91b61006ef29";
}

double AxiomV2TrueRange(const MqlRates &bars[], const int index)
{
   double high_low = bars[index].high - bars[index].low;
   double high_close = MathAbs(bars[index].high - bars[index - 1].close);
   double low_close = MathAbs(bars[index].low - bars[index - 1].close);
   return MathMax(high_low, MathMax(high_close, low_close));
}

double AxiomV2MeanTrueRange(const MqlRates &bars[], const int current, const int window)
{
   double total = 0.0;
   for(int index = current - window + 1; index <= current; index++)
      total += AxiomV2TrueRange(bars, index);
   return total / window;
}

double AxiomV2ReturnStd(const MqlRates &bars[], const int current, const int window)
{
   double mean = 0.0;
   for(int index = current - window + 1; index <= current; index++)
      mean += MathLog(bars[index].close / bars[index - 1].close);
   mean /= window;
   double variance = 0.0;
   for(int index = current - window + 1; index <= current; index++)
   {
      double value = MathLog(bars[index].close / bars[index - 1].close);
      variance += (value - mean) * (value - mean);
   }
   return MathSqrt(variance / window);
}

bool AxiomV2ComputeFeatures(
   const MqlRates &bars[],
   const int current,
   float &features[],
   string &reason
)
{
   ArrayResize(features, AXIOM_V2_FEATURE_COUNT);
   if(current < AXIOM_V2_WARMUP_BARS || current >= ArraySize(bars))
   {
      reason = "warmup";
      return false;
   }
   double average_range = AxiomV2MeanTrueRange(bars, current, 24);
   double bar_range = bars[current].high - bars[current].low;
   if(average_range <= 0.0 || bar_range <= 0.0)
   {
      reason = "invalid_range";
      return false;
   }
   double volume_mean = 0.0;
   for(int index = current - 47; index <= current; index++)
      volume_mean += (double)bars[index].tick_volume;
   volume_mean /= 48.0;
   double volume_variance = 0.0;
   for(int index = current - 47; index <= current; index++)
   {
      double delta = (double)bars[index].tick_volume - volume_mean;
      volume_variance += delta * delta;
   }
   double volume_std = MathSqrt(volume_variance / 48.0);
   if(volume_std <= 0.0)
   {
      reason = "zero_tick_volume_scale";
      return false;
   }
   double spread_mean = 0.0;
   for(int index = current - 23; index <= current; index++)
   {
      if(bars[index].spread <= 0)
      {
         reason = "unknown_cost_zero_spread";
         return false;
      }
      spread_mean += (double)bars[index].spread;
   }
   spread_mean /= 24.0;
   MqlDateTime time_parts;
   TimeToStruct(bars[current].time + 300 - 7 * 3600, time_parts);
   double minute = time_parts.hour * 60.0 + time_parts.min;
   double angle = 6.2831853071795864769 * minute / 1440.0;
   features[0] = (float)MathLog(bars[current].close / bars[current - 1].close);
   features[1] = (float)MathLog(bars[current].close / bars[current - 3].close);
   features[2] = (float)MathLog(bars[current].close / bars[current - 12].close);
   features[3] = (float)AxiomV2ReturnStd(bars, current, 12);
   features[4] = (float)AxiomV2ReturnStd(bars, current, 48);
   features[5] = (float)(AxiomV2TrueRange(bars, current) / average_range);
   features[6] = (float)(MathAbs(bars[current].close - bars[current].open) / average_range);
   features[7] = (float)((bars[current].close - bars[current].low) / bar_range);
   features[8] = (float)(((double)bars[current].tick_volume - volume_mean) / volume_std);
   features[9] = (float)((double)bars[current].spread / spread_mean);
   features[10] = (float)MathSin(angle);
   features[11] = (float)MathCos(angle);
   for(int index = 0; index < AXIOM_V2_FEATURE_COUNT; index++)
   {
      if(!MathIsValidNumber((double)features[index]))
      {
         reason = "nonfinite_feature";
         return false;
      }
   }
   reason = "ok";
   return true;
}

#endif
