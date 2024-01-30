from itertools import chain
import time
import json
import re
from functools import wraps


def old_fetch_system_messege(system_prompt_uri):
    with open(system_prompt_uri, 'r') as file:
        file_contents = file.read()
    
    return file_contents

def parse_openai_response(raw_response, newline_delimeter):
    str_resp = str(raw_response).replace(newline_delimeter,",").replace("\\n\\n",",").replace("\\n",",").replace("\\","")
    start = str_resp.find('(content=\'')
    end = str_resp.find('}}\'')
    if (start == -1) or (end == -1):
        return [{}]
    response = str_resp[ start + len('(content=\'')   : end + len('}}\'')-1  ]
    to_dict = '{\"data\":['+response+']}'.replace("\\n\\n",",").replace("\\n",",").replace("\\","")
    
    response ={}
    try:
        ret_val = re.sub('\,\,+', ',', to_dict)
        response = json.loads(ret_val)
    except Exception as e:
        print("ERROR: Invalid response format from sentiment annalyzer", e)
    
    return response

def fetch_num_tokens(text_list, encoder):

    return [len(encoded_text) for encoded_text in encoder.encode_batch(text_list) ]


def fetch_batches(input_text_list, token_lengths,  batch_size):
    curr_batch, curr_batch_token_cnt, row_count = list(), 0, 0

    for input_text, token_cnt in zip(input_text_list, token_lengths):
        
        if(token_cnt>batch_size): 
            row_count += 1
            continue

        if(curr_batch_token_cnt+token_cnt<batch_size):
            curr_batch_token_cnt+=token_cnt
            curr_batch.append(input_text)
            row_count += 1
        else:
            #yield curr_batch
            return row_count, curr_batch #we want only one batch
            curr_batch, curr_batch_token_cnt = [input_text], token_cnt
    
    #yield curr_batch
    return row_count, curr_batch #we want only one batch


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


def fetch_openai_response(user_message,openai_client, system_message, model="gpt-3.5-turbo", temperature=0, max_tokens =500):
    messages =  [  
                    {'role':'system', 
                    'content': system_message},    
                    {'role':'user', 
                    'content':user_message },  
                ] 
    



    raw_response = openai_client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature, 
        max_tokens=max_tokens,
    )

    return raw_response

def fix_open_ai_response_format(response):
    
    if (not isinstance(response, dict)) or ("data" not in response):
        return []
    
    result_list = response["data"]

    return result_list