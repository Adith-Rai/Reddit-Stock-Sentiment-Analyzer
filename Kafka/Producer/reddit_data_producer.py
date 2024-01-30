import sys

import json

import boto3

import praw

import kafka


#Read config and input json from S3
def get_s3_json(bucket, key):

    #Retrieve keys from S3
    s3_resourse = boto3.client('s3')
    data = s3_resourse.get_object(Bucket=bucket, Key=key)
    
    config = json.loads(data['Body'].read().decode('utf-8'))
    
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
   
#check inputs arguments format
def check_input_args(input_data):

    sorting = input_data["sorting"]
    stock_subreddit = input_data["subreddit"]
    limit = input_data["post_limit"]
    depth = input_data["comment_depth"]
    sortings = []
    stock_subreddits = []
    if isinstance(sortings, str):
        sortings = [sorting]
    elif isinstance(sortings, list):
        sortings = sorting
    else:
        print( {'statusCode': 400,'error': "Input is wrong format, please use a string or list for sorting"})
    if isinstance(stock_subreddit, str):
        stock_subreddits = [stock_subreddit]
    elif isinstance(stock_subreddit, list):
        stock_subreddits = stock_subreddit
    else:
        print( {'statusCode': 400,'error': "Input is wrong format, please use a string or list for stock_subreddit"})       
    if not isinstance(limit, int):
        print( {'statusCode': 400,'error': "Input is wrong format, please use a string or list for sorting"})      
    elif limit > 1000:
        limit = None
    if not isinstance(depth, int):
        print( {'statusCode': 400,'error': "Input is wrong format, please use a string or list for sorting"})      
    elif depth > 1000:
        limit = None
        
    return stock_subreddits, sortings, limit, depth


#Extract required data from posts and send to kafka, return comment objects
def send_posts_to_kafka(config, posts):
    
    #KAFKA Config
    kafka_server = config["KAFKA_BROKER"]
    topic = config["KAFKA_TOPIC"]
    
    #Connect the producer to kafka endpoint, serialize to json
    producer = kafka.KafkaProducer(security_protocol="SSL", bootstrap_servers = kafka_server, value_serializer = lambda data: json.dumps(data).encode('utf-8'))
    
    error = 0
    success = 0
    comments = []
    
    #lazy evaluation, so posts are retrieved here
    #get important data from posts
    try:
        for post in posts:
            post_dict = {}
            post_dict["id"] = post.id
            post_dict["title"] = post.title
            post_dict["body"] = post.selftext
            post_dict["author"] = post.author.name if (post.author is not None) else "deleted"
            post_dict["created_utc"] = post.created_utc
            post_dict["score"] = post.score
            post_dict["is_self"] = post.is_self
            post_dict["parent_id"] = post.subreddit.id 
            post_dict["type"] = "post"
            
            #get comments object of post
            comments.append(post.comments)
            
            #send to kafka
            #Dictionaries are ordered in python 3.7+, though this is hardly relevant overall
            producer.send(topic, post_dict)
            
            success += 1
            
    except Exception as e:
        print("Error while retrieving or sending reddit posts, this set of posts is abandoned: ",e)
        error += 1
        
       
    #flush the remaining data and close the stream     
    producer.flush()
    producer.close()
    
    return (comments, success, error)
    

#Extract required data from comments from retrieved posts and send to kafka
def send_comments_to_kafka(config, posts_comments, comment_depth=None):
    
    #KAFKA Config
    kafka_server = config["KAFKA_BROKER"]
    topic = config["KAFKA_TOPIC"]
    
    #Connect the producer to kafka endpoint, serialize to json
    producer = kafka.KafkaProducer(security_protocol="SSL", bootstrap_servers = kafka_server, value_serializer = lambda data: json.dumps(data).encode('utf-8'))
    
    error = 0
    success = 0
    
    #Iterate over comments of each retrieved post
    for comments in posts_comments:
        
        #Get all comments for post till specified depth
        try:
            comments.replace_more(limit=comment_depth)
        except Exception as e:
            print("Error while retrieving reddit comments, this set of comments is abandoned: ",e)
            error += 1
            continue
        
        #get important data from comments
        try:
            for comment in comments.list():
                comment_dict = {}
                comment_dict["id"] = comment.id
                comment_dict["title"] = ""
                comment_dict["body"] = comment.body
                comment_dict["author"] = comment.author.name if (comment.author is not None) else "deleted"
                comment_dict["created_utc"] = comment.created_utc
                comment_dict["score"] = comment.score
                comment_dict["is_self"] = True
                comment_dict["parent_id"] = comment.parent_id
                comment_dict["type"] = "comment"
                
                #send to kafka
                #Dictionaries are ordered in python 3.7+, though this is hardly relevant overall
                producer.send(topic, comment_dict)
                
                success += 1
                
        except Exception as e:
            print("Error while retrieving or sending reddit comments, this set of comments is abandoned: ",e)
            error += 1
            continue
        
       
    #flush the remaining data and close the stream     
    producer.flush()
    producer.close()
    
    return (success, error)
    
    
#Get posts from reddit
def scrape_reddit_posts(config, subreddit_name="StockMarket", sort="top", posts_limit=None):
    
    #Create reddit client
    reddit_client = praw.Reddit(
    client_id=config["REDDIT_CLIENT_ID"],
    client_secret=config["REDDIT_SECRET_ID"],
    user_agent=config['USER_AGENT'])
    
    #get subreddit posts 
    subreddit = reddit_client.subreddit(subreddit_name)
    
    #Initialize return values
    comments = []
    success = 0
    error = 0
    
    #posts of different sorting methods
    if sort=="top":
        comments, success, error = send_posts_to_kafka(config, subreddit.top(limit=posts_limit))
    elif sort=="hot":
        comments, success, error = send_posts_to_kafka(config, subreddit.hot(limit=posts_limit))
    elif sort=="new":
        comments, success, error = send_posts_to_kafka(config, subreddit.new(limit=posts_limit))
    elif sort=="controversial":
        comments, success, error = send_posts_to_kafka(config, subreddit.controversial(limit=posts_limit))
    elif sort=="gilded":
        comments, success, error = send_posts_to_kafka(config, subreddit.gilded(limit=posts_limit))
    elif sort=="rising":
        comments, success, error = send_posts_to_kafka(config, subreddit.rising(limit=posts_limit))
    else:
        return (comments, success, error)
    
    return (comments, success, error)
   
   
#Running code
def main():
    
    #Get config data for reddit API
    config_data = get_s3_json(bucket="big-data-final-project", key="config/api_tokens.json")
    #Check config format
    check_config_args(config_data)
    
    #Get inputs for fucntion
    input_data = get_s3_json(bucket="big-data-final-project", key="producer/inputs/producer_input.json")    
    #Check Input format
    stock_subreddits, sortings, limit, depth = check_input_args(input_data)
    
    #Initialize success and error counts
    success = 0
    error = 0
    
    #Get data from all desired subreddits
    for subreddit in stock_subreddits:    
        comments = []   
        
        #get posts from all sortings of subreddit (max of ~1000 from each sorting method, so overall always > 7000 items in list)
        for sorting in sortings:     
            print("sending posts of: ",subreddit, sorting)
            c, s, e = scrape_reddit_posts(config=config_data, subreddit_name=subreddit, sort=sorting, posts_limit=limit)            
            comments.extend(c)
            success += s
            error += e
        
        #Retrieve comments for all desired sortings of subreddit
        if depth >= 0:
            print("sending comments of: ",subreddit, sorting)
            s, e = send_comments_to_kafka(config_data, comments, comment_depth=depth)
            success += s
            error += e
    
    print( {'succesful_sends': success,'errors': error} )
    

if __name__ == '__main__':
    main()
