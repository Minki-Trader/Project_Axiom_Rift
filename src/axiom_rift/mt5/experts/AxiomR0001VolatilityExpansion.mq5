#property strict
#property version "1.00"

#include <Trade/Trade.mqh>

input string InpRunId = "R0001";
input string InpOutputMode = "logic_parity";
input string InpOutputScope = "";
input string InpResponseMode = "continuation";
input long InpMagic = 100001;
input double InpLot = 0.01;
input int InpLookbackRangeBars = 48;
input int InpBreakoutBars = 24;
input double InpExpansionRangeMultiple = 1.8;
input double InpMinBodyRangeFraction = 0.55;
input int InpCompressionBars = 12;
input double InpCompressionRangeMultiple = 4.0;
input double InpBreakoutRangeMultiple = 1.0;
input int InpPullbackSearchBars = 6;
input int InpReclaimSearchBars = 6;
input double InpPullbackMinRatio = 0.20;
input double InpPullbackMaxRatio = 0.65;
input double InpStopAtrMultiple = 0.8;
input double InpTargetAtrMultiple = 1.2;
input int InpMaxHoldBars = 18;
input bool InpUseCommonFiles = true;
input bool InpUseClosedBarExit = true;
input bool InpUseSessionFilter = false;
input int InpSessionStartMinute = 0;
input int InpSessionEndMinute = 1440;

CTrade g_trade;
datetime g_last_bar_time = 0;
int g_state = 0;
int g_direction = 0;
int g_bars_since_expansion = 0;
double g_expansion_open = 0.0;
double g_expansion_close = 0.0;
double g_expansion_range = 0.0;
double g_expansion_avg_range = 0.0;
double g_breakout_level = 0.0;
datetime g_expansion_time = 0;
bool g_pending_entry = false;
int g_pending_direction = 0;
datetime g_pending_signal_time = 0;
datetime g_pending_entry_bar_time = 0;
double g_active_stop = 0.0;
double g_active_target = 0.0;
datetime g_active_entry_bar_time = 0;
int g_active_direction = 0;
int g_active_bars_held = 0;
double g_active_entry_price = 0.0;
ulong g_signal_count = 0;
ulong g_entry_count = 0;
ulong g_exit_count = 0;
int g_event_handle = INVALID_HANDLE;

string BaseFolder()
{
   string folder = "AxiomRift\\C0001\\" + InpRunId + "\\" + InpOutputMode;
   if(InpOutputScope != "")
      folder = folder + "\\" + InpOutputScope;
   return folder;
}

int FileFlags()
{
   int flags = FILE_WRITE | FILE_CSV | FILE_ANSI;
   if(InpUseCommonFiles)
      flags |= FILE_COMMON;
   return flags;
}

int ReadFlags()
{
   int flags = FILE_READ | FILE_CSV | FILE_ANSI;
   if(InpUseCommonFiles)
      flags |= FILE_COMMON;
   return flags;
}

string TimeText(datetime value)
{
   return TimeToString(value, TIME_DATE | TIME_MINUTES | TIME_SECONDS);
}

int ClampedSessionMinute(int value)
{
   if(value < 0)
      return 0;
   if(value > 1440)
      return 1440;
   return value;
}

int MinuteOfDay(datetime value)
{
   MqlDateTime parts;
   TimeToStruct(value, parts);
   return parts.hour * 60 + parts.min;
}

bool IsWithinSession(datetime value)
{
   if(!InpUseSessionFilter)
      return true;

   int start_minute = ClampedSessionMinute(InpSessionStartMinute);
   int end_minute = ClampedSessionMinute(InpSessionEndMinute);
   if(start_minute == end_minute)
      return true;

   int minute = MinuteOfDay(value);
   if(start_minute < end_minute)
      return minute >= start_minute && minute < end_minute;
   return minute >= start_minute || minute < end_minute;
}

bool CanQueueSignal(datetime closed_bar_time)
{
   return IsWithinSession(closed_bar_time) && IsWithinSession(BarTime(0));
}

string DirectionText(int direction)
{
   if(direction > 0)
      return "long";
   if(direction < 0)
      return "short";
   return "flat";
}

void EnsureFolders()
{
   int common_flag = InpUseCommonFiles ? FILE_COMMON : 0;
   FolderCreate("AxiomRift", common_flag);
   FolderCreate("AxiomRift\\C0001", common_flag);
   FolderCreate("AxiomRift\\C0001\\" + InpRunId, common_flag);
   FolderCreate("AxiomRift\\C0001\\" + InpRunId + "\\" + InpOutputMode, common_flag);
   FolderCreate(BaseFolder(), common_flag);
}

void WriteStatus(string status, string detail)
{
   EnsureFolders();
   int handle = FileOpen(BaseFolder() + "\\mt5_status.csv", FileFlags(), ',');
   if(handle == INVALID_HANDLE)
      return;
   FileWrite(handle, "field", "value");
   FileWrite(handle, "status", status);
   FileWrite(handle, "detail", detail);
   FileWrite(handle, "run_id", InpRunId);
   FileWrite(handle, "output_mode", InpOutputMode);
   FileWrite(handle, "output_scope", InpOutputScope);
   FileWrite(handle, "response_mode", InpResponseMode);
   FileWrite(handle, "symbol", _Symbol);
   FileWrite(handle, "period_seconds", IntegerToString(PeriodSeconds(_Period)));
   FileWrite(handle, "magic", IntegerToString((int)InpMagic));
   FileWrite(handle, "lot", DoubleToString(InpLot, 4));
   FileWrite(handle, "exit_evaluation", InpUseClosedBarExit ? "closed_bar_ohlc" : "tick_price");
   FileWrite(handle, "session_filter_enabled", InpUseSessionFilter ? "true" : "false");
   FileWrite(handle, "session_start_minute", IntegerToString(InpSessionStartMinute));
   FileWrite(handle, "session_end_minute", IntegerToString(InpSessionEndMinute));
   FileWrite(handle, "logical_entry_price_basis", "bar_open");
   FileWrite(handle, "signals", IntegerToString((int)g_signal_count));
   FileWrite(handle, "entries", IntegerToString((int)g_entry_count));
   FileWrite(handle, "exits", IntegerToString((int)g_exit_count));
   FileWrite(handle, "balance", DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2));
   FileWrite(handle, "equity", DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2));
   FileWrite(handle, "currency", AccountInfoString(ACCOUNT_CURRENCY));
   FileWrite(handle, "leverage", IntegerToString((int)AccountInfoInteger(ACCOUNT_LEVERAGE)));
   FileWrite(handle, "created_at", TimeText(TimeCurrent()));
   FileClose(handle);
}

void OpenEventLog()
{
   EnsureFolders();
   g_event_handle = FileOpen(BaseFolder() + "\\mt5_events.csv", FileFlags(), ',');
   if(g_event_handle == INVALID_HANDLE)
      return;
   FileWrite(
      g_event_handle,
      "event",
      "time",
      "bar_time",
      "direction",
      "price",
      "stop",
      "target",
      "signal_time",
      "expansion_time",
      "bars_held",
      "reason",
      "retcode"
   );
   FileFlush(g_event_handle);
}

void LogEvent(
   string event_name,
   datetime event_time,
   datetime bar_time,
   int direction,
   double price,
   double stop_price,
   double target_price,
   datetime signal_time,
   datetime expansion_time,
   int bars_held,
   string reason,
   int retcode
)
{
   if(g_event_handle == INVALID_HANDLE)
      return;
   FileWrite(
      g_event_handle,
      event_name,
      TimeText(event_time),
      TimeText(bar_time),
      DirectionText(direction),
      DoubleToString(price, _Digits),
      DoubleToString(stop_price, _Digits),
      DoubleToString(target_price, _Digits),
      TimeText(signal_time),
      TimeText(expansion_time),
      IntegerToString(bars_held),
      reason,
      IntegerToString(retcode)
   );
   FileFlush(g_event_handle);
}

double BarOpen(int shift) { return iOpen(_Symbol, _Period, shift); }
double BarHigh(int shift) { return iHigh(_Symbol, _Period, shift); }
double BarLow(int shift) { return iLow(_Symbol, _Period, shift); }
double BarClose(int shift) { return iClose(_Symbol, _Period, shift); }
datetime BarTime(int shift) { return iTime(_Symbol, _Period, shift); }

double AverageRange(int start_shift, int count)
{
   double total = 0.0;
   for(int i = start_shift; i < start_shift + count; i++)
      total += MathMax(0.0, BarHigh(i) - BarLow(i));
   return total / count;
}

double HighestHigh(int start_shift, int count)
{
   double value = BarHigh(start_shift);
   for(int i = start_shift + 1; i < start_shift + count; i++)
      value = MathMax(value, BarHigh(i));
   return value;
}

double LowestLow(int start_shift, int count)
{
   double value = BarLow(start_shift);
   for(int i = start_shift + 1; i < start_shift + count; i++)
      value = MathMin(value, BarLow(i));
   return value;
}

bool HasOpenPosition()
{
   if(!PositionSelect(_Symbol))
      return false;
   return (long)PositionGetInteger(POSITION_MAGIC) == InpMagic;
}

int DetectExpansion(int shift, double &average_range, double &breakout_level)
{
   breakout_level = 0.0;
   if(Bars(_Symbol, _Period) < InpLookbackRangeBars + InpBreakoutBars + 10)
      return 0;
   average_range = AverageRange(shift + 1, InpLookbackRangeBars);
   if(average_range <= 0.0)
      return 0;

   double open_price = BarOpen(shift);
   double high_price = BarHigh(shift);
   double low_price = BarLow(shift);
   double close_price = BarClose(shift);
   double range_points = high_price - low_price;
   double body = close_price - open_price;
   double previous_high = HighestHigh(shift + 1, InpBreakoutBars);
   double previous_low = LowestLow(shift + 1, InpBreakoutBars);

   if(range_points < InpExpansionRangeMultiple * average_range)
      return 0;
   if(MathAbs(body) < InpMinBodyRangeFraction * range_points)
      return 0;
   if(body > 0.0 && close_price > previous_high)
   {
      breakout_level = previous_high;
      return 1;
   }
   if(body < 0.0 && close_price < previous_low)
   {
      breakout_level = previous_low;
      return -1;
   }
   return 0;
}

bool PullbackConfirmed(int shift)
{
   double low_price = BarLow(shift);
   double high_price = BarHigh(shift);
   double close_price = BarClose(shift);
   double retrace = 0.0;
   bool still_valid = false;

   if(g_direction > 0)
   {
      retrace = g_expansion_close - low_price;
      still_valid = close_price > g_expansion_open;
   }
   else if(g_direction < 0)
   {
      retrace = high_price - g_expansion_close;
      still_valid = close_price < g_expansion_open;
   }
   if(g_expansion_range <= 0.0 || !still_valid)
      return false;
   double ratio = retrace / g_expansion_range;
   return ratio >= InpPullbackMinRatio && ratio <= InpPullbackMaxRatio;
}

bool BreakoutReclaimConfirmed(int shift)
{
   double close_price = BarClose(shift);
   if(g_breakout_level <= 0.0)
      return false;
   if(g_direction > 0)
      return close_price < g_breakout_level;
   if(g_direction < 0)
      return close_price > g_breakout_level;
   return false;
}

bool UsesBreakoutReclaim()
{
   return InpResponseMode == "failed_breakout_reclaim_reversal";
}

bool UsesCompressionBreakout()
{
   return InpResponseMode == "compression_breakout_continuation" || UsesCompressionBreakoutReversal();
}

bool UsesCompressionBreakoutReversal()
{
   return InpResponseMode == "compression_breakout_reversal";
}

bool UsesExpansionExhaustionReversal()
{
   return InpResponseMode == "expansion_exhaustion_reversal";
}

int DetectCompressionBreakout(int shift, double &average_range)
{
   if(Bars(_Symbol, _Period) < InpLookbackRangeBars + InpCompressionBars + 10)
      return 0;
   average_range = AverageRange(shift + 1, InpLookbackRangeBars);
   if(average_range <= 0.0)
      return 0;

   double compression_high = HighestHigh(shift + 1, InpCompressionBars);
   double compression_low = LowestLow(shift + 1, InpCompressionBars);
   double compression_width = compression_high - compression_low;
   double range_points = BarHigh(shift) - BarLow(shift);
   double body = BarClose(shift) - BarOpen(shift);

   if(compression_width <= 0.0)
      return 0;
   if(compression_width > InpCompressionRangeMultiple * average_range)
      return 0;
   if(range_points < InpBreakoutRangeMultiple * average_range)
      return 0;
   if(MathAbs(body) < InpMinBodyRangeFraction * range_points)
      return 0;
   if(body > 0.0 && BarClose(shift) > compression_high)
      return 1;
   if(body < 0.0 && BarClose(shift) < compression_low)
      return -1;
   return 0;
}

bool SignalConfirmed(int shift)
{
   if(UsesBreakoutReclaim())
      return BreakoutReclaimConfirmed(shift);
   return PullbackConfirmed(shift);
}

int SearchBarsLimit()
{
   if(UsesBreakoutReclaim())
      return InpReclaimSearchBars;
   return InpPullbackSearchBars;
}

string SignalReason()
{
   if(UsesBreakoutReclaim())
      return "breakout_reclaimed";
   return "pullback_confirmed";
}

string ExpiredReason()
{
   if(UsesBreakoutReclaim())
      return "breakout_reclaim_not_found";
   return "pullback_not_found";
}

int ResponseDirection(int expansion_direction)
{
   if(InpResponseMode == "reversal" || UsesBreakoutReclaim() || UsesExpansionExhaustionReversal() || UsesCompressionBreakoutReversal())
      return -expansion_direction;
   return expansion_direction;
}

void ResetSignalState()
{
   g_state = 0;
   g_direction = 0;
   g_bars_since_expansion = 0;
   g_expansion_open = 0.0;
   g_expansion_close = 0.0;
   g_expansion_range = 0.0;
   g_breakout_level = 0.0;
}

bool QueueDirectSignal(int direction, double average_range, datetime closed_bar_time, string reason)
{
   if(direction == 0)
      return false;
   if(!CanQueueSignal(closed_bar_time))
      return false;
   g_signal_count++;
   g_pending_entry = true;
   g_pending_direction = ResponseDirection(direction);
   g_pending_signal_time = closed_bar_time;
   g_pending_entry_bar_time = BarTime(0);
   g_expansion_avg_range = average_range;
   g_expansion_time = closed_bar_time;
   LogEvent("signal", TimeCurrent(), closed_bar_time, g_pending_direction, BarClose(1), 0.0, 0.0, closed_bar_time, g_expansion_time, 0, reason, 0);
   return true;
}

void ProcessClosedBar()
{
   if(HasOpenPosition())
      return;

   int shift = 1;
   datetime closed_bar_time = BarTime(shift);

   if(!IsWithinSession(closed_bar_time))
   {
      if(g_state == 1)
         ResetSignalState();
      return;
   }

   if(UsesCompressionBreakout())
   {
      double compression_average_range = 0.0;
      int compression_direction = DetectCompressionBreakout(shift, compression_average_range);
      QueueDirectSignal(compression_direction, compression_average_range, closed_bar_time, "compression_breakout_confirmed");
      return;
   }

   if(UsesExpansionExhaustionReversal())
   {
      double direct_average_range = 0.0;
      double direct_breakout_level = 0.0;
      int direct_direction = DetectExpansion(shift, direct_average_range, direct_breakout_level);
      QueueDirectSignal(direct_direction, direct_average_range, closed_bar_time, "expansion_exhaustion_confirmed");
      return;
   }

   if(g_state == 1)
   {
      g_bars_since_expansion++;
      if(SignalConfirmed(shift))
      {
         if(!CanQueueSignal(closed_bar_time))
         {
            ResetSignalState();
            return;
         }
         g_signal_count++;
         g_pending_entry = true;
         g_pending_direction = ResponseDirection(g_direction);
         g_pending_signal_time = closed_bar_time;
         g_pending_entry_bar_time = BarTime(0);
         LogEvent("signal", TimeCurrent(), closed_bar_time, g_pending_direction, BarClose(shift), 0.0, 0.0, closed_bar_time, g_expansion_time, 0, SignalReason(), 0);
         ResetSignalState();
         return;
      }
      if(g_bars_since_expansion >= SearchBarsLimit())
      {
         LogEvent("signal_expired", TimeCurrent(), closed_bar_time, g_direction, BarClose(shift), 0.0, 0.0, closed_bar_time, g_expansion_time, 0, ExpiredReason(), 0);
         ResetSignalState();
      }
      return;
   }

   double average_range = 0.0;
   double breakout_level = 0.0;
   int direction = DetectExpansion(shift, average_range, breakout_level);
   if(direction == 0)
      return;

   double body_points = MathAbs(BarClose(shift) - BarOpen(shift));
   double range_points = BarHigh(shift) - BarLow(shift);
   g_state = 1;
   g_direction = direction;
   g_bars_since_expansion = 0;
   g_expansion_open = BarOpen(shift);
   g_expansion_close = BarClose(shift);
   g_expansion_range = MathMax(MathMax(body_points, range_points), average_range);
   g_expansion_avg_range = average_range;
   g_breakout_level = breakout_level;
   g_expansion_time = closed_bar_time;
   LogEvent("expansion", TimeCurrent(), closed_bar_time, direction, BarClose(shift), 0.0, 0.0, closed_bar_time, g_expansion_time, 0, "expansion_detected", 0);
}

void ExecutePendingEntry()
{
   if(!g_pending_entry || HasOpenPosition())
      return;

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(50);
   bool ok = false;
   if(g_pending_direction > 0)
      ok = g_trade.Buy(InpLot, _Symbol, 0.0, 0.0, 0.0, InpRunId);
   else
      ok = g_trade.Sell(InpLot, _Symbol, 0.0, 0.0, 0.0, InpRunId);

   int retcode = (int)g_trade.ResultRetcode();
   if(!ok)
   {
      LogEvent("entry_failed", TimeCurrent(), BarTime(0), g_pending_direction, 0.0, 0.0, 0.0, g_pending_signal_time, g_expansion_time, 0, "trade_open_failed", retcode);
      g_pending_entry = false;
      return;
   }

   if(!PositionSelect(_Symbol))
   {
      LogEvent("entry_failed", TimeCurrent(), BarTime(0), g_pending_direction, 0.0, 0.0, 0.0, g_pending_signal_time, g_expansion_time, 0, "position_missing_after_open", retcode);
      g_pending_entry = false;
      return;
   }

   double actual_entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
   g_active_entry_price = BarOpen(0);
   g_active_direction = g_pending_direction;
   g_active_entry_bar_time = g_pending_entry_bar_time;
   g_active_bars_held = 0;
   g_active_stop = NormalizeDouble(g_active_entry_price - g_active_direction * InpStopAtrMultiple * g_expansion_avg_range, _Digits);
   g_active_target = NormalizeDouble(g_active_entry_price + g_active_direction * InpTargetAtrMultiple * g_expansion_avg_range, _Digits);
   g_entry_count++;
   LogEvent("entry", TimeCurrent(), g_active_entry_bar_time, g_active_direction, g_active_entry_price, g_active_stop, g_active_target, g_pending_signal_time, g_expansion_time, 0, "opened", retcode);
   if(MathAbs(actual_entry_price - g_active_entry_price) > 0.0)
      LogEvent("entry_price_basis", TimeCurrent(), g_active_entry_bar_time, g_active_direction, actual_entry_price, g_active_stop, g_active_target, g_pending_signal_time, g_expansion_time, 0, "actual_fill_price", retcode);
   g_pending_entry = false;
}

void CloseActivePositionAt(string reason, datetime logical_bar_time, int logical_bars_held)
{
   if(!HasOpenPosition())
      return;
   double price = (g_active_direction > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   bool ok = g_trade.PositionClose(_Symbol, 50);
   int retcode = (int)g_trade.ResultRetcode();
   if(ok)
   {
      g_exit_count++;
      LogEvent("exit", TimeCurrent(), logical_bar_time, g_active_direction, price, g_active_stop, g_active_target, g_pending_signal_time, g_expansion_time, logical_bars_held, reason, retcode);
      g_active_direction = 0;
      g_active_entry_price = 0.0;
      g_active_stop = 0.0;
      g_active_target = 0.0;
      g_active_bars_held = 0;
   }
   else
   {
      LogEvent("exit_failed", TimeCurrent(), logical_bar_time, g_active_direction, price, g_active_stop, g_active_target, g_pending_signal_time, g_expansion_time, logical_bars_held, reason, retcode);
   }
}

void CloseActivePosition(string reason)
{
   CloseActivePositionAt(reason, BarTime(0), g_active_bars_held);
}

string ClosedBarExitReason(int shift)
{
   if(!HasOpenPosition())
      return "";
   double high_price = BarHigh(shift);
   double low_price = BarLow(shift);
   if(g_active_direction > 0)
   {
      if(low_price <= g_active_stop)
         return "stop";
      if(high_price >= g_active_target)
         return "target";
   }
   else if(g_active_direction < 0)
   {
      if(high_price >= g_active_stop)
         return "stop";
      if(low_price <= g_active_target)
         return "target";
   }
   return "";
}

void ManageOpenPosition()
{
   if(!HasOpenPosition())
      return;
   if(InpUseClosedBarExit)
      return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(g_active_direction > 0)
   {
      if(bid <= g_active_stop)
      {
         CloseActivePosition("stop");
         return;
      }
      if(bid >= g_active_target)
      {
         CloseActivePosition("target");
         return;
      }
   }
   else if(g_active_direction < 0)
   {
      if(ask >= g_active_stop)
      {
         CloseActivePosition("stop");
         return;
      }
      if(ask <= g_active_target)
      {
         CloseActivePosition("target");
         return;
      }
   }
}

void OnNewBar()
{
   if(HasOpenPosition() && InpUseClosedBarExit)
   {
      string reason = ClosedBarExitReason(1);
      if(reason != "")
      {
         CloseActivePositionAt(reason, BarTime(1), g_active_bars_held + 1);
      }
   }

   if(HasOpenPosition())
   {
      g_active_bars_held++;
      if(g_active_bars_held >= InpMaxHoldBars)
      {
         CloseActivePosition("max_hold");
         return;
      }
   }
   ProcessClosedBar();
   ExecutePendingEntry();
}

void WriteHistoryDeals()
{
   EnsureFolders();
   int handle = FileOpen(BaseFolder() + "\\mt5_deals.csv", FileFlags(), ',');
   if(handle == INVALID_HANDLE)
      return;
   FileWrite(handle, "ticket", "time", "position_id", "entry", "type", "volume", "price", "profit", "commission", "swap", "symbol", "comment");
   HistorySelect(0, TimeCurrent());
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if((long)HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic)
         continue;
      string symbol = HistoryDealGetString(ticket, DEAL_SYMBOL);
      if(symbol != _Symbol)
         continue;
      FileWrite(
         handle,
         IntegerToString((int)ticket),
         TimeText((datetime)HistoryDealGetInteger(ticket, DEAL_TIME)),
         IntegerToString((int)HistoryDealGetInteger(ticket, DEAL_POSITION_ID)),
         IntegerToString((int)HistoryDealGetInteger(ticket, DEAL_ENTRY)),
         IntegerToString((int)HistoryDealGetInteger(ticket, DEAL_TYPE)),
         DoubleToString(HistoryDealGetDouble(ticket, DEAL_VOLUME), 4),
         DoubleToString(HistoryDealGetDouble(ticket, DEAL_PRICE), _Digits),
         DoubleToString(HistoryDealGetDouble(ticket, DEAL_PROFIT), 2),
         DoubleToString(HistoryDealGetDouble(ticket, DEAL_COMMISSION), 2),
         DoubleToString(HistoryDealGetDouble(ticket, DEAL_SWAP), 2),
         symbol,
         HistoryDealGetString(ticket, DEAL_COMMENT)
      );
   }
   FileClose(handle);
}

int OnInit()
{
   if(_Period != PERIOD_M5)
   {
      WriteStatus("invalid_period", InpRunId + " requires M5");
      return INIT_FAILED;
   }
   g_trade.SetExpertMagicNumber(InpMagic);
   OpenEventLog();
   WriteStatus("started", InpRunId + " MT5 probe started");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(HasOpenPosition())
      CloseActivePosition("deinit");
   WriteHistoryDeals();
   WriteStatus("completed", InpRunId + " MT5 probe completed");
   if(g_event_handle != INVALID_HANDLE)
      FileClose(g_event_handle);
}

void OnTick()
{
   ManageOpenPosition();
   datetime bar_time = BarTime(0);
   if(bar_time != g_last_bar_time)
   {
      if(g_last_bar_time != 0)
         OnNewBar();
      g_last_bar_time = bar_time;
   }
}

double OnTester()
{
   return AccountInfoDouble(ACCOUNT_BALANCE);
}
