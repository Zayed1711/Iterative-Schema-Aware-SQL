import json
import random
import csv
import os
import sqlite3
import ollama
import time
import re

def estimate_hardness(sql_string):
    """A proxy heuristic to estimate Spider difficulty based on SQL complexity."""
    sql = sql_string.upper()
    
    # Count complex operations
    joins = sql.count("JOIN")
    nested = max(0, sql.count("SELECT") - 1) # First SELECT doesn't count
    groupings = sql.count("GROUP BY") + sql.count("ORDER BY") + sql.count("HAVING")
    set_ops = sql.count("INTERSECT") + sql.count("UNION") + sql.count("EXCEPT")
    
    score = joins + nested + groupings + set_ops
    
    if score == 0:
        return "easy"
    elif score == 1:
        return "medium"
    elif score == 2:
        return "hard"
    else:
        return "extra" # 3 or more operations is extra hard

def get_stratified_sample(spider_dev_path, seed=42, total_target=500):
    """Extracts a balanced sample, backfilling if any category falls short."""
    with open(spider_dev_path, 'r') as f:
        data = json.load(f)
        
    categorized = {"easy": [], "medium": [], "hard": [], "extra": []}
    
    for item in data:
        sql_query = item.get("query", "")
        hardness = estimate_hardness(sql_query)
        item['hardness'] = hardness 
        categorized[hardness].append(item)
            
    random.seed(seed)
    sample = []
    target_per_bucket = total_target // 4
    unused_queries = []
    
    print("Stratifying dataset based on heuristic complexity...")
    for level in categorized:
        random.shuffle(categorized[level])
        # Grab up to the target amount
        selected = categorized[level][:target_per_bucket]
        sample.extend(selected)
        
        # Save the leftovers in case we need to backfill
        unused_queries.extend(categorized[level][target_per_bucket:])
        print(f" -> {level.capitalize()}: Loaded {len(selected)} queries.")
        
    # The Smart Backfill: If we didn't hit 100, fill the gap
    shortfall = total_target - len(sample)
    if shortfall > 0:
        print(f" -> Shortfall detected. Backfilling {shortfall} queries to reach {total_target}...")
        random.shuffle(unused_queries)
        sample.extend(unused_queries[:shortfall])
        
    print(f"Total Benchmark Sample: {len(sample)} queries.")
    return sample

def test_sql_silently(db_path, generated_sql):
    """Runs the SQL. Returns (True, latency) or (False, error_msg)."""
    start_time = time.time()
    try:
        # Connect to the specific Spider SQLite database for this query
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(generated_sql)
        cursor.fetchall() 
        conn.close()
        return True, (time.time() - start_time), None
    except Exception as e:
        return False, 0.0, str(e)



def extract_sql_from_markdown(text):
    """Strips conversational text and extracts only the SQL code."""
    # First, look for code wrapped in ```sql ... ```
    sql_match = re.search(r'```sql(.*?)```', text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        return sql_match.group(1).strip()
    
    # Next, look for generic code blocks ``` ... ```
    generic_match = re.search(r'```(.*?)```', text, re.DOTALL)
    if generic_match:
        return generic_match.group(1).strip()
        
    # If no markdown blocks exist, assume it followed the rules and return raw text
    return text.strip()

def run_iterative_framework(user_query, schema_text, db_path, max_retries=3):
    """The self-correction loop for the 1.5B model."""
    
    system_prompt = f"""You are a strict SQLite expert.
    Rule 1: Return ONLY valid SQL code. 
    Rule 2: Do NOT use tables or columns that do not exist in the schema.
    Rule 3: If the question CANNOT be answered with the provided schema, return exactly: UNANSWERABLE.
    Schema:\n{schema_text}"""
    
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_query}
    ]
    
    attempts = 0
    total_exec_time = 0.0
    
    while attempts < max_retries:
        attempts += 1
        
        # 1. Generate SQL locally
        response = ollama.chat(model='qwen2.5-coder:1.5b', messages=messages)
        raw_ai_output = response['message']['content'].strip()
        
        # 2. Extract the actual SQL (fixing the conversational bug)
        ai_sql = extract_sql_from_markdown(raw_ai_output)
        
        print(f"\n[Attempt {attempts}] Cleaned AI SQL: {ai_sql}") 
        
        # 3. Check Fail-Safe
        if "UNANSWERABLE" in ai_sql.upper():
            return "UNANSWERABLE", attempts, total_exec_time
            
        # 4. Test the SQL silently
        is_valid, exec_time, error_msg = test_sql_silently(db_path, ai_sql)
        total_exec_time += exec_time
        
        if is_valid:
            print(f"[Attempt {attempts}] DB Status: SUCCESS") 
            return "SUCCESS", attempts, total_exec_time
        else:
            print(f"[Attempt {attempts}] DB Error: {error_msg}") 
            # 5. The Magic Feedback Loop
            messages.append({'role': 'assistant', 'content': raw_ai_output})
            messages.append({'role': 'user', 'content': f"Executing that SQL gave this SQLite error: '{error_msg}'. Fix the syntax based ONLY on the provided schema. Do not explain, just output the fixed SQL."})
            
    # If it fails 3 times, it safely exits here (this prevents the NoneType crash)
    return "FAILED_RETRY_LIMIT", attempts, total_exec_time



def build_schema_string(db_id, all_schemas):
    """
    Finds the specific database in Spider's tables.json and builds a clean 
    text blueprint of the tables and columns for the AI.
    """
    # Find the specific schema for this database
    db_schema = next((db for db in all_schemas if db['db_id'] == db_id), None)
    if not db_schema:
        return "Schema not found."

    table_names = db_schema['table_names_original']
    column_data = db_schema['column_names_original']
    
    schema_text = ""
    
    # Loop through each table and attach its columns
    for table_idx, table_name in enumerate(table_names):
        # Column format in Spider is [table_index, column_name]
        # We ignore index -1 (which usually represents the '*' wildcard)
        cols = [col[1] for col in column_data if col[0] == table_idx]
        
        schema_text += f"Table: {table_name} ({', '.join(cols)})\n"
        
    return schema_text.strip()

def run_benchmark():
    print("Initializing Spider Benchmark Rig...")
    
    # 1. Load the 100 balanced queries
    spider_dev_path = "dataset/spider_data/dev.json" # Adjust path if needed
    queries = get_stratified_sample(spider_dev_path, total_target=500)
    
    # Load schemas (tables.json) to dynamically inject blueprints
    with open("dataset/spider_data/tables.json", 'r') as f:
        schemas = json.load(f)
        
    csv_filename = 'spider_run_final_500.csv'
    
    with open(csv_filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        # We log the exact metrics ICDE/CIKM reviewers want to see
        writer.writerow(['Query_ID', 'Database', 'Difficulty', 'Outcome', 'Attempts', 'Total_Latency_Seconds'])
        
        for idx, q in enumerate(queries):
            db_id = q['db_id']
            difficulty = q.get('hardness', 'unknown')
            user_question = q['question']
            
            # Construct exact paths dynamically for each query
            db_path = f"dataset/spider_data/database/{db_id}/{db_id}.sqlite"
            
            # --- THE FIX: Dynamically generate the real schema! ---
            schema_text = build_schema_string(db_id, schemas) 
            
            print(f"[{idx+1}/500] Testing DB: {db_id} | Diff: {difficulty}")
        
            
            # Record End-to-End Latency (AI Generation + DB Execution)
            start_time = time.time()
            
            # Run the framework!
            result, attempts, db_exec_time = run_iterative_framework(user_question, schema_text, db_path, max_retries=3)

            total_time = time.time() - start_time
            
            writer.writerow([idx+1, db_id, difficulty, result, attempts, round(total_time, 2)])
            print(f"      -> Result: {result} | Loops: {attempts} | Time: {total_time:.2f}s")
            
    print(f"\nBenchmark Complete! Results saved to {csv_filename}")

if __name__ == "__main__":
    run_benchmark()