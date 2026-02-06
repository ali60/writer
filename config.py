import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bedrock Knowledge Base
KNOWLEDGE_BASE_ID = os.getenv('KNOWLEDGE_BASE_ID')
AWS_REGION = os.getenv('AWS_REGION')

# Tavily API for internet search
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

# SerpAPI for Google News search
SERP_API_KEY = os.getenv('SERP_API_KEY')

# RSS Sources (use output folder from RSS crawler)
PROJECT_ROOT = Path(__file__).parent
RSS_CACHE_FILE = str(PROJECT_ROOT / 'output' / 'articles.json')

# Output directory for generated articles
OUTPUT_DIR = PROJECT_ROOT / 'output' / 'generated'

# Web Crawling
MAX_CRAWL_DEPTH = 2
MAX_PAGES_PER_TOPIC = 5
USER_AGENT = 'WriterAI-Editorial-System/1.0'

# Research Parameters
MAX_RESEARCH_ITERATIONS = 6
CONFIDENCE_THRESHOLD = 0.8
