import re
import json
import quopri
import html
from bs4 import BeautifulSoup

def extract_actual_message(ticket_subject: str, ticket_body: str) -> str:
    if not ticket_body or not ticket_body.strip():
        return "Ticket body is empty."

    # Step 1: Decode quoted-printable
    try:
        decoded_body = quopri.decodestring(ticket_body).decode('utf-8', errors='ignore')
    except Exception:
        decoded_body = ticket_body

    # Step 2: Parse HTML and extract visible text
    soup = BeautifulSoup(decoded_body, 'html.parser')
    text_only = soup.get_text(separator='\n')
    text_only = html.unescape(text_only)

    # Step 3: Normalize whitespace and line breaks
    text_only = re.sub(r'\r', '', text_only)
    text_only = re.sub(r'\n+', '\n', text_only)
    text_only = re.sub(r'[ \t]+', ' ', text_only)
    clean_body = text_only.strip()

    if not clean_body:
        return "Ticket body contained no readable text."

    # Step 4: Remove email headers
    header_pattern = re.compile(
        r'^(Delivered-To|Received|Authentication-Results|ARC|Return-Path|DKIM-Signature|'
        r'Message-ID|Content-Type|Content-Transfer-Encoding|MIME-Version|X-[\w-]+|Thread-|'
        r'Received-SPF|SPF|DKIM|DMARC|ARC-Seal|ARC-Message-Signature|ARC-Authentication-Results):.*(?:\n\s+.*)*',
        re.IGNORECASE | re.MULTILINE
    )
    clean_body = re.sub(header_pattern, '', clean_body).strip()

    # Step 5: Try extracting full JSON blocks using balanced braces
    def find_json_blocks(text: str) -> list[str]:
        jsons = []
        stack = []
        start_idx = None
        for idx, char in enumerate(text):
            if char == '{':
                if not stack:
                    start_idx = idx
                stack.append('{')
            elif char == '}':
                if stack:
                    stack.pop()
                    if not stack and start_idx is not None:
                        candidate = text[start_idx:idx + 1]
                        try:
                            json.loads(candidate)
                            jsons.append(candidate)
                        except json.JSONDecodeError:
                            pass
                        start_idx = None
        return jsons

    json_blocks = find_json_blocks(clean_body)
    for block in json_blocks:
        try:
            parsed = json.loads(block)
            return json.dumps(parsed, indent=2)
        except json.JSONDecodeError:
            continue

    # Step 6: AWS CloudWatch alarm fallback logic - extract up to end of Threshold block
    aws_alarm_match = re.search(
        r"You are receiving this email because your Amazon CloudWatch Alarm.*?",
        clean_body,
        re.DOTALL
    )
    if aws_alarm_match:
        start_idx = aws_alarm_match.start()
        content = clean_body[start_idx:]

        # Look for the earliest ending point with expanded patterns:
        ending_patterns = [
            # Process information sections
            r"^Top 5 processes.*",
            r"^Top \d+ processes.*",
            r"^Top Command Output.*",
            r"^Process details.*",
            r"^Running processes.*",
            
            # Storage and disk information
            r"^Storage Utilization Details.*",
            r"^Disk Usage Details.*",
            r"^File System Details.*",
            r"^Volume Information.*",
            r"^Partition Details.*",
            
            # Memory and CPU details
            r"^Memory Consumption Output.*",
            r"^Memory Usage Details.*",
            r"^CPU Usage Breakdown.*",
            r"^System Resource Details.*",
            r"^Performance Metrics.*",
            
            # Network information
            r"^Network Interface Details.*",
            r"^Network Statistics.*",
            r"^Traffic Details.*",
            
            # System information
            r"^System Information.*",
            r"^Host Details.*",
            r"^Instance Details.*",
            r"^Server Information.*",
            
            # Log sections
            r"^Log Details.*",
            r"^Error Logs.*",
            r"^Recent Logs.*",
            
            # Troubleshooting sections
            r"^Troubleshooting Steps.*",
            r"^Recommended Actions.*",
            r"^Next Steps.*",
            r"^Resolution Steps.*",
            
            # Footer/signature patterns
            r"^(Regards|Thanks|Thank you|Sincerely|Best Regards|Kind Regards).*",
            r"^--+.*",  # Signature separator
            r"^This email was sent.*",
            r"^Please do not reply.*",
            r"^For more information.*",
            r"^AWS Support.*",
            r"^Amazon Web Services.*",
            
            # Common email footers
            r"^Disclaimer:.*",
            r"^CONFIDENTIAL.*",
            r"^This message.*confidential.*",
            
            # Unsubscribe patterns
            r"^To unsubscribe.*",
            r"^Unsubscribe.*",
            r"^If you no longer wish to receive.*",
            
            # Additional technical sections
            r"^Application Logs.*",
            r"^Service Status.*",
            r"^Health Check Results.*",
            r"^Monitoring Data.*",
            r"^Threshold Details.*",
            r"^Alert History.*",
            r"^Previous Alerts.*",
            
            # Time-based sections
            r"^Recent Activity.*",
            r"^Last 24 hours.*",
            r"^Historical Data.*",
            
            # Administrative sections
            r"^Account Information.*",
            r"^Billing Information.*",
            r"^Contact Information.*"
        ]
        
        # Find all matches for ending patterns
        matches = []
        for pattern in ending_patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
            if match:
                matches.append(match)
        
        # Determine which match ends earliest
        if matches:
            earliest = min(matches, key=lambda m: m.start())
            end_idx = earliest.start()
            return content[:end_idx].strip()
        else:
            # Fallback: return whole content if no end marker found
            return content.strip()

    # Step 7: Enhanced simple summary logic (body and subject)
    summary_lines = []
    summary_pattern = re.compile(
        r'\[[^\]]+\]\s*\[\s*(?:🔴|🟢|⚠️|✅|Down|Up|Critical|OK|Info)[^\]]*\].*',
        re.UNICODE | re.IGNORECASE
    )
    for line in clean_body.splitlines():
        line = line.strip()
        if not line:
            continue
        if summary_pattern.match(line):
            summary_lines.append(line)
        elif re.search(r'^Time \(UTC\):', line):
            summary_lines.append(line)

    if summary_lines:
        return "\n".join(summary_lines)

    # Step 7 fallback: Search summary in subject
    if ticket_subject:
        subject_lines = []
        for line in ticket_subject.splitlines():
            if summary_pattern.search(line):
                subject_lines.append(line.strip())
        if subject_lines:
            return "\n".join(subject_lines)

    # Step 8: Extract message between greeting and signature
    greeting_keywords = r"(Hi|Hello|Hey|Hii|Dear|Greetings|Good\s+(morning|afternoon|evening)|Hi\s+Team|Hello\s+Team|Hi\s+All|Hello\s+All)"
    closing_keywords = r"(Regards|Thanks|Thank you|Sincerely|Cheers|Best\s+Regards|Warm\s+Regards|Kind\s+Regards|Looking forward to your (support|response|insights|reply)|With\s+gratitude|Faithfully|Yours\s+(truly|faithfully))"
    message_match = re.search(
        rf"(?P<msg>\b{greeting_keywords}\b[\s\S]{{0,5000}}?)(?=\n*{closing_keywords}\b)",
        clean_body,
        re.IGNORECASE
    )
    if message_match:
        clean_body = message_match.group("msg").strip()

    # Step 9: Remove quoted original email content
    clean_body = re.split(
        r'(?i)(From: .*|On .* wrote:|Sent from my .*|-----Original Message-----|Begin forwarded message:)',
        clean_body
    )[0].strip()

    # Step 10: Remove email signatures
    signature_patterns = [
        r'^--\s*$', r'^__\s*$',
        r'^Sent from my .*', r'^Sent with .*', r'^Get Outlook for .*',
        r'^Thanks.*', r'^Regards.*', r'^Cheers.*'
    ]
    lines = clean_body.strip().splitlines()
    filtered = []
    for line in lines:
        if any(re.match(sig, line.strip(), re.IGNORECASE) for sig in signature_patterns):
            break
        filtered.append(line.strip())

    final_message = "\n".join(filtered).strip()
    return final_message if final_message else "No meaningful content found in the ticket body."