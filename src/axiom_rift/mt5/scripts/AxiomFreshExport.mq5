#property script_show_inputs

input string InpSymbol = "US100";
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M5;
input datetime InpFrom = D'1970.01.01 00:00';
input string InpOutputFile = "AxiomRift\\US100_M5_max.csv";
input string InpStatusFile = "AxiomRift\\US100_M5_max_status.csv";
input bool InpIncludeCurrentBar = false;
input int InpMaxRetries = 12;
input int InpSleepMs = 5000;

string TimeText(datetime value)
{
   return TimeToString(value, TIME_DATE | TIME_MINUTES | TIME_SECONDS);
}

void WriteStatus(string status, int copied, string first_time, string last_time, int last_error)
{
   FolderCreate("AxiomRift");
   int handle = FileOpen(InpStatusFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
   {
      Print("status FileOpen failed: ", GetLastError());
      return;
   }
   FileWrite(handle, "status", "copied", "first_time", "last_time", "last_error");
   FileWrite(handle, status, copied, first_time, last_time, last_error);
   FileClose(handle);
}

void OnStart()
{
   string symbol = InpSymbol;
   FolderCreate("AxiomRift");
   SymbolSelect(symbol, true);

   MqlRates rates[];
   datetime to_time = TimeCurrent();
   int copied = -1;
   int last_error = 0;

   for(int attempt = 0; attempt < InpMaxRetries; attempt++)
   {
      ResetLastError();
      copied = CopyRates(symbol, InpTimeframe, InpFrom, to_time, rates);
      last_error = GetLastError();
      if(copied > 0)
         break;
      Sleep(InpSleepMs);
   }

   if(copied <= 0)
   {
      WriteStatus("copy_rates_failed", copied, "", "", last_error);
      return;
   }

   datetime current_bar = iTime(symbol, InpTimeframe, 0);
   int handle = FileOpen(InpOutputFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
   {
      WriteStatus("output_open_failed", copied, "", "", GetLastError());
      return;
   }

   FileWrite(handle, "time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume");

   int written = 0;
   string first_time = "";
   string last_time_written = "";
   for(int i = 0; i < copied; i++)
   {
      if(!InpIncludeCurrentBar && rates[i].time >= current_bar)
         continue;
      string t = TimeText(rates[i].time);
      if(written == 0)
         first_time = t;
      last_time_written = t;
      FileWrite(
         handle,
         t,
         DoubleToString(rates[i].open, _Digits),
         DoubleToString(rates[i].high, _Digits),
         DoubleToString(rates[i].low, _Digits),
         DoubleToString(rates[i].close, _Digits),
         (long)rates[i].tick_volume,
         (int)rates[i].spread,
         (long)rates[i].real_volume
      );
      written++;
   }
   FileClose(handle);
   WriteStatus("ok", written, first_time, last_time_written, 0);
}
