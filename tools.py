import json
import boto3
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import os
import logging

try:
    from config import *
except ImportError:
    from config import *

# Setup logging
logger = logging.getLogger(__name__)


def search_google_news(query: str, country: str = 'US', language: str = 'en', max_results: int = 10) -> List[Dict]:
    """Search Google News using GoogleNews package."""
    logger.info(f"📰 GOOGLE NEWS SEARCH: '{query}' (country={country}, lang={language})")
    
    try:
        from GoogleNews import GoogleNews
        
        googlenews = GoogleNews(lang=language, region=country, period='7d', encode='utf-8')
        googlenews.search(query)
        
        results = []
        for item in googlenews.results()[:max_results]:
            results.append({
                'title': item.get('title', ''),
                'content': item.get('desc', ''),
                'source': item.get('link', ''),
                'source_name': item.get('media', 'Unknown'),
                'date': item.get('date', ''),
                'type': 'google_news'
            })
        
        googlenews.clear()
        
        logger.info(f"   → Found {len(results)} Google News results")
        for r in results:
            logger.info(f"   ✓ {r['source_name']}: {r['title'][:60]}...")
        
        return results
    
    except ImportError:
        logger.error("   ✗ GoogleNews package not installed. Run: pip install GoogleNews")
        return []
    except Exception as e:
        logger.error(f"   ✗ Google News search error: {e}")
        return []


def search_internet_duckduckgo(query: str, max_results: int = 10) -> List[Dict]:
    """Search the internet using DuckDuckGo (free alternative)."""
    logger.info(f"🦆 DUCKDUCKGO SEARCH: '{query}' (max_results={max_results})")
    
    try:
        from ddgs import DDGS
        
        results = []
        with DDGS() as ddgs:
            search_results = list(ddgs.text(query, max_results=max_results))
            
            for item in search_results:
                logger.info(f"   ✓ {item.get('title', '')[:60]}...")
                results.append({
                    'title': item.get('title', ''),
                    'content': item.get('body', ''),
                    'source': item.get('href', ''),
                    'type': 'web_search'
                })
        
        logger.info(f"   → Found {len(results)} results")
        return results
    
    except ImportError:
        logger.error("   ✗ ddgs not installed. Run: pip install ddgs")
        return []
    except Exception as e:
        logger.error(f"   ✗ DuckDuckGo search error: {e}")
        return []


def search_internet(query: str, max_results: int = 10) -> List[Dict]:
    """Search the internet using Tavily API with DuckDuckGo fallback."""
    logger.info(f"🌐 INTERNET SEARCH: '{query}' (max_results={max_results})")
    
    api_key = os.getenv('TAVILY_API_KEY', TAVILY_API_KEY)
    
    # Try Tavily first if API key is available
    if api_key:
        try:
            logger.debug("   → Trying Tavily API...")
            response = requests.post(
                'https://api.tavily.com/search',
                json={
                    'api_key': api_key,
                    'query': query,
                    'max_results': max_results,
                    'include_answer': True,
                    'include_raw_content': False
                },
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            # Add the AI-generated answer if available
            if data.get('answer'):
                logger.info(f"   ✓ Got AI summary ({len(data['answer'])} chars)")
                results.append({
                    'title': 'AI Summary',
                    'content': data['answer'],
                    'source': 'tavily_ai_summary',
                    'type': 'summary'
                })
            
            # Add search results
            for item in data.get('results', []):
                logger.info(f"   ✓ {item.get('title')[:60]}...")
                results.append({
                    'title': item.get('title'),
                    'content': item.get('content'),
                    'source': item.get('url'),
                    'type': 'web_search'
                })
            
            logger.info(f"   → Found {len(results)} total results")
            return results
        
        except Exception as e:
            logger.warning(f"   ⚠️  Tavily failed: {e}")
            logger.info(f"   → Falling back to DuckDuckGo...")
    else:
        logger.info("   → No Tavily API key, using DuckDuckGo...")
    
    # Fallback to DuckDuckGo
    return search_internet_duckduckgo(query, max_results)


def query_knowledge_base(query: str, max_results: int = 30) -> List[Dict]:
    """Query Bedrock Knowledge Base for relevant information."""
    logger.info(f"📚 KNOWLEDGE BASE: '{query}' (max_results={max_results})")
    
    if not KNOWLEDGE_BASE_ID:
        logger.warning("   ⚠️  KNOWLEDGE_BASE_ID not set, skipping KB query")
        return []
    
    logger.debug(f"   → Querying KB: {KNOWLEDGE_BASE_ID}")
    client = boto3.client('bedrock-agent-runtime', region_name=AWS_REGION)
    
    try:
        response = client.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={'text': query},
            retrievalConfiguration={
                'vectorSearchConfiguration': {
                    'numberOfResults': max_results
                }
            }
        )
        
        results = [{
            'content': result['content']['text'],
            'source': result.get('location', {}).get('s3Location', {}).get('uri', 'unknown'),
            'score': result.get('score', 0)
        } for result in response.get('retrievalResults', [])]
        
        logger.info(f"   → Found {len(results)} KB results")
        for r in results:
            logger.info(f"   ✓ Score: {r['score']:.2f} | {r['source']}")
        
        return results
    except Exception as e:
        logger.error(f"   ✗ KB query error: {e}")
        return []


def search_rss_feeds(query: str) -> List[Dict]:
    """Search cached RSS feed content."""
    logger.info(f"📰 RSS SEARCH: '{query}'")
    
    try:
        logger.debug(f"   → Reading: {RSS_CACHE_FILE}")
        with open(RSS_CACHE_FILE, 'r') as f:
            rss_data = json.load(f)
        
        logger.debug(f"   → Loaded {len(rss_data)} articles")
        
        results = []
        query_lower = query.lower()
        
        for item in rss_data:
            title = item.get('title', '')
            summary = item.get('summary', '')
            content = item.get('content', '')
            
            if query_lower in title.lower() or \
               query_lower in summary.lower() or \
               query_lower in content.lower():
                results.append({
                    'title': title,
                    'content': summary or content[:500],
                    'source': item.get('url') or item.get('link'),
                    'date': item.get('published_date') or item.get('published')
                })
        
        logger.info(f"   → Found {len(results)} matching articles (returning top 5)")
        for r in results[:5]:
            logger.info(f"   ✓ {r['title'][:60]}...")
        
        return results[:5]
    except FileNotFoundError:
        logger.error(f"   ✗ RSS cache not found: {RSS_CACHE_FILE}")
        return []


def crawl_web(url: str) -> Dict:
    """Fetch and extract content from a web page with improved parsing."""
    logger.info(f"🕷️  WEB CRAWL: {url}")
    
    try:
        logger.debug("   → Fetching page...")
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        logger.debug("   → Parsing HTML...")
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
            element.decompose()
        
        # Try to find main content area (better extraction)
        main_content = (
            soup.find('article') or 
            soup.find('main') or 
            soup.find('div', class_=['content', 'article', 'post', 'entry', 'post-content']) or
            soup.find('body')
        )
        
        if main_content:
            text = main_content.get_text(separator=' ', strip=True)
        else:
            text = soup.get_text(separator=' ', strip=True)
        
        # Clean up whitespace
        text = ' '.join(text.split())
        
        title = soup.title.string if soup.title else ''
        
        logger.info(f"   ✓ Extracted {len(text)} chars: {title[:60]}...")
        
        return {
            'url': url,
            'title': title,
            'content': text[:8000],  # Increased limit for better context
            'source': 'web'
        }
    except Exception as e:
        logger.error(f"   ✗ Crawl error: {e}")
        return {'url': url, 'error': str(e)}


def search_web(query: str, num_results: int = 3) -> List[str]:
    """Search web and return URLs using Tavily."""
    results = search_internet(query, num_results)
    return [r['source'] for r in results if r.get('type') == 'web_search']
