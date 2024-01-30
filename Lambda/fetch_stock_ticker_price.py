import yfinance as yf

import time
from functools import wraps
import pandas as pd

def limit_rate(limit_count, limit_interval):
    def decorator(func):
        call_times = []
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_time = time.time()
            call_times.append(current_time)
            call_times[:] = [t for t in call_times if current_time - t <= limit_interval]
            
            if len(call_times) <= limit_count:
                return func(*args, **kwargs)
            else:
                time.sleep(limit_interval - (current_time - call_times[0]))
                return func(*args, **kwargs)
        
        return wrapper
    return decorator

def parse_stock_price_df(stock_data_df, start_date, end_date):
    filler_dict = {
    'Date': pd.date_range(start_date, end_date)}
    
    filler_df = pd.DataFrame(filler_dict)
    filler_df["Date"] = filler_df["Date"].astype(str)

    merged_df = filler_df.set_index("Date").join(stock_data_df.set_index("Date"), how='left').reset_index().rename(columns={"index":"Date"})
    merged_df = merged_df.set_index("Date")
    
    return merged_df.reset_index()


# @limit_rate(5,60)
def get_stock_prices_yahoo(ticker, start_date, end_date):
    stock_data_raw_df = yf.download(ticker, start=start_date, end=end_date)
    stock_data_df = stock_data_raw_df.reset_index()
    stock_data_df["Date"] = stock_data_df["Date"].astype(str)
    if(stock_data_df.shape[0]==0): return None
    resp_df = parse_stock_price_df(stock_data_df, start_date, start_date)
    resp_df["stock_ticker"] = ticker
    resp_df.rename(columns={"Date":"date","Close":"closing_price"}, inplace=True)
    return resp_df[["date","closing_price","stock_ticker"]]
