import boto3
import math
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from constants import EMBED_TABLE_NAME

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(EMBED_TABLE_NAME)

def compute_cosine_similarity(text1, text2):
    """
    Compute cosine similarity between two strings using word frequency vectors.
    Optimized with early returns and minimal processing.
    """
    if not text1 or not text2:
        return 0.0
    
    words1 = text1.lower().split()
    words2 = text2.lower().split()
    
    # Early return for very different length texts
    len_ratio = len(words1) / len(words2) if len(words2) > 0 else 0
    if len_ratio > 5 or len_ratio < 0.2:
        return 0.0

    counter1 = Counter(words1)
    counter2 = Counter(words2)

    intersection = set(counter1.keys()) & set(counter2.keys())
    
    # Early return if no common words
    if not intersection:
        return 0.0
        
    dot_product = sum(counter1[x] * counter2[x] for x in intersection)

    norm1 = math.sqrt(sum(v ** 2 for v in counter1.values()))
    norm2 = math.sqrt(sum(v ** 2 for v in counter2.values()))

    if not norm1 or not norm2:
        return 0.0

    return dot_product / (norm1 * norm2)

def process_batch(items, new_ticket_body, threshold):
    """Process a batch of items for similarity computation."""
    similarities = []
    for item in items:
        past_body = item.get("ticketBody", "")
        similarity = compute_cosine_similarity(new_ticket_body, past_body)
        if similarity >= threshold:
            similarities.append({
                "ticketId": item.get("ticketId"),
                "ticketSubject": item.get("ticketSubject"),
                "ticketBody": past_body,
                "response": item.get("response"),
                "similarity": round(similarity, 3),
                "timestamp": item.get("timestamp")
            })
    return similarities

def parallel_scan_with_pagination(table, new_ticket_body, threshold=0.7, max_workers=4):
    """
    Perform parallel scan with pagination to handle large datasets efficiently.
    """
    all_similarities = []
    
    def scan_segment(segment, total_segments):
        segment_similarities = []
        scan_kwargs = {
            'Segment': segment,
            'TotalSegments': total_segments,
            'Select': 'ALL_ATTRIBUTES'
        }
        
        try:
            while True:
                response = table.scan(**scan_kwargs)
                items = response.get('Items', [])
                
                if items:
                    batch_similarities = process_batch(items, new_ticket_body, threshold)
                    segment_similarities.extend(batch_similarities)
                
                # Check if there are more items to scan
                if 'LastEvaluatedKey' not in response:
                    break
                scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
                
                # Add small delay to avoid throttling
                time.sleep(0.01)
                
        except Exception as e:
            print(f"Error in segment {segment}: {str(e)}")
            
        return segment_similarities
    
    # Use parallel scanning with multiple segments
    total_segments = max_workers
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(scan_segment, i, total_segments)
            for i in range(total_segments)
        ]
        
        for future in as_completed(futures):
            try:
                segment_result = future.result()
                all_similarities.extend(segment_result)
            except Exception as e:
                print(f"Error processing segment: {str(e)}")
    
    return all_similarities

def search_similar_ticket_response(new_ticket_body, threshold=0.7, top_n=3, max_workers=4):
    """
    Optimized search for similar ticket responses with parallel processing.
    """
    try:
        start_time = time.time()
        
        # Get all similarities using parallel scan
        all_similarities = parallel_scan_with_pagination(
            table, new_ticket_body, threshold, max_workers
        )
        
        # Sort by highest similarity and return top N
        all_similarities.sort(key=lambda x: x["similarity"], reverse=True)
        result = all_similarities[:top_n]
        
        end_time = time.time()
        processing_time = round(end_time - start_time, 2)
        
        return {
            "results": result,
            "total_found": len(all_similarities),
            "processing_time_seconds": processing_time,
            "status": "success"
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}