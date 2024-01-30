from decimal import Decimal
from reddit_text_analysis import * 
from fetch_stock_ticker_price import *

from openai import OpenAI
import tiktoken

from functools import partial
import datetime #import datetime, timedelta
import uuid
import json

import boto3

def get_s3_json(bucket, key):

    #Retrieve keys from S3
    s3_resourse = boto3.client('s3')
    data = s3_resourse.get_object(Bucket=bucket, Key=key)
    
    config = json.loads(data['Body'].read())
    
    return config
    
def fetch_system_messege(bucket, key):

    #Retrieve keys from S3
    s3_resourse = boto3.client('s3')
    data = s3_resourse.get_object(Bucket=bucket, Key=key)
    
    file = data['Body'].read().decode("utf-8")
    
    return file


#Analyze text sentiment and write back sentiment score and current stock price to DynamoDB
def write_stock_sentiment(scrapped_data_df):

    system_prompt_uri = "reddit_text_analysis_prompt.txt"
    config_data = get_s3_json(bucket="big-data-final-project", key="config/api_tokens.json")
    input_envelope = config_data["INPUT_ENVELOPE"]
    newline_delimeter = config_data["NEWLINE_DELIMETER"]
    
    #Only analyze posts
    scrapped_data_df = scrapped_data_df.loc[scrapped_data_df["type"]=="post"].reset_index(drop=True)
    if scrapped_data_df.empty:
        return scrapped_data_df
    
    #save a copy (in memory) of the superset of data to write back
    return_df = scrapped_data_df.copy()
    
    #Limit the number of entries to half the number of possible tokens per post (since we cant send and recieve more than 2000-4000 tokens per request anyway)
    scrapped_data_df = scrapped_data_df.head(int(config_data["MAX_TOKENS"]//4))
    
    #prefix title to body and 
    scrapped_data_df["body"] = scrapped_data_df["title"] + "\n" + scrapped_data_df["body"]
    scrapped_data_df["body"] = scrapped_data_df["body"].str.replace(newline_delimeter,"").replace(input_envelope,"")
    
    
    #Prefix the date to text that will have their sentiment analyzed
    scrapped_data_df["created_utc"] = scrapped_data_df["created_utc"].apply(lambda x: datetime.datetime.utcfromtimestamp(int(x)).strftime('%Y-%m-%d'))
    scrapped_data_df["body"] = scrapped_data_df["created_utc"] + " " + scrapped_data_df["body"]
    
    #Create client
    openai_client = OpenAI(api_key=config_data["OPENAI_API_KEY"])
    model, temperature, max_tokens = (
        config_data["OPENAI_MODEL_NAME"], int(config_data["TEMPERATURE"]), int(config_data["MAX_TOKENS"])
        )

    encoder = tiktoken.encoding_for_model(model)
    
    
    #Conduct sentiment analysis on text
    raw_system_message =  fetch_system_messege(bucket="big-data-final-project", key= 'lambda-package/'+system_prompt_uri)
    
    system_message  = raw_system_message.replace("newline_delimeter",newline_delimeter)

    fetch_openai_response_with_context = partial(fetch_openai_response, openai_client=openai_client,system_message = system_message, model=model, temperature=temperature, max_tokens=max_tokens)
    fetch_num_tokens_with_model = partial(fetch_num_tokens, encoder = encoder)
    parse_openai_response_with_newline_delimeter = partial(parse_openai_response, newline_delimeter = newline_delimeter)

    post_contents = scrapped_data_df["body"].values

    enveloped_messages_list = list(
                                map(
                                    lambda row_text : f"""{input_envelope}{row_text}{input_envelope}""" ,post_contents
                                    )
                                )
    
    #Get token lengths
    #Did not try - except this because we want to break the function if this fails
    token_lengths = fetch_num_tokens(enveloped_messages_list, encoder)

    #Select data to analize
    row_count, input_batches = fetch_batches(enveloped_messages_list,token_lengths, max_tokens)
    padded_input_batches = newline_delimeter.join(input_batches)
    
    #Analize sentiment of text data
    raw_responses_objs = None
    try:
        raw_responses_objs = fetch_openai_response_with_context(padded_input_batches)
    except Exception as e:
        print("ERROR: Text sentiment analyzer returned error: ",e)
        if row_count==0 and (row_count is not None):
            print("No text data analyzed")
            return pd.DataFrame()
        else: 
            return return_df[row_count:]
    
    #Format results of analysis
    results = parse_openai_response_with_newline_delimeter(raw_responses_objs)

    results_list = fix_open_ai_response_format( results)
 
    
    #Get ticker price for post date of analyzed texts
    df = pd.DataFrame()
    for result  in results_list:
        for key in result.keys(): 
            if key=="NaS": continue
            next_day = datetime.datetime.strptime(result[key]["timestamp"], '%Y-%m-%d') + datetime.timedelta(days=1)
            curr_df = None
            try:
                curr_df = get_stock_prices_yahoo(key,result[key]["timestamp"], next_day.strftime('%Y-%m-%d') ) #get for only post creation date
            except Exception as e:
                print("ERROR: yfinance api error: ",e)
                continue
            if(isinstance(curr_df, type(None))): continue
            curr_df["sentiment_inference"] = result[key]["sentiment_score"]
            curr_df["reasoning"] = result[key]["reasoning"]
            df = pd.concat([df, curr_df], ignore_index=True)
    df['id_column'] = [uuid.uuid4() for _ in range(len(df.index))]
    
    #Write stock data and stock sentiment to dynamoDB
    dynamodb = boto3.resource('dynamodb', region_name=config_data["REGION_NAME"], aws_access_key_id=config_data["AWS_ACCESS_KEY_ID"], aws_secret_access_key=config_data["AWS_SECRET_ACCESS_KEY"])
    stock_table = dynamodb.Table('TBL_RedditStockSentiment')

    with stock_table.batch_writer() as writer:
        for i in range(len(df)):
        # print(updation)
            stock_table.put_item(Item={
                'ID' : str(df['id_column'][i]),
                'Stock_Ticker' : df['stock_ticker'][i].upper(),
                'Closing_Price' : Decimal(df['closing_price'][i]),
                'Date' : df['date'][i],
                'Sentiment_Inference' : int(df['sentiment_inference'][i]),
                'Reasoning' : df['reasoning'][i]
            })
            print("Wrote stock and sentiment to DB: ", df['stock_ticker'][i], int(df['sentiment_inference'][i]), Decimal(df['closing_price'][i]))
    
    
    #return dataframe of all un-analyzed text
    if row_count==0 and (row_count is not None):
        print("No text data analyzed")
        return pd.DataFrame()
    return return_df[row_count:]