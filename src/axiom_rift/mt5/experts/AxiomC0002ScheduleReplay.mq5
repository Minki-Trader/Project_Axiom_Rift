#property strict
#property version "1.00"

#include <Trade/Trade.mqh>

input string InpRunId = "R0000";
input string InpOutputMode = "logic_parity";
input string InpOutputScope = "";
input string InpResponseMode = "score_conditioned_schedule_replay";
input string InpSchedulePath = "AxiomRift\\C0002\\R0000\\schedule\\schedule.csv";
input long InpMagic = 200000;
input double InpLot = 0.01;
input int InpMaxHoldBars = 18;
input bool InpUseCommonFiles = true;
input bool InpUseClosedBarExit = true;

CTrade g_trade;
datetime g_last_bar_time = 0;
int g_event_handle = INVALID_HANDLE;
bool g_initialized = false;

string g_fold_ids[];
datetime g_signal_times[];
datetime g_entry_times[];
datetime g_exit_times[];
int g_directions[];
double g_scores[];
double g_entry_prices[];
double g_exit_prices[];
double g_stop_prices[];
double g_target_prices[];
int g_bars_held[];
string g_exit_reasons[];

int g_schedule_count = 0;
int g_next_index = 0;
int g_active_index = -1;
int g_active_direction = 0;
int g_active_bars_held = 0;
double g_active_entry_price = 0.0;
double g_active_stop = 0.0;
double g_active_target = 0.0;
ulong g_signal_count = 0;
ulong g_entry_count = 0;
ulong g_exit_count = 0;
ulong g_skip_count = 0;

string BaseFolder()
{
   string folder = "AxiomRift\\C0002\\" + InpRunId + "\\" + InpOutputMode;
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

int DirectionFromText(string value)
{
   if(value == "long" || value == "1")
      return 1;
   if(value == "short" || value == "-1")
      return -1;
   return 0;
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
   FolderCreate("AxiomRift\\C0002", common_flag);
   FolderCreate("AxiomRift\\C0002\\" + InpRunId, common_flag);
   FolderCreate("AxiomRift\\C0002\\" + InpRunId + "\\" + InpOutputMode, common_flag);
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
   FileWrite(handle, "max_hold_bars", IntegerToString(InpMaxHoldBars));
   FileWrite(handle, "exit_evaluation", InpUseClosedBarExit ? "closed_bar_ohlc" : "tick_price");
   FileWrite(handle, "logical_entry_price_basis", "schedule_entry_bar_open");
   FileWrite(handle, "schedule_path", InpSchedulePath);
   FileWrite(handle, "schedule_rows", IntegerToString(g_schedule_count));
   FileWrite(handle, "signals", IntegerToString((int)g_signal_count));
   FileWrite(handle, "entries", IntegerToString((int)g_entry_count));
   FileWrite(handle, "exits", IntegerToString((int)g_exit_count));
   FileWrite(handle, "skips", IntegerToString((int)g_skip_count));
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
      TimeText(signal_time),
      IntegerToString(bars_held),
      reason,
      IntegerToString(retcode)
   );
   FileFlush(g_event_handle);
}

datetime BarTime(int shift) { return iTime(_Symbol, _Period, shift); }

bool HasOpenPosition()
{
   if(!PositionSelect(_Symbol))
      return false;
   return (long)PositionGetInteger(POSITION_MAGIC) == InpMagic;
}

void ResizeSchedule(int size)
{
   ArrayResize(g_fold_ids, size);
   ArrayResize(g_signal_times, size);
   ArrayResize(g_entry_times, size);
   ArrayResize(g_exit_times, size);
   ArrayResize(g_directions, size);
   ArrayResize(g_scores, size);
   ArrayResize(g_entry_prices, size);
   ArrayResize(g_exit_prices, size);
   ArrayResize(g_stop_prices, size);
   ArrayResize(g_target_prices, size);
   ArrayResize(g_bars_held, size);
   ArrayResize(g_exit_reasons, size);
}

bool LoadSchedule()
{
   int handle = FileOpen(InpSchedulePath, ReadFlags(), ',');
   if(handle == INVALID_HANDLE)
   {
      WriteStatus("invalid_schedule_open_failed", InpSchedulePath);
      return false;
   }

   for(int i = 0; i < 12 && !FileIsEnding(handle); i++)
      FileReadString(handle);

   while(!FileIsEnding(handle))
   {
      string fold_id = FileReadString(handle);
      if(FileIsEnding(handle) && fold_id == "")
         break;
      string signal_time = FileReadString(handle);
      string entry_time = FileReadString(handle);
      string exit_time = FileReadString(handle);
      string direction = FileReadString(handle);
      string score = FileReadString(handle);
      string entry_price = FileReadString(handle);
      string exit_price = FileReadString(handle);
      string stop_price = FileReadString(handle);
      string target_price = FileReadString(handle);
      string bars_held = FileReadString(handle);
      string exit_reason = FileReadString(handle);

      if(fold_id == "" || entry_time == "" || exit_time == "")
         continue;

      int index = g_schedule_count;
      g_schedule_count++;
      ResizeSchedule(g_schedule_count);
      g_fold_ids[index] = fold_id;
      g_signal_times[index] = StringToTime(signal_time);
      g_entry_times[index] = StringToTime(entry_time);
      g_exit_times[index] = StringToTime(exit_time);
      g_directions[index] = DirectionFromText(direction);
      g_scores[index] = StringToDouble(score);
      g_entry_prices[index] = StringToDouble(entry_price);
      g_exit_prices[index] = StringToDouble(exit_price);
      g_stop_prices[index] = StringToDouble(stop_price);
      g_target_prices[index] = StringToDouble(target_price);
      g_bars_held[index] = (int)StringToInteger(bars_held);
      g_exit_reasons[index] = exit_reason;
   }
   FileClose(handle);
   if(g_schedule_count <= 0)
   {
      WriteStatus("invalid_schedule_empty", InpSchedulePath);
      return false;
   }
   return true;
}

void SkipExpiredEntries(datetime bar_time)
{
   while(g_next_index < g_schedule_count && g_entry_times[g_next_index] < bar_time)
   {
      g_skip_count++;
      LogEvent(
         "entry_skipped",
         TimeCurrent(),
         g_entry_times[g_next_index],
         g_directions[g_next_index],
         g_entry_prices[g_next_index],
         g_stop_prices[g_next_index],
         g_target_prices[g_next_index],
         g_signal_times[g_next_index],
         0,
         "schedule_entry_missed",
         0
      );
      g_next_index++;
   }
}

void ExecuteScheduledEntry(datetime bar_time)
{
   if(HasOpenPosition())
      return;
   SkipExpiredEntries(bar_time);
   if(g_next_index >= g_schedule_count)
      return;
   if(g_entry_times[g_next_index] != bar_time)
      return;

   int index = g_next_index;
   int direction = g_directions[index];
   if(direction == 0)
   {
      g_next_index++;
      return;
   }

   g_signal_count++;
   LogEvent(
      "signal",
      TimeCurrent(),
      g_signal_times[index],
      direction,
      g_entry_prices[index],
      g_stop_prices[index],
      g_target_prices[index],
      g_signal_times[index],
      0,
      "score_schedule_selected",
      0
   );

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(50);
   bool ok = false;
   if(direction > 0)
      ok = g_trade.Buy(InpLot, _Symbol, 0.0, 0.0, 0.0, InpRunId);
   else
      ok = g_trade.Sell(InpLot, _Symbol, 0.0, 0.0, 0.0, InpRunId);

   int retcode = (int)g_trade.ResultRetcode();
   if(!ok || !PositionSelect(_Symbol))
   {
      LogEvent(
         "entry_failed",
         TimeCurrent(),
         bar_time,
         direction,
         g_entry_prices[index],
         g_stop_prices[index],
         g_target_prices[index],
         g_signal_times[index],
         0,
         "trade_open_failed",
         retcode
      );
      g_next_index++;
      return;
   }

   double actual_entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
   g_active_index = index;
   g_active_direction = direction;
   g_active_bars_held = 0;
   g_active_entry_price = g_entry_prices[index];
   g_active_stop = g_stop_prices[index];
   g_active_target = g_target_prices[index];
   g_entry_count++;
   LogEvent(
      "entry",
      TimeCurrent(),
      bar_time,
      direction,
      g_entry_prices[index],
      g_stop_prices[index],
      g_target_prices[index],
      g_signal_times[index],
      0,
      "opened",
      retcode
   );
   if(MathAbs(actual_entry_price - g_entry_prices[index]) > 0.0)
   {
      LogEvent(
         "entry_price_basis",
         TimeCurrent(),
         bar_time,
         direction,
         actual_entry_price,
         g_stop_prices[index],
         g_target_prices[index],
         g_signal_times[index],
         0,
         "actual_fill_price",
         retcode
      );
   }
   g_next_index++;
}

void CloseActivePositionAt(string reason, datetime logical_bar_time, int logical_bars_held)
{
   if(!HasOpenPosition() || g_active_index < 0)
      return;
   bool ok = g_trade.PositionClose(_Symbol, 50);
   int retcode = (int)g_trade.ResultRetcode();
   if(ok)
   {
      g_exit_count++;
      LogEvent(
         "exit",
         TimeCurrent(),
         logical_bar_time,
         g_active_direction,
         g_exit_prices[g_active_index],
         g_active_stop,
         g_active_target,
         g_signal_times[g_active_index],
         logical_bars_held,
         reason,
         retcode
      );
      g_active_index = -1;
      g_active_direction = 0;
      g_active_bars_held = 0;
      g_active_entry_price = 0.0;
      g_active_stop = 0.0;
      g_active_target = 0.0;
   }
   else
   {
      LogEvent(
         "exit_failed",
         TimeCurrent(),
         logical_bar_time,
         g_active_direction,
         g_exit_prices[g_active_index],
         g_active_stop,
         g_active_target,
         g_signal_times[g_active_index],
         logical_bars_held,
         reason,
         retcode
      );
   }
}

void ManageOpenPosition()
{
   if(!HasOpenPosition() || g_active_index < 0 || InpUseClosedBarExit)
      return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(g_active_direction > 0)
   {
      if(bid <= g_active_stop)
      {
         CloseActivePositionAt("stop", BarTime(0), g_active_bars_held);
         return;
      }
      if(bid >= g_active_target)
      {
         CloseActivePositionAt("target", BarTime(0), g_active_bars_held);
         return;
      }
   }
   else if(g_active_direction < 0)
   {
      if(ask >= g_active_stop)
      {
         CloseActivePositionAt("stop", BarTime(0), g_active_bars_held);
         return;
      }
      if(ask <= g_active_target)
      {
         CloseActivePositionAt("target", BarTime(0), g_active_bars_held);
         return;
      }
   }
}

void OnNewBar()
{
   datetime closed_bar_time = BarTime(1);
   if(HasOpenPosition() && InpUseClosedBarExit && g_active_index >= 0)
   {
      if(g_exit_times[g_active_index] == closed_bar_time)
      {
         CloseActivePositionAt(g_exit_reasons[g_active_index], closed_bar_time, g_active_bars_held + 1);
      }
   }

   if(HasOpenPosition() && g_active_index >= 0)
   {
      g_active_bars_held++;
      if(!InpUseClosedBarExit && g_active_bars_held >= InpMaxHoldBars)
      {
         CloseActivePositionAt("max_hold", BarTime(0), g_active_bars_held);
         ExecuteScheduledEntry(BarTime(0));
         return;
      }
   }

   ExecuteScheduledEntry(BarTime(0));
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
   if(!LoadSchedule())
      return INIT_FAILED;
   g_trade.SetExpertMagicNumber(InpMagic);
   OpenEventLog();
   WriteStatus("started", InpRunId + " MT5 schedule replay started");
   g_initialized = true;
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(g_initialized)
   {
      if(HasOpenPosition() && g_active_index >= 0)
         CloseActivePositionAt("deinit", BarTime(0), g_active_bars_held);
      WriteHistoryDeals();
      WriteStatus("completed", InpRunId + " MT5 schedule replay completed");
   }
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
