"""Writer Agent - Applies editorial feedback to improve articles."""

import json
import logging
from datetime import datetime
from strands import Agent
from strands.models import BedrockModel
from strands.tools import tool
from config import AWS_REGION
from tools import search_internet, search_google_news
import wikipedia
from botocore.config import Config

logger = logging.getLogger(__name__)

WRITER_SYSTEM_PROMPT = """You are an experienced magazine journalist who takes editorial feedback seriously.

CURRENT DATE: {current_date}

PERSONAL OPENING (USE AS INSPIRATION):
{personal_story}

Your role is to revise articles based on editor feedback, implementing ALL suggested improvements while maintaining your voice.

CRITICAL INSTRUCTIONS FOR PERSONAL OPENING:
- The article should START with a personal opening (1-2 paragraphs) based on the story above
- ADAPT the personal story to fit the article's theme and flow naturally
- FIX any factual errors in the personal story (e.g., release dates, product names)
- Make it conversational and authentic, but ensure all facts are accurate
- Transition smoothly from personal opening to the main topic

REVISION PRINCIPLES:
- Address every critical issue completely
- Implement specific line edits exactly as suggested
- Apply broader improvements throughout the article
- Fix all factual errors, especially in the personal opening
- Keep the journalist voice authentic and engaging
- Ensure all changes improve clarity and impact

SOURCING REQUIREMENTS:
- When fact-checker identifies missing sources, use available tools to find proper references
- Use search_for_source_tool to find credible sources for unsourced claims
- Use search_wikipedia_for_facts_tool to find Wikipedia references for factual claims
- DO NOT use inline citations like [Source: URL] in the article body
- Instead, use numbered references [1], [2], etc. in the text
- Place all reference URLs in a "Sources" section at the bottom of the article
- Format: [1] URL - Brief description of source

Output the complete revised article, not just the changes."""


@tool
def search_for_source_tool(claim: str, topic: str) -> str:
    """Search for credible sources to support a specific claim.
    
    Args:
        claim: The specific claim that needs a source
        topic: The article topic for context
        
    Returns:
        JSON with relevant sources and URLs
    """
    # Search both news and web
    query = f"{claim} {topic}"
    
    results = []
    
    # Try Google News first
    news_results = search_google_news(query, max_results=3)
    for item in news_results[:2]:
        results.append({
            'source': item.get('source', 'Unknown'),
            'title': item.get('title', ''),
            'url': item.get('url', ''),
            'snippet': item.get('content', '')[:200]
        })
    
    # Try web search
    web_results = search_internet(query, max_results=3)
    for item in web_results[:2]:
        results.append({
            'source': 'Web',
            'title': item.get('title', ''),
            'url': item.get('url', ''),
            'snippet': item.get('content', '')[:200]
        })
    
    return json.dumps(results, indent=2)


@tool
def search_wikipedia_for_facts_tool(topic: str) -> str:
    """Search Wikipedia for factual information and references.
    
    Args:
        topic: The topic to search for on Wikipedia
        
    Returns:
        JSON with Wikipedia summary and URL
    """
    try:
        page = wikipedia.page(topic, auto_suggest=True)
        summary = wikipedia.summary(topic, sentences=5, auto_suggest=True)
        
        return json.dumps({
            'title': page.title,
            'summary': summary,
            'url': page.url
        }, indent=2)
    except Exception as e:
        return json.dumps({'error': str(e), 'topic': topic})


class WriterAgent(Agent):
    """Writer that revises articles based on editorial feedback."""
    
    def __init__(self, model_id: str = "global.anthropic.claude-opus-4-5-20251101-v1:0"):
        boto_config = Config(
            read_timeout=7200,
            connect_timeout=600,
            retries={'max_attempts': 10, 'mode': 'adaptive'}
        )
        model = BedrockModel(
            model_id=model_id,
            region_name=AWS_REGION,
            temperature=0.4,  # Slightly higher for creative revision
            max_tokens=60000,
            config=boto_config
        )
        
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        
        # Load personal story if available
        personal_story = "You are an experienced technology journalist."
        try:
            from pathlib import Path
            story_path = Path(__file__).parent / "personal_story.txt"
            if story_path.exists():
                with open(story_path, 'r') as f:
                    content = f.read().strip()
                    if content and not content.startswith("Add your personal story"):
                        personal_story = content
        except Exception:
            pass
        
        super().__init__(
            name="WriterAgent",
            model=model,
            system_prompt=WRITER_SYSTEM_PROMPT.format(
                current_date=current_date,
                personal_story=personal_story
            ),
            tools=[search_for_source_tool, search_wikipedia_for_facts_tool]
        )
    
    def revise_article(self, article: str, feedback: dict, topic: str) -> str:
        """Revise article based on editorial feedback."""
        logger.info("\n" + "=" * 70)
        logger.info("✍️  WRITER REVISION")
        logger.info("=" * 70)
        
        # Extract key feedback elements
        editor = feedback.get('editor', {})
        fact_checker = feedback.get('fact_checker', {})
        authenticity = feedback.get('authenticity', {})
        user = feedback.get('user', {})
        
        critical_issues = editor.get('critical_issues', [])
        improvements = editor.get('improvements', [])
        line_edits = editor.get('line_edits', [])
        fact_issues = [i for i in fact_checker.get('issues', []) if i.get('severity') in ['CRITICAL', 'HIGH']]
        ai_patterns = authenticity.get('ai_patterns_found', [])
        user_feedback_text = user.get('feedback', '')
        
        # Build focused feedback summary
        feedback_summary = f"""EDITOR ASSESSMENT:
Grade: {editor.get('grade')}
Overall: {editor.get('overall_assessment', '')}

CRITICAL ISSUES TO FIX:
{json.dumps(critical_issues, indent=2)}

IMPROVEMENTS REQUIRED:
{json.dumps(improvements, indent=2)}

LINE EDITS TO APPLY:
{json.dumps(line_edits, indent=2)}

FACT-CHECK ISSUES (Score: {fact_checker.get('verification_score', 0)}/100):
{json.dumps(fact_issues[:10], indent=2)}

AUTHENTICITY CHECK (Score: {authenticity.get('authenticity_score', 0)}/100):
AI Patterns Found: {len(ai_patterns)}
{json.dumps(ai_patterns[:5], indent=2)}

Recommendations:
{json.dumps(authenticity.get('recommendations', []), indent=2)}"""

        if user_feedback_text:
            feedback_summary += f"""

USER FEEDBACK (HIGHEST PRIORITY):
{user_feedback_text}

NOTE: User feedback takes precedence over other feedback. Address user concerns first."""
        
        logger.info(f"   → Applying editorial feedback...")
        logger.info(f"   → Critical issues to fix: {len(critical_issues)}")
        logger.info(f"   → Improvements to apply: {len(improvements)}")
        logger.info(f"   → Line edits to apply: {len(line_edits)}")
        logger.info(f"   → Fact-check issues: {len(fact_issues)}")
        logger.info(f"   → AI patterns to fix: {len(ai_patterns)}")
        if user_feedback_text:
            logger.info(f"   → User feedback: Yes")
        
        prompt = f"""You MUST revise this article on "{topic}" by addressing EVERY issue listed below.

ORIGINAL ARTICLE:
{article}

FEEDBACK TO ADDRESS:
{feedback_summary}

MANDATORY REQUIREMENTS:
1. Fix EVERY critical issue listed - no exceptions
2. Apply EVERY line edit exactly as specified
3. Implement ALL improvement suggestions
4. Remove or fix ALL AI patterns identified (repetitive constructions, hedging language, etc.)
5. For ANY unsourced claims or missing citations:
   - Use search_for_source_tool to find credible sources
   - Use search_wikipedia_for_facts_tool for factual background
   - Add proper numbered citations [1], [2], etc.
6. Ensure the article sounds authentically human-written with varied rhythm and clear voice
7. Remove or properly source ALL unverified statistics
8. Maintain the article's voice and core insights
{"9. ADDRESS USER FEEDBACK FIRST - this is the highest priority" if user_feedback_text else ""}

DO NOT write meta-commentary. DO NOT explain what you're doing. 
Write ONLY the complete revised article with all fixes applied.

REVISED ARTICLE:"""
        
        # Retry logic for Bedrock errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self(prompt)
                break
            except Exception as e:
                if attempt < max_retries - 1 and "serviceUnavailableException" in str(e):
                    import time
                    delay = 10 * (2 ** attempt)
                    logger.warning(f"   ⚠️  Writer error (attempt {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"   ⏳ Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
        
        revised_article = response.result if hasattr(response, 'result') else str(response)
        
        logger.info(f"   ✓ Revision complete ({len(revised_article)} characters)")
        logger.info("=" * 70)
        
        return revised_article
