import boto3
import logging

comprehend = boto3.client("comprehend")
translate = boto3.client("translate")
logger = logging.getLogger()

def detect_and_translate(text):
    lang_response = comprehend.detect_dominant_language(Text=text)
    language_code = lang_response["Languages"][0]["LanguageCode"]

    if language_code != "en":
        translation = translate.translate_text(
            Text=text,
            SourceLanguageCode=language_code,
            TargetLanguageCode="en"
        )
        return language_code, translation["TranslatedText"]

    return language_code, text