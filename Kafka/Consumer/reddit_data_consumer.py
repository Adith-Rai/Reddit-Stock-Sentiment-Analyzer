import sys
assert sys.version_info >= (3, 5) # make sure we have Python 3.5+

from pyspark.sql import SparkSession, functions, types

import boto3
import json

import time


#Retrieve credentials for reddit API and kafka from S3
def get_config(bucket="big-data-final-project",key="config/api_tokens.json"):

    #Retrieve keys from S3
    s3_resourse = boto3.client('s3')
    api_tokens = s3_resourse.get_object(Bucket=bucket, Key=key)
    
    config = json.loads(api_tokens['Body'].read().decode('utf-8'))
    
    return config


#Read Kafka stream and write data after cleaning and transforming
def main():
    
    #get config for kafka
    config = get_config()
    servers = ','.join(config["KAFKA_BROKER"])
    time_frame=float(config["data_time_frame"])*3600.0
    
    #create schema
    schema = types.StructType([
    types.StructField('id', types.StringType(), False),
    types.StructField('title', types.StringType(), True),
    types.StructField('body', types.StringType()),
    types.StructField('author', types.StringType()),
    types.StructField('created_utc', types.FloatType()),
    types.StructField('score', types.LongType()),
    types.StructField('is_self', types.BooleanType()),
    types.StructField('parent_id', types.StringType(), False),
    types.StructField('type', types.StringType()),
    ])
    
    #get json data from kafka
    messages = spark.readStream.format('kafka').option('kafka.bootstrap.servers', servers).option('subscribe', config["KAFKA_TOPIC"]).option("kafka.security.protocol","SSL").option("startingOffsets", "earliest").option("failOnDataLoss", "false").load()
    
    #apply schema and set to json
    values = messages.withColumn("response", functions.from_json(messages['value'].cast('string'), schema))
    values = values.select(functions.to_json(values['response']).alias("json"))
    
    #put json values into dataframe
    reddit_content = values.select(functions.json_tuple(values['json'], "id", "title", "body", "author", "created_utc", "score", "is_self", "parent_id", "type")).toDF("id", "title", "body", "author", "created_utc", "score", "is_self", "parent_id", "type")
    
    #remove duplicate records
    reddit_content = reddit_content.dropDuplicates(["id", "parent_id"])
    
    #remove records before the time window we need
    reddit_content = reddit_content.filter(reddit_content["created_utc"] > (time.time() - time_frame))
    
    #remove scores less than 0
    reddit_content = reddit_content.filter(reddit_content["score"] >= 0)
   
    #remove deleted posts and empty posts
    reddit_content = reddit_content.filter( ((reddit_content["title"].isNotNull()) & (reddit_content["title"]!="")) | ((reddit_content["body"].isNotNull()) & (reddit_content["body"]!="") & (reddit_content["body"]!="deleted")))
    
    #set non text post bodies to empty string
    reddit_content = reddit_content.withColumn("body", functions.when(reddit_content["is_self"] == False, "").otherwise(reddit_content["body"]))
    
    #Write to S3 dump
    #function to write to S3 in batches
    def write_batch(df, epoch_id):
        df.write.json(config["S3_DUMP"], mode="append")
        pass 
    reddit_content = reddit_content.writeStream.format("json").trigger(processingTime='5 seconds').outputMode('append').foreachBatch(write_batch).start()
       
    #Keep alive
    reddit_content.awaitTermination()
    

if __name__ == '__main__':
    spark = SparkSession.builder.appName('reddit-data-consume').getOrCreate()
    assert spark.version >= '3.0' # make sure we have Spark 3.0+
    spark.sparkContext.setLogLevel('WARN')
    sc = spark.sparkContext
    main()