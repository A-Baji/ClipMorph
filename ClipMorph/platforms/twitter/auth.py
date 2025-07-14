import os
import tweepy
import logging

logger = logging.getLogger(__name__)


def authenticate_twitter():
    logger.info("[Twitter/X] Authenticating to Twitter API...")
    API_KEY = os.getenv("TWITTER_API_KEY")
    API_KEY_SECRET = os.getenv("TWITTER_API_KEY_SECRET")
    ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
    ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
    BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

    auth = tweepy.OAuth1UserHandler(API_KEY, API_KEY_SECRET, ACCESS_TOKEN,
                                    ACCESS_TOKEN_SECRET)
    api = tweepy.API(auth)
    client = tweepy.Client(bearer_token=BEARER_TOKEN,
                           consumer_key=API_KEY,
                           consumer_secret=API_KEY_SECRET,
                           access_token=ACCESS_TOKEN,
                           access_token_secret=ACCESS_TOKEN_SECRET)
    logger.info("[Twitter/X] Authentication successful!")
    return api, client
