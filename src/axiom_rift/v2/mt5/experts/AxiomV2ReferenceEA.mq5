#property strict
#property version "2.00"

#include <Trade/Trade.mqh>
#include "..\include\AxiomV2Features.mqh"
#include "..\include\AxiomV2Onnx.mqh"

#resource "\\Experts\\AxiomRiftV2\\models\\axiom_v2_reference.onnx" as uchar AxiomV2Model[]

input string InpMode = "fixture";
input string InpFixturePath = "AxiomRiftV2\\fixture_bars.csv";
input string InpFixtureOutputPath = "AxiomRiftV2\\fixture_actual.csv";
input string InpStatusPath = "AxiomRiftV2\\status.csv";
input string InpDecisionLogPath = "AxiomRiftV2\\online_decisions.csv";
input string InpExpectedFeatureOrderHash = "36c24bfec2f73634af87daaa9906d597f8502c743c40c581f4eb91b61006ef29";
input double InpScoreThreshold = 0.25;
input int InpHoldBars = 6;
input int InpMaxDailyEntries = 10;
input bool InpDryRun = true;
input double InpLot = 0.01;
input long InpMagic = 2200001;

CTrade g_trade;
CAxiomV2Onnx g_model;
datetime g_last_bar_time = 0;
datetime g_entry_signal_time = 0;
int g_active_direction = 0;
int g_bars_held = 0;
int g_daily_entries = 0;
string g_market_day = "";
bool g_fixture_complete = false;

void EnsureFolders()
{
   FolderCreate("AxiomRiftV2", FILE_COMMON);
}

void WriteStatus(const string status, const string detail)
{
   EnsureFolders();
   int handle = FileOpen(InpStatusPath, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(handle == INVALID_HANDLE)
      return;
   FileWrite(handle, "field", "value");
   FileWrite(handle, "status", status);
   FileWrite(handle, "detail", detail);
   FileWrite(handle, "mode", InpMode);
   FileWrite(handle, "feature_order_sha256", AxiomV2FeatureOrderHash());
   FileWrite(handle, "model_runtime", "mql5_native_onnx");
   FileWrite(handle, "dry_run", InpDryRun ? "true" : "false");
   FileClose(handle);
}

int RawDirection(const float score)
{
   if(score > (float)InpScoreThreshold)
      return 1;
   if(score < (float)(-InpScoreThreshold))
      return -1;
   return 0;
}

string MarketDay(const datetime bar_open_time)
{
   return TimeToString(bar_open_time + 300 - 7 * 3600, TIME_DATE);
}

bool LoadFixture(MqlRates &bars[])
{
   int handle = FileOpen(InpFixturePath, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(handle == INVALID_HANDLE)
      return false;
   for(int column = 0; column < 8; column++)
      FileReadString(handle);
   ArrayResize(bars, 0);
   while(!FileIsEnding(handle))
   {
      string time_text = FileReadString(handle);
      if(time_text == "")
         break;
      int size = ArraySize(bars);
      ArrayResize(bars, size + 1);
      bars[size].time = StringToTime(time_text);
      bars[size].open = StringToDouble(FileReadString(handle));
      bars[size].high = StringToDouble(FileReadString(handle));
      bars[size].low = StringToDouble(FileReadString(handle));
      bars[size].close = StringToDouble(FileReadString(handle));
      bars[size].tick_volume = (long)StringToInteger(FileReadString(handle));
      bars[size].spread = (int)StringToInteger(FileReadString(handle));
      bars[size].real_volume = (long)StringToInteger(FileReadString(handle));
   }
   FileClose(handle);
   return ArraySize(bars) > AXIOM_V2_WARMUP_BARS;
}

void WriteFixtureHeader(const int handle)
{
   FileWrite(
      handle,
      "index", "time",
      "f0", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11",
      "score", "raw_direction", "admitted_direction", "active_direction", "event"
   );
}

bool RunFixture()
{
   MqlRates bars[];
   if(!LoadFixture(bars))
   {
      WriteStatus("fixture_failed", "fixture_load_failed");
      return false;
   }
   int output = FileOpen(InpFixtureOutputPath, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(output == INVALID_HANDLE)
   {
      WriteStatus("fixture_failed", "fixture_output_open_failed");
      return false;
   }
   WriteFixtureHeader(output);
   int active_direction = 0;
   int entry_signal_index = -1;
   int daily_entries = 0;
   string market_day = "";
   for(int current = AXIOM_V2_WARMUP_BARS; current < ArraySize(bars); current++)
   {
      float features[];
      string reason = "";
      if(!AxiomV2ComputeFeatures(bars, current, features, reason))
         continue;
      float score = 0.0;
      if(!g_model.Score(features, score))
      {
         FileClose(output);
         WriteStatus("fixture_failed", "onnx_score_failed");
         return false;
      }
      string day = MarketDay(bars[current].time);
      if(day != market_day)
      {
         market_day = day;
         daily_entries = 0;
      }
      string event = "";
      if(active_direction != 0 && entry_signal_index >= 0 && current - entry_signal_index >= InpHoldBars)
      {
         active_direction = 0;
         entry_signal_index = -1;
         event = "exit";
      }
      int raw_direction = RawDirection(score);
      int admitted_direction = 0;
      if(active_direction == 0 && raw_direction != 0 && daily_entries < InpMaxDailyEntries)
      {
         admitted_direction = raw_direction;
         active_direction = raw_direction;
         entry_signal_index = current;
         daily_entries++;
         event = event == "exit" ? "exit_then_enter" : "enter";
      }
      if(event == "")
         event = active_direction != 0 ? "hold" : "flat";
      FileWrite(
         output,
         IntegerToString(current),
         TimeToString(bars[current].time, TIME_DATE | TIME_MINUTES | TIME_SECONDS),
         DoubleToString((double)features[0], 9),
         DoubleToString((double)features[1], 9),
         DoubleToString((double)features[2], 9),
         DoubleToString((double)features[3], 9),
         DoubleToString((double)features[4], 9),
         DoubleToString((double)features[5], 9),
         DoubleToString((double)features[6], 9),
         DoubleToString((double)features[7], 9),
         DoubleToString((double)features[8], 9),
         DoubleToString((double)features[9], 9),
         DoubleToString((double)features[10], 9),
         DoubleToString((double)features[11], 9),
         DoubleToString((double)score, 9),
         IntegerToString(raw_direction),
         IntegerToString(admitted_direction),
         IntegerToString(active_direction),
         event
      );
   }
   FileClose(output);
   WriteStatus("fixture_completed", "python_onnx_mql_decision_lifecycle_path_executed");
   return true;
}

bool HasOwnPosition()
{
   if(!PositionSelect(_Symbol))
      return false;
   return (long)PositionGetInteger(POSITION_MAGIC) == InpMagic;
}

void RecoverPositionState()
{
   if(InpDryRun || !HasOwnPosition())
      return;
   long position_type = PositionGetInteger(POSITION_TYPE);
   g_active_direction = position_type == POSITION_TYPE_BUY ? 1 : -1;
   datetime position_time = (datetime)PositionGetInteger(POSITION_TIME);
   g_entry_signal_time = position_time;
   int shift = iBarShift(_Symbol, _Period, position_time, false);
   g_bars_held = shift < 0 ? 0 : shift;
}

void AppendOnlineDecision(
   const datetime signal_bar_time,
   const float score,
   const int raw_direction,
   const int admitted_direction,
   const string event,
   const string detail
)
{
   int handle = FileOpen(InpDecisionLogPath, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(handle == INVALID_HANDLE)
      handle = FileOpen(InpDecisionLogPath, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(handle == INVALID_HANDLE)
      return;
   if(FileSize(handle) == 0)
      FileWrite(handle, "signal_bar_time", "score", "raw_direction", "admitted_direction", "active_direction", "event", "detail");
   FileSeek(handle, 0, SEEK_END);
   FileWrite(
      handle,
      TimeToString(signal_bar_time, TIME_DATE | TIME_MINUTES | TIME_SECONDS),
      DoubleToString((double)score, 9),
      IntegerToString(raw_direction),
      IntegerToString(admitted_direction),
      IntegerToString(g_active_direction),
      event,
      detail
   );
   FileClose(handle);
}

bool ClosePosition(const datetime signal_bar_time)
{
   if(g_active_direction == 0)
      return true;
   if(!InpDryRun && HasOwnPosition())
   {
      if(!g_trade.PositionClose(_Symbol, 50))
      {
         AppendOnlineDecision(signal_bar_time, 0.0, 0, 0, "exit_failed", IntegerToString((int)g_trade.ResultRetcode()));
         return false;
      }
   }
   g_active_direction = 0;
   g_bars_held = 0;
   g_entry_signal_time = 0;
   AppendOnlineDecision(signal_bar_time, 0.0, 0, 0, "exit", "fixed_horizon");
   return true;
}

bool OpenPosition(const int direction, const datetime signal_bar_time)
{
   if(direction == 0 || g_active_direction != 0)
      return false;
   if(!InpDryRun)
   {
      g_trade.SetExpertMagicNumber(InpMagic);
      g_trade.SetDeviationInPoints(50);
      bool opened = direction > 0 ? g_trade.Buy(InpLot, _Symbol) : g_trade.Sell(InpLot, _Symbol);
      if(!opened)
      {
         AppendOnlineDecision(signal_bar_time, 0.0, direction, 0, "entry_failed", IntegerToString((int)g_trade.ResultRetcode()));
         return false;
      }
   }
   g_active_direction = direction;
   g_bars_held = 0;
   g_entry_signal_time = signal_bar_time;
   return true;
}

void ProcessOnlineBar()
{
   datetime signal_bar_time = iTime(_Symbol, _Period, 1);
   if(g_active_direction != 0)
   {
      g_bars_held++;
      if(g_bars_held >= InpHoldBars && !ClosePosition(signal_bar_time))
         return;
   }
   MqlRates bars[];
   ArraySetAsSeries(bars, false);
   int copied = CopyRates(_Symbol, _Period, 1, AXIOM_V2_WARMUP_BARS + 1, bars);
   if(copied != AXIOM_V2_WARMUP_BARS + 1)
   {
      AppendOnlineDecision(signal_bar_time, 0.0, 0, 0, "skip", "missing_or_stale_bars");
      return;
   }
   float features[];
   string reason = "";
   if(!AxiomV2ComputeFeatures(bars, ArraySize(bars) - 1, features, reason))
   {
      AppendOnlineDecision(signal_bar_time, 0.0, 0, 0, "skip", reason);
      return;
   }
   float score = 0.0;
   if(!g_model.Score(features, score))
   {
      AppendOnlineDecision(signal_bar_time, 0.0, 0, 0, "skip", "onnx_score_failed");
      return;
   }
   string day = MarketDay(signal_bar_time);
   if(day != g_market_day)
   {
      g_market_day = day;
      g_daily_entries = 0;
   }
   int raw_direction = RawDirection(score);
   int admitted_direction = 0;
   string event = g_active_direction != 0 ? "hold" : "flat";
   if(g_active_direction == 0 && raw_direction != 0 && g_daily_entries < InpMaxDailyEntries)
   {
      if(OpenPosition(raw_direction, signal_bar_time))
      {
         admitted_direction = raw_direction;
         g_daily_entries++;
         event = "enter";
      }
   }
   AppendOnlineDecision(signal_bar_time, score, raw_direction, admitted_direction, event, "ok");
}

int OnInit()
{
   EnsureFolders();
   if(_Period != PERIOD_M5)
   {
      WriteStatus("init_failed", "M5_required");
      return INIT_FAILED;
   }
   if(InpExpectedFeatureOrderHash != AxiomV2FeatureOrderHash())
   {
      WriteStatus("init_failed", "feature_order_hash_mismatch");
      return INIT_FAILED;
   }
   if(InpHoldBars <= 0 || InpMaxDailyEntries <= 0 || InpMaxDailyEntries > 10)
   {
      WriteStatus("init_failed", "invalid_lifecycle_input");
      return INIT_FAILED;
   }
   if(!g_model.Initialize(AxiomV2Model))
   {
      WriteStatus("init_failed", "onnx_model_load_failed_" + IntegerToString(GetLastError()));
      return INIT_FAILED;
   }
   g_trade.SetExpertMagicNumber(InpMagic);
   if(InpMode == "fixture")
   {
      g_fixture_complete = RunFixture();
      return g_fixture_complete ? INIT_SUCCEEDED : INIT_FAILED;
   }
   if(InpMode != "online")
   {
      WriteStatus("init_failed", "unknown_mode");
      return INIT_FAILED;
   }
   RecoverPositionState();
   g_last_bar_time = iTime(_Symbol, _Period, 0);
   WriteStatus("online_started", "native_closed_bar_signal_path_active");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   g_model.Release();
   if(InpMode == "online")
      WriteStatus("online_completed", "deinit_" + IntegerToString(reason));
}

void OnTick()
{
   if(g_fixture_complete)
   {
      g_fixture_complete = false;
      ExpertRemove();
      return;
   }
   if(InpMode != "online")
      return;
   datetime bar_time = iTime(_Symbol, _Period, 0);
   if(bar_time == 0 || bar_time == g_last_bar_time)
      return;
   g_last_bar_time = bar_time;
   ProcessOnlineBar();
}

double OnTester()
{
   return AccountInfoDouble(ACCOUNT_BALANCE);
}
