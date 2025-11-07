import json
import logging
import boto3
import re
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
from first_response import send_email_reply

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def extract_s3_objects_from_ssm_output(ssm_output):
    """
    Extract S3 objects JSON from SSM command output.
    """
    try:
        # Look for S3_OBJECTS_JSON_START and S3_OBJECTS_JSON_END markers
        start_marker = "S3_OBJECTS_JSON_START"
        end_marker = "S3_OBJECTS_JSON_END"
        
        if not ssm_output:
            logger.warning("No SSM output provided")
            return []
        
        start_index = ssm_output.find(start_marker)
        end_index = ssm_output.find(end_marker)
        
        if start_index != -1 and end_index != -1:
            start_index += len(start_marker)
            json_str = ssm_output[start_index:end_index].strip()
            s3_objects = json.loads(json_str)
            logger.info(f"Successfully extracted {len(s3_objects)} S3 objects from SSM output")
            return s3_objects
        else:
            logger.info("S3 objects JSON markers not found in SSM output - S3 upload may not be configured")
            return []
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing S3 objects JSON from SSM output: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Error extracting S3 objects from SSM output: {str(e)}")
        return []

def generate_presigned_urls(s3_objects, expiration_hours=24):
    """
    Generate presigned URLs for S3 objects.
    """
    if not s3_objects:
        logger.info("No S3 objects to generate presigned URLs for")
        return []
    
    s3_client = boto3.client('s3')
    presigned_urls = []
    
    for obj in s3_objects:
        try:
            bucket_name = obj.get('S3Bucket')
            s3_key = obj.get('S3Key')
            username = obj.get('Username')
            
            if not bucket_name or not s3_key or not username:
                logger.warning(f"Missing required fields in S3 object: {obj}")
                continue
            
            # Generate presigned URL
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': s3_key},
                ExpiresIn=expiration_hours * 3600  # Convert hours to seconds
            )
            
            presigned_urls.append({
                'Username': username,
                'S3Key': s3_key,
                'S3Bucket': bucket_name,
                'PresignedURL': presigned_url,
                'ExpiresIn': f"{expiration_hours} hours"
            })
            
            logger.info(f"Generated presigned URL for {username}: {s3_key}")
            
        except ClientError as e:
            logger.error(f"Error generating presigned URL for {obj.get('Username', 'unknown')}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {str(e)}")
    
    logger.info(f"Successfully generated {len(presigned_urls)} presigned URLs")
    return presigned_urls

def build_credentials_html(response_data, presigned_urls=None):
    """
    Builds an HTML table with user credentials and download links from the response data.
    """
    user_creds = response_data.get("UserCredentials", [])
    if not user_creds:
        logger.error("No UserCredentials found in response data")
        return "<p><strong>No TSPlus user credentials found in the response.</strong></p>"

    # Create a lookup dictionary for presigned URLs
    url_lookup = {}
    if presigned_urls:
        url_lookup = {url['Username']: url for url in presigned_urls}
        logger.info(f"Created URL lookup for {len(url_lookup)} users")

    # Determine if we have download links
    has_download_links = len(url_lookup) > 0

    html_content = [
        "<h2>TSPlus User Credentials Created Successfully:</h2>",
        "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse; width: 100%;'>",
        "<tr style='background-color:#f2f2f2;'>"
        "<th>Username</th><th>Password</th><th>Groups</th><th>Server IP</th>"
    ]
    
    # Add download column header if we have download links
    if has_download_links:
        html_content.append("<th>Download .connect File</th>")
    
    html_content.append("</tr>")

    for cred in user_creds:
        username = cred.get('Username', '')
        password = cred.get('Password', '')
        groups = cred.get('Groups', '')
        server_ip = cred.get('ServerIP', '')
        
        html_content.append(
            f"<tr>"
            f"<td>{username}</td>"
            f"<td>{password}</td>"
            f"<td>{groups}</td>"
            f"<td>{server_ip}</td>"
        )
        
        # Add download link if available
        if has_download_links:
            if username in url_lookup:
                presigned_url = url_lookup[username]['PresignedURL']
                expires_in = url_lookup[username]['ExpiresIn']
                download_link = (
                    f"<a href='{presigned_url}' "
                    f"style='color: #007bff; text-decoration: none; font-weight: bold;' "
                    f"target='_blank' download='{username}.connect'>"
                    f"📥 Download</a><br/>"
                    f"<small style='color: #666; font-size: 11px;'>"
                    f"Expires in {expires_in}</small>"
                )
            else:
                download_link = "<span style='color: #999;'>Not Available</span>"
            
            html_content.append(f"<td style='text-align: center;'>{download_link}</td>")
        
        html_content.append("</tr>")
    
    html_content.append("</table>")
    
    # Add download instructions if we have download links
    if has_download_links:
        html_content.extend([
            "<br/><div style='background-color: #f8f9fa; padding: 15px; border-left: 4px solid #007bff; margin: 20px 0;'>",
            "<h3 style='color: #007bff; margin-top: 0;'>📁 Download Instructions:</h3>",
            "<ol style='margin: 10px 0; padding-left: 20px;'>",
            "<li>Click the <strong>📥 Download</strong> link for each user to download their .connect file</li>",
            "<li>Save the .connect file to your local machine</li>", 
            "<li>Double-click the .connect file to launch TSPlus connection</li>",
            "<li><strong>Important:</strong> Download links are valid for 24 hours only</li>",
            "</ol>",
            "<p style='margin: 10px 0; font-size: 12px; color: #666;'>",
            "💡 <strong>Tip:</strong> Right-click the download link and select 'Save Link As' to specify the download location.",
            "</p>",
            "</div>"
        ])
    else:
        # Add note about manual file access if no S3 links
        html_content.extend([
            "<br/><div style='background-color: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0;'>",
            "<h3 style='color: #856404; margin-top: 0;'>📝 Connection Files:</h3>",
            "<p style='margin: 10px 0; color: #856404;'>",
            "TSPlus .connect files have been created on the server. Please contact your system administrator to access them.",
            "</p>",
            "</div>"
        ])
    
    return "".join(html_content)

def send_tsplus_credentials(ticket_id, from_emails, to_emails, cc_emails, response_data, ssm_output=None):
    """
    Formats TSPlus credentials and sends them via email reply on Zoho Desk ticket.
    Now includes S3 presigned URLs for .connect files if available.
    """
    try:
        logger.info("Preparing TSPlus credentials email for ticket ID: %s", ticket_id)

        # Extract S3 objects from SSM output if provided
        s3_objects = []
        presigned_urls = []
        
        if ssm_output:
            logger.info("Processing SSM output for S3 objects")
            s3_objects = extract_s3_objects_from_ssm_output(ssm_output)
            
            if s3_objects:
                logger.info(f"Found {len(s3_objects)} S3 objects, generating presigned URLs")
                presigned_urls = generate_presigned_urls(s3_objects, expiration_hours=24)
            else:
                logger.info("No S3 objects found in SSM output")
        else:
            logger.info("No SSM output provided, skipping S3 processing")

        # Build HTML content with or without download links
        credentials_html = build_credentials_html(response_data, presigned_urls)
        server_name = response_data.get("ServerName", "Unknown Server")
        
        # Check S3 configuration status
        s3_config = response_data.get("S3Configuration", {})
        s3_enabled = s3_config.get("Enabled", False)

        # Build email body
        email_body = (
            "<body style='font-family: Arial, sans-serif; font-size: 14px; color: #333;'>"
            "<p>Dear Sir/Ma'am,</p>"
            "<p>Greetings from <strong>Workmates Support</strong>! We hope this email finds you well.</p>"

            f"<p>✅ The TSPlus users have been created successfully on server <strong>{server_name}</strong>.</p>"
            
            f"{credentials_html}"
        )
        
        # Add S3 information if files were uploaded
        if presigned_urls:
            email_body += (
                "<br/><div style='background-color: #d4edda; padding: 15px; border-left: 4px solid #28a745; margin: 20px 0;'>"
                "<h3 style='color: #155724; margin-top: 0;'>🔒 Security Information</h3>"
                "<p style='margin: 10px 0; color: #155724;'>"
                f"Your TSPlus .connect files have been securely uploaded to our cloud storage. "
                f"Download links are valid for <strong>24 hours</strong> and will expire automatically for security."
                "</p>"
                "</div>"
            )
        elif s3_enabled:
            # S3 was configured but no files were uploaded
            email_body += (
                "<br/><div style='background-color: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0;'>"
                "<h3 style='color: #856404; margin-top: 0;'>⚠️ File Upload Status</h3>"
                "<p style='margin: 10px 0; color: #856404;'>"
                "Cloud storage was configured but .connect files may not have been uploaded successfully. "
                "Please check the server logs or contact support if you need assistance accessing the files."
                "</p>"
                "</div>"
            )
        
        email_body += (
            "<p>Thank you,<br/><br/>"
            "<strong>Best Regards</strong><br/>"
            "<img src='https://zoho-uptime-automation-assets-bucket.s3.ap-south-1.amazonaws.com/Workmates-Logo.png' "
            "alt='Workmates Logo' style='margin-top:10px; width:150px;'/>"
            "<br/>Workmates Support<br/></p>"
            "</body>"
        )

        logger.info("Sending TSPlus credentials email with reply text length: %s", len(email_body))

        response = send_email_reply(
            ticket_id=ticket_id,
            from_emails=from_emails,
            to_emails=to_emails,
            cc_emails=cc_emails,
            reply_text=email_body
        )

        logger.info("send_email_reply response: %s", response)
        
        # Add S3 information to response for debugging
        if hasattr(response, 'get') and isinstance(response, dict):
            response['S3Info'] = {
                'ObjectsFound': len(s3_objects),
                'PresignedURLsGenerated': len(presigned_urls),
                'S3Enabled': s3_enabled
            }
        
        return response

    except Exception as e:
        logger.error("Error sending TSPlus credentials email: %s", str(e), exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Error sending credentials email: {str(e)}"})
        }

# Backward compatibility - keep original function signature
def send_tsplus_credentials_legacy(ticket_id, from_emails, to_emails, cc_emails, response_data):
    """
    Legacy function signature for backward compatibility.
    """
    return send_tsplus_credentials(ticket_id, from_emails, to_emails, cc_emails, response_data)