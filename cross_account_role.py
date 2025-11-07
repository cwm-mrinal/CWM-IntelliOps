import boto3
from aws_accounts import sts


def assume_role(account_id: str):
    sts_response = sts(account_id)
    if sts_response["status"] != 200:
        error_msg = f"Failed to create session for account {account_id}: {sts_response['message']}"
        raise Exception(error_msg)  # Changed from return tuple to raise exception
    
    # Always return just the session on success
    return boto3.Session(
        aws_access_key_id=sts_response["data"]["AccessKeyId"],
        aws_secret_access_key=sts_response["data"]["SecretAccessKey"],
        aws_session_token=sts_response["data"]["SessionToken"],
    )