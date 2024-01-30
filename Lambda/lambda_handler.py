from write_sentiment_and_stock import write_stock_sentiment

import io

import boto3

import uuid
import json

import pandas as pd

#Read config from S3
def get_s3_json(bucket, key):

    #Retrieve keys from S3
    s3_resourse = boto3.client('s3')
    data = s3_resourse.get_object(Bucket=bucket, Key=key)
    
    config = json.loads(data['Body'].read())
    
    return config

#check config arguments format
def check_config_args(config):

    if not isinstance(config["KAFKA_BROKER"], list):
        print( {'statusCode': 400,'error': "Config in worng format KAFKA_BROKER (s) must be in a list"})       
    if not isinstance(config["KAFKA_TOPIC"], str):
        print( {'statusCode': 400,'error': "Config in worng format KAFKA_TOPIC must be a string"})       
    if not isinstance(config["REDDIT_CLIENT_ID"], str):
        print( {'statusCode': 400,'error': "Config in worng format REDDIT_CLIENT_ID must be a string"})
    if not isinstance(config["REDDIT_SECRET_ID"], str):
        print( {'statusCode': 400,'error': "Config in worng format REDDIT_SECRET_ID must be a string"})
    if not isinstance(config["USER_AGENT"], str):
        print( {'statusCode': 400,'error': "Config in worng format USER_AGENT must be a string"})
    if not isinstance(config["S3_DUMP"], str):
        print( {'statusCode': 400,'error': "Config in worng format KAFKA_BROKER (s) must be in a list"})


def get_s3_json_df(bucket, key):
    
    #Retrieve keys from S3
    s3_resourse = boto3.client('s3')
    data = s3_resourse.get_object(Bucket=bucket, Key=key)
        
    file_df = pd.read_json(data['Body'], lines=True)
    
    return file_df

#write file to S3 dump
def write_to_s3(data_frame, location):
    
    #Prepare json file
    file_buffer = io.StringIO()
    data_frame.to_json(file_buffer, orient="records", lines=True)

    fileName = "partial-"+ str(uuid.uuid4()) + '.json'

    #Get bucket and key
    path_sections = location.split('/')
    bucket = path_sections[2]
    directory = ""
    for i in range(3, len(path_sections)):
        directory += path_sections[i]
        if i < (len(path_sections)-1):
            directory += '/'      
    key = directory + fileName

    s3_resourse = boto3.client('s3')
    try:
        s3_resourse.put_object(Bucket=bucket, Key=key, Body=file_buffer.getvalue())
    except Exception as e:
        return "ERROR: Could NOT write to S3 location: " + location + " - Due to: " + str(e)
        
    return "Wrote un-analyzed data back to: " + location
    
#deletes file from S3
def delete_s3_file(location):

    #Get bucket and key
    path_sections = location.split('/')
    bucket = path_sections[2]
    file_loc = ""
    for i in range(3, len(path_sections)):
        file_loc += path_sections[i]
        if i < (len(path_sections)-1):
            file_loc += '/'      

    #delete S3 
    s3_resourse = boto3.client('s3')
    try:
        s3_resourse.delete_object(Bucket=bucket, Key=file_loc)
    except Exception as e:
        return "ERROR: Could NOT delete S3 file: " + location + " - Due to: " + str(e)
        
    return "Deleted file at: " + location

#function called by lambda function
def lambda_handler(event, context):

    #Get config data for reddit API
    config_data = get_s3_json(bucket="big-data-final-project", key="config/api_tokens.json")
    #Check config format
    check_config_args(config_data)

    #Put this execution's trigger file into a pandas data frame
    trigger_file = get_s3_json_df(bucket=event["Records"][0]["s3"]["bucket"]["name"], key=event["Records"][0]["s3"]["object"]["key"])
    if trigger_file.empty:
        print("Trigger File is empty")
        deleted = delete_s3_file("s3://" + event["Records"][0]["s3"]["bucket"]["name"] + '/' + event["Records"][0]["s3"]["object"]["key"])
        print(deleted)
        return {'statusCode': 200, 'message': 'empty trigger file'}
    
    #Analyze text sentiment and write back sentiment score and current stock price to DynamoDB
    unanalyzed_data = write_stock_sentiment(trigger_file)
    
    #If there is unused data left, write remaining unprocessed data back to trigger location as json
    if not unanalyzed_data.empty:
        writeback_status = write_to_s3(unanalyzed_data, config_data["S3_DUMP"])
        print(writeback_status)
    else:
        print("All data in: " + config_data["S3_DUMP"] + " processed.")
    
    #delete triiger file
    deleted = delete_s3_file("s3://" + event["Records"][0]["s3"]["bucket"]["name"] + '/' + event["Records"][0]["s3"]["object"]["key"])
    print(deleted)
    
    return {
        'statusCode': 200
    }