"""Fact-Checker Agent - Verifies claims, sources, and statistics in articles."""

import json
import logging
import re
import requests
from typing import List, Dict
from datetime import datetime
from strands import Agent
from strands.models import BedrockModel
from strands.tools import tool
from config import AWS_REGION
from botocore.config import Config

logger = logging.getLogger(__name__)

# URL verification cache
_url_cache = {}

FACT_CHECKER_SYSTEM_PROMPT = """You are a meticulous fact-checker for a prestigious magazine.

CURRENT DATE: {current_date}

Your role is to verify factual claims, statistics, and source citations in articles.

VERIFICATION STANDARDS:
1. **Claims**: Major assertions should be verifiable or clearly marked as opinion/analysis
2. **Statistics**: Key numbers should have sources (inline or in context)
3. **Sources**: URLs should be valid and content should support claims
4. **Quotes**: Verify attribution is reasonable
5. **Dates**: Check major dates are accurate
6. ⚠️ **RECENCY**: For statistics and data, verify publication dates. Flag if article uses outdated data without noting it's historical context:
   - Non-book references (articles, news, reports): MUST be within 3 months of current date
   - Book references (from Bedrock Knowledge Base): Can be older as they provide historical context
   - Flag as CRITICAL if recent statistics cite sources older than 3 months

TOOLS AVAILABLE:
- **verify_url**: Crawls a URL to check accessibility and extract content. Use this to verify all cited sources.
- **find_alternative_source**: When a URL is blocked (403, 401, paywall), use this to find alternative accessible sources for the same claim.

HANDLING BLOCKED SOURCES:
- If a source returns 403/401/paywall error, use find_alternative_source to find accessible alternatives
- Don't immediately flag as HIGH severity if the claim is verifiable through alternative sources
- Only flag as HIGH if NO accessible source can be found for an important claim

FLAG LEVELS:
- **CRITICAL**: Factual error that MUST be corrected (provably wrong number, false claim, completely broken source, outdated statistics presented as current)
- **HIGH**: Important claim lacking any accessible source (after trying alternatives), or recent statistics without dates
- **MEDIUM**: Minor sourcing issue or ambiguous statement
- **LOW**: Style or precision improvement

PUBLICATION CRITERIA:
- Ready to publish if: verification_score >= 80 AND critical_issues == 0
- Score 80-89: Acceptable quality
- Score 90+: Excellent

Be thorough but reasonable. Magazine articles don't need academic-level sourcing for every sentence."""


@tool
def verify_url(url: str) -> str:
    """Check if a URL is accessible, crawl it, and extract key content.
    
    Args:
        url: URL to verify
        
    Returns:
        JSON with status, title, content snippet, and accessibility info
    """
    # Check cache first
    if url in _url_cache:
        logger.info(f"   ✓ Using cached result for {url}")
        return json.dumps(_url_cache[url])
    
    try:
        # Try GET request to get full content
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=15, allow_redirects=True, headers=headers)
        
        accessible = response.status_code == 200
        result = {
            "url": url,
            "accessible": accessible,
            "status_code": response.status_code,
            "final_url": response.url
        }
        
        if accessible:
            # Parse HTML to extract title and content
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title
            title = soup.find('title')
            if title:
                result["title"] = title.get_text().strip()
            
            # Extract main content (first 500 chars)
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            result["content_snippet"] = text[:500] if text else ""
            result["content_length"] = len(text)
        
        # Cache the result
        _url_cache[url] = result
        
        return json.dumps(result)
    except requests.exceptions.Timeout:
        return json.dumps({
            "url": url,
            "accessible": False,
            "error": "timeout",
            "message": "Request timed out after 15 seconds"
        })
    except Exception as e:
        return json.dumps({
            "url": url,
            "accessible": False,
            "error": str(type(e).__name__),
            "message": str(e)
        })


@tool
def find_alternative_source(claim: str, blocked_url: str) -> str:
    """Find alternative accessible sources for a claim when the original URL is blocked.
    
    Args:
        claim: The claim or statistic that needs verification
        blocked_url: The original blocked URL
        
    Returns:
        JSON with alternative sources found via web search
    """
    from tools import search_internet
    
    # Extract domain from blocked URL for context
    domain = blocked_url.split('/')[2] if '://' in blocked_url else ''
    
    # Search for the claim
    query = f"{claim} {domain}"
    results = search_internet(query, max_results=5)
    
    alternatives = []
    for item in results:
        url = item.get('source', '')
        # Skip AI summaries and the blocked URL
        if url and url != 'tavily_ai_summary' and url != blocked_url:
            alternatives.append({
                'title': item.get('title', ''),
                'url': url,
                'snippet': item.get('content', '')[:200]
            })
    
    return json.dumps({
        'original_url': blocked_url,
        'claim': claim,
        'alternatives': alternatives[:3]
    }, indent=2)


class FactCheckerAgent(Agent):
    """Fact-checker that verifies claims and sources."""
    
    def __init__(self, model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"):
        boto_config = Config(
            read_timeout=7200,
            connect_timeout=600,
            retries={'max_attempts': 10, 'mode': 'adaptive'}
        )
        model = BedrockModel(
            model_id=model_id,
            region_name=AWS_REGION,
            temperature=0.1,  # Low temperature for accuracy
            max_tokens=60000,
            config=boto_config
        )
        
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        
        super().__init__(
            name="FactCheckerAgent",
            model=model,
            system_prompt=FACT_CHECKER_SYSTEM_PROMPT.format(current_date=current_date),
            tools=[verify_url, find_alternative_source]
        )
    
    def check_article(self, article: str, topic: str) -> dict:
        """Fact-check an article and return findings."""
        logger.info("\n" + "=" * 70)
        logger.info("🔍 FACT-CHECKING")
        logger.info("=" * 70)
        
        # Extract all URLs from article
        urls = re.findall(r'https?://[^\s\)]+', article)
        logger.info(f"   → Found {len(urls)} URLs to verify")
        
        # Extract statistics (numbers with context)
        stats = re.findall(r'\$?[\d,]+\.?\d*\s*(?:trillion|billion|million|thousand|%|percent)', article, re.IGNORECASE)
        logger.info(f"   → Found {len(stats)} statistics to verify")
        
        prompt = f"""Fact-check this article on "{topic}".

ARTICLE:
{article}

VERIFICATION TASKS:
1. Check major factual claims are supported or clearly marked as analysis
2. Verify key statistics have sources (inline or contextual)
3. Use verify_url tool to check source URLs are accessible
4. Flag provably false claims or completely missing sources for major assertions
5. Be reasonable - magazine articles don't need citations for every sentence

SCORING GUIDANCE:
- 90-100: Excellent sourcing, all major claims verified
- 80-89: Good sourcing, minor issues only
- 60-79: Acceptable, some sourcing gaps but no critical errors
- Below 60: Significant sourcing problems or factual errors

PUBLICATION DECISION:
- ready_to_publish: true if score >= 60 AND no CRITICAL issues
- ready_to_publish: false if score < 60 OR any CRITICAL issues exist

Return findings in this JSON format:
{{
  "overall_assessment": "summary of fact-checking results",
  "verification_score": 0-100,
  "issues": [
    {{
      "severity": "CRITICAL/HIGH/MEDIUM/LOW",
      "type": "claim/statistic/source/quote",
      "location": "quote from article",
      "issue": "what's wrong",
      "correction": "how to fix it",
      "verified": true/false
    }}
  ],
  "verified_sources": [
    {{
      "url": "source URL",
      "claim": "what it supports",
      "accessible": true/false
    }}
  ],
  "unverified_claims": ["major unsourced claims only"],
  "statistics_check": [
    {{
      "statistic": "the number",
      "context": "what it's about",
      "sourced": true/false
    }}
  ],
  "ready_to_publish": true/false,
  "required_corrections": ["only critical corrections"]
}}"""
        
        logger.info("   → Analyzing claims and sources...")
        
        # Retry logic for Bedrock errors during fact-checking
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self(prompt)
                break
            except Exception as e:
                error_str = str(e)
                is_retryable = (
                    "serviceUnavailableException" in error_str or
                    "SSLError" in error_str or
                    "DECRYPTION_FAILED" in error_str
                )
                if attempt < max_retries - 1 and is_retryable:
                    import time
                    delay = 10 * (2 ** attempt)  # 10s, 20s, 40s
                    logger.warning(f"   ⚠️  Fact-check error (attempt {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"   ⏳ Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
        
        try:
            content = response.result if hasattr(response, 'result') else str(response)
            
            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            findings = json.loads(content)
            
            # Log summary
            critical = len([i for i in findings.get('issues', []) if i.get('severity') == 'CRITICAL'])
            high = len([i for i in findings.get('issues', []) if i.get('severity') == 'HIGH'])
            
            logger.info(f"   ✓ Fact-check complete")
            logger.info(f"   → Verification score: {findings.get('verification_score', 0)}/100")
            logger.info(f"   → Critical issues: {critical}")
            logger.info(f"   → High priority issues: {high}")
            logger.info(f"   → Ready to publish: {findings.get('ready_to_publish', False)}")
            logger.info("=" * 70)
            
            return findings
            
        except Exception as e:
            logger.error(f"   ✗ Failed to parse fact-check results: {e}")
            return {
                "overall_assessment": "Fact-check parsing failed",
                "verification_score": 0,
                "ready_to_publish": False,
                "error": str(e),
                "raw_response": content
            }
