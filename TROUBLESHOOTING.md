# Troubleshooting Guide

## Issue: Invalid UTF-8 Error in Lambda Invocation

### Problem
```
An error occurred (InvalidRequestContentException) when calling the Invoke operation: 
Could not parse request body into json: Could not parse payload into json: 
Invalid UTF-8 start byte 0x87
```

### Root Cause
The `echo` command in bash can introduce invalid UTF-8 characters (like BOM - Byte Order Mark) when creating JSON files, especially when dealing with nested JSON strings.

### Solution Applied

**Before:**
```bash
echo '{"body": "{\"ticketId\":\"TEST-001\"}"}' > test-event.json
```

**After:**
```bash
cat > test-event.json << 'EOF'
{
  "body": "{\"ticketId\":\"TEST-001\"}"
}
EOF
```

### Why This Works
- `cat` with heredoc (`<< 'EOF'`) creates clean UTF-8 files without BOM
- Single quotes around `'EOF'` prevent variable expansion
- No shell interpretation of escape sequences

### Additional Recommendations

1. **Use Base64 Encoding for Complex Payloads:**
```bash
echo '{"body": "..."}' | base64 > test-event.b64
aws lambda invoke --payload fileb://test-event.b64 ...
```

2. **Use Python for JSON Creation:**
```bash
python3 -c 'import json; print(json.dumps({"body": "..."}))' > test-event.json
```

3. **Validate JSON Before Sending:**
```bash
cat test-event.json | jq .  # Validates JSON syntax
```

### Testing the Fix

Run the updated workflow or use the test script:
```bash
./test-lambda.sh
```

The test script now uses heredoc for all test event creation, ensuring clean UTF-8 encoding.

---

**Last Updated:** January 7, 2025
