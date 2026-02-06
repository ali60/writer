import json
import logging
from typing import Dict, List
from pathlib import Path
from datetime import datetime
from strands import Agent
from strands.models import BedrockModel
from strands.tools import tool
from tools import query_knowledge_base, crawl_web, search_internet, search_web, search_google_news
import wikipedia
from prompts import (
    RESEARCH_SYSTEM_PROMPT, 
    TOPIC_ANALYSIS_PROMPT, 
    SYNTHESIS_PROMPT,
    ARTICLE_WRITER_PROMPT
)
from config import MAX_RESEARCH_ITERATIONS, CONFIDENCE_THRESHOLD, AWS_REGION
from botocore.config import Config

# Setup logging
logger = logging.getLogger(__name__)


@tool
def search_internet_tool(query: str) -> str:
    """Search the internet for information on a topic.
    
    Args:
        query: Search query string
        
    Returns:
        JSON string with search results including titles, content, and sources
    """
    results = search_internet(query)
    return json.dumps(results, indent=2)


@tool
def search_google_news_tool(query: str, country: str = 'us', language: str = 'en') -> str:
    """Search Google News for recent news articles on a topic.
    
    Args:
        query: Search query string
        country: Country code (e.g., 'us', 'uk', 'au')
        language: Language code (e.g., 'en', 'es', 'fr')
        
    Returns:
        JSON string with news results including titles, snippets, sources, and dates
    """
    results = search_google_news(query, country, language)
    return json.dumps(results, indent=2)



@tool
def query_kb_tool(query: str) -> str:
    """Query Bedrock Knowledge Base for information.
    
    Args:
        query: Search query string
        
    Returns:
        JSON string with knowledge base results
    """
    results = query_knowledge_base(query)
    return json.dumps(results, indent=2)


@tool
def search_wikipedia_tool(query: str, sentences: int = 3) -> str:
    """Search Wikipedia for factual information.
    
    Args:
        query: Topic or term to search for
        sentences: Number of sentences in summary (default: 3)
        
    Returns:
        JSON string with Wikipedia article summary and URL
    """
    try:
        # Search for the topic
        search_results = wikipedia.search(query, results=3)
        if not search_results:
            return json.dumps({"error": "No Wikipedia articles found", "query": query})
        
        # Get summary of first result
        page = wikipedia.page(search_results[0], auto_suggest=False)
        summary = wikipedia.summary(search_results[0], sentences=sentences, auto_suggest=False)
        
        return json.dumps({
            "title": page.title,
            "summary": summary,
            "url": page.url,
            "related_topics": search_results[1:] if len(search_results) > 1 else []
        }, indent=2)
    except wikipedia.exceptions.DisambiguationError as e:
        # Handle disambiguation pages
        return json.dumps({
            "error": "Disambiguation page",
            "query": query,
            "options": e.options[:5]
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "query": query})


class ResearchAgent(Agent):
    """Deep research agent using Bedrock AgentCore with multiple knowledge sources."""
    
    def __init__(self, model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0", use_memory: bool = False):
        from memory_manager import ResearchMemoryManager
        
        boto_config = Config(
            read_timeout=7200,
            connect_timeout=600,
            retries={'max_attempts': 10, 'mode': 'adaptive'}
        )
        model = BedrockModel(
            model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            region_name=AWS_REGION,
            temperature=0.3,
            max_tokens=60000
        )
        
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        
        self.memory = ResearchMemoryManager(region=AWS_REGION) if use_memory else None
        
        super().__init__(
            name="ResearchAgent",
            model=model,
            system_prompt=RESEARCH_SYSTEM_PROMPT.format(current_date=current_date),
            tools=[search_internet_tool, search_google_news_tool, search_wikipedia_tool, query_kb_tool]
        )
    
    def extract_research_requests(self, fact_check: dict, editor: dict) -> list:
        """Extract specific research needs from editorial feedback."""
        requests = []
        
        # From fact-checker: missing/weak sources
        for issue in fact_check.get('issues', []):
            if issue.get('severity') in ['CRITICAL', 'HIGH']:
                if 'source' in issue.get('type', '').lower() or 'citation' in issue.get('issue', '').lower():
                    requests.append({
                        'claim': issue.get('location', ''),
                        'issue': issue.get('issue', ''),
                        'correction': issue.get('correction', ''),
                        'priority': 'critical' if issue.get('severity') == 'CRITICAL' else 'high'
                    })
        
        # From editor: explicit research requests in improvements
        for improvement in editor.get('improvements', []):
            if isinstance(improvement, dict):
                improvement_text = improvement.get('suggestion', '')
            else:
                improvement_text = str(improvement)
            
            if 'research' in improvement_text.lower() or 'source' in improvement_text.lower() or 'citation' in improvement_text.lower():
                requests.append({
                    'claim': improvement_text,
                    'issue': 'Editor requested more research',
                    'priority': 'medium'
                })
        
        return requests
    
    def do_targeted_research(self, requests: list, topic: str) -> list:
        """Do targeted research for specific claims that need sources."""
        if not requests:
            return []
        
        logger.info(f"\n{'='*70}")
        logger.info(f"🔬 TARGETED RESEARCH")
        logger.info(f"   → Researching {len(requests)} specific claims")
        logger.info(f"{'='*70}")
        
        new_findings = []
        
        for i, request in enumerate(requests, 1):
            claim = request.get('claim', '')
            issue = request.get('issue', '')
            priority = request.get('priority', 'medium')
            
            logger.info(f"\n   📋 Request {i}/{len(requests)} (Priority: {priority})")
            logger.info(f"   Claim: {claim[:100]}...")
            logger.info(f"   Issue: {issue[:100]}...")
            
            # Extract keywords from claim
            keywords = claim.split()[:5]  # Simple keyword extraction
            search_query = ' '.join(keywords)
            
            # Search internet for sources
            try:
                results = search_internet(search_query, max_results=3)
                if results:
                    for result in results:
                        new_findings.append({
                            'content': result.get('content', ''),
                            'url': result.get('url', ''),
                            'title': result.get('title', ''),
                            'source': 'targeted_internet_search',
                            'related_claim': claim,
                            'priority': priority
                        })
                    logger.info(f"   ✓ Found {len(results)} sources")
            except Exception as e:
                logger.warning(f"   ⚠️  Search failed: {e}")
        
        logger.info(f"\n   ✓ Targeted research complete: {len(new_findings)} new findings")
        logger.info(f"{'='*70}")
        return new_findings
    
    def research(self, topic: str, use_cache: bool = True) -> Dict:
        """Conduct deep research on a topic.
        
        Args:
            topic: The topic to research
            use_cache: If True, load from cache if available
        """
        # Check cache first
        cache_file = Path(f"output/research_cache/{topic.replace(' ', '_')}.json")
        if use_cache and cache_file.exists():
            logger.info("==" * 35)
            logger.info(f"📦 LOADING CACHED RESEARCH: {topic}")
            logger.info("==" * 35)
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                logger.info(f"   ✓ Loaded from cache: {cache_file}")
                logger.info(f"   Total findings: {len(cached['findings'])}")
                logger.info(f"   Confidence: {cached['confidence']:.2f}")
                logger.info("==" * 35)
                return cached
            except Exception as e:
                logger.warning(f"   ⚠️  Cache load failed: {e}, running fresh research")
        
        logger.info("=" * 70)
        logger.info(f"🔬 STARTING RESEARCH: {topic}")
        logger.info("=" * 70)
        
        # Generate research questions
        logger.info("\n📋 PHASE 1: Topic Analysis")
        questions = self._analyze_topic(topic)
        logger.info(f"   → Generated {len(questions)} research questions")
        for i, q in enumerate(questions, 1):
            logger.info(f"   {i}. {q}")
        
        # Iterative research
        all_findings = []
        confidence = 0.0
        iteration = 0
        
        while iteration < MAX_RESEARCH_ITERATIONS and confidence < CONFIDENCE_THRESHOLD:
            iteration += 1
            logger.info(f"\n🔄 ITERATION {iteration}/{MAX_RESEARCH_ITERATIONS}")
            logger.info("-" * 70)
            
            # ALWAYS search Wikipedia first for historical context
            if iteration == 1:
                logger.info("📖 Searching Wikipedia for historical context...")
                try:
                    wiki_page = wikipedia.page(topic, auto_suggest=True)
                    wiki_summary = wikipedia.summary(topic, sentences=5, auto_suggest=True)
                    all_findings.append({
                        'source': 'Wikipedia',
                        'title': wiki_page.title,
                        'content': wiki_summary,
                        'url': wiki_page.url,
                        'type': 'background'
                    })
                    logger.info(f"   ✓ Found Wikipedia article: {wiki_page.title}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Wikipedia search failed: {e}")
            
            # Query all sources (agent will use tools autonomously)
            logger.info("🤖 Agent gathering findings (will invoke tools as needed)...")
            findings = self._gather_findings(questions)
            all_findings.extend(findings)
            logger.info(f"   → Collected {len(findings)} new findings")
            
            # Synthesize and assess
            logger.info("\n🧠 Synthesizing findings...")
            synthesis = self._synthesize(all_findings)
            confidence = synthesis.get('confidence', 0)
            logger.info(f"   → Confidence: {confidence:.2f}")
            
            # Identify gaps for next iteration
            questions = synthesis.get('gaps', [])
            if questions:
                logger.info(f"   → Identified {len(questions)} knowledge gaps")
            
            if not questions:
                logger.info("   ✓ No gaps identified, research complete")
                break
        
        logger.info("\n" + "=" * 70)
        logger.info(f"✅ RESEARCH COMPLETE")
        logger.info(f"   Total findings: {len(all_findings)}")
        logger.info(f"   Final confidence: {confidence:.2f}")
        logger.info(f"   Iterations: {iteration}")
        logger.info("=" * 70)
        
        result = {
            'topic': topic,
            'findings': all_findings,
            'synthesis': synthesis,
            'confidence': confidence,
            'iterations': iteration,
            'timestamp': datetime.now().isoformat()
        }
        
        # Store in memory if enabled
        if self.memory:
            self.memory.initialize_memory(topic)
            self.memory.store_research_findings(all_findings, topic)
        
        # Save to cache
        cache_file = Path(f"output/research_cache/{topic.replace(' ', '_')}.json")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_file, 'w') as f:
                json.dump(result, f, indent=2)
            logger.info(f"\n💾 Research cached: {cache_file}")
        except Exception as e:
            logger.warning(f"   ⚠️  Failed to cache research: {e}")
        
        return result
    
    def _analyze_topic(self, topic: str) -> List[str]:
        """Break topic into research questions."""
        prompt = TOPIC_ANALYSIS_PROMPT.format(topic=topic)
        response = self(prompt)
        
        try:
            content = response.result if hasattr(response, 'result') else str(response)
            return json.loads(content)
        except:
            return [topic]  # Fallback to original topic
    
    def _gather_findings(self, questions: List[str]) -> List[Dict]:
        """Query all sources for each question."""
        findings = []
        
        for question in questions:
            # Knowledge Base
            kb_results = query_knowledge_base(question)
            findings.extend([{**r, 'type': 'knowledge_base'} for r in kb_results])
            
            # Web (if URLs available)
            urls = search_web(question)
            for url in urls:
                web_result = crawl_web(url)
                if 'error' not in web_result:
                    findings.append({**web_result, 'type': 'web'})
        
        return findings
    
    def _synthesize(self, findings: List[Dict]) -> Dict:
        """Synthesize findings and identify gaps."""
        prompt = SYNTHESIS_PROMPT.format(findings=json.dumps(findings, indent=2))
        response = self(prompt)
        
        try:
            content = response.result if hasattr(response, 'result') else str(response)
            return json.loads(content)
        except:
            return {'confidence': 0.5, 'gaps': []}
    
    def write_article(self, topic: str, research_data: Dict = None) -> str:
        """Write a professional article based on research findings."""
        # If no research provided, conduct research first
        if research_data is None:
            logger.info(f"\n📝 No research data provided, conducting research first...")
            research_data = self.research(topic)
        
        logger.info("\n" + "=" * 70)
        logger.info(f"✍️  WRITING ARTICLE: {topic}")
        logger.info("=" * 70)
        
        # Load personal story if available
        personal_story = "You are an experienced technology journalist."
        try:
            story_path = Path(__file__).parent / "personal_story.txt"
            if story_path.exists():
                with open(story_path, 'r') as f:
                    content = f.read().strip()
                    # Skip if it's just the template
                    if content and not content.startswith("Add your personal story"):
                        personal_story = content
                        logger.info("   ✓ Loaded personal story")
        except Exception as e:
            logger.warning(f"   ⚠️  Could not load personal story: {e}")
        
        # Format findings for article writing
        findings_text = json.dumps(research_data.get('findings', []), indent=2)
        logger.info(f"   → Using {len(research_data.get('findings', []))} findings")
        
        # Generate article
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        prompt = ARTICLE_WRITER_PROMPT.format(
            current_date=current_date,
            personal_story=personal_story,
            topic=topic,
            findings=findings_text
        )
        
        logger.info("   → Generating article with Claude...")
        response = self(prompt)
        
        article = response.result if hasattr(response, 'result') else str(response)
        logger.info(f"   ✓ Article generated ({len(article)} characters)")
        logger.info("=" * 70)
        
        return article


def markdown_to_html(markdown_text: str, title: str, workflow_dir: Path = None) -> str:
    """Convert markdown article to formatted HTML with optional editorial feedback."""
    import markdown
    import json
    import re
    
    # Check for article image
    image_section = ""
    if workflow_dir:
        image_path = workflow_dir / "article_image.png"
        if image_path.exists():
            image_section = f'<div style="text-align: center; margin: 2em 0;"><img src="article_image.png" alt="{title}" style="max-width: 70%; height: auto; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);"></div>'
    
    # Convert [Source: URL] to footnote references
    sources = []
    source_map = {}  # Track URL to footnote number mapping
    
    def replace_source(match):
        url = match.group(1)
        if url not in source_map:
            sources.append(url)
            source_map[url] = len(sources)
        footnote_num = source_map[url]
        return f'<sup><a href="{url}" target="_blank">[{footnote_num}]</a></sup>'
    
    markdown_text = re.sub(r'\[Source: (https?://[^\]]+)\]', replace_source, markdown_text)
    
    html_content = markdown.markdown(markdown_text, extensions=['extra', 'nl2br'])
    
    # Add sources section if any sources found
    sources_section = ""
    if sources:
        sources_section = '<div style="margin-top: 2em; padding-top: 1em; border-top: 1px solid #ccc; font-size: 0.9em;"><h3>Sources</h3><ol>'
        for i, url in enumerate(sources, 1):
            sources_section += f'<li><a href="{url}" target="_blank">{url}</a></li>'
        sources_section += '</ol></div>'
    
    # Load editorial feedback if available
    editorial_section = ""
    if workflow_dir:
        feedback_files = sorted(workflow_dir.glob("*_feedback_*.json"))
        factcheck_files = sorted(workflow_dir.glob("fact_check_*.json"))
        
        if feedback_files or factcheck_files:
            editorial_section = """
    <div style="margin-top: 3em; padding-top: 2em; border-top: 2px solid #ccc;">
        <button onclick="document.getElementById('editorial').style.display = document.getElementById('editorial').style.display === 'none' ? 'block' : 'none'" 
                style="background: #333; color: white; padding: 10px 20px; border: none; cursor: pointer; font-size: 1em;">
            📝 Show Editorial Journey
        </button>
        <div id="editorial" style="display: none; margin-top: 1em;">
"""
            
            for i, (editor_file, fact_file) in enumerate(zip(feedback_files, factcheck_files), 1):
                with open(editor_file) as f:
                    editor = json.load(f)
                with open(fact_file) as f:
                    factcheck = json.load(f)
                
                editorial_section += f"""
            <div style="background: #f5f5f5; padding: 1.5em; margin: 1em 0; border-left: 4px solid #333;">
                <h3>Revision {i}</h3>
                <div style="margin: 1em 0;">
                    <strong>Editor Grade:</strong> {editor.get('grade', 'N/A')} | 
                    <strong>Fact-Check Score:</strong> {factcheck.get('verification_score', 0)}/100 | 
                    <strong>Ready:</strong> {'✅' if editor.get('ready_to_publish') and factcheck.get('ready_to_publish') else '❌'}
                </div>
                <details style="margin-top: 1em;">
                    <summary style="cursor: pointer; font-weight: bold;">Editor Feedback</summary>
                    <pre style="white-space: pre-wrap; background: white; padding: 1em; margin-top: 0.5em; overflow-x: auto;">{json.dumps(editor, indent=2)}</pre>
                </details>
                <details style="margin-top: 1em;">
                    <summary style="cursor: pointer; font-weight: bold;">Fact-Check Report</summary>
                    <pre style="white-space: pre-wrap; background: white; padding: 1em; margin-top: 0.5em; overflow-x: auto;">{json.dumps(factcheck, indent=2)}</pre>
                </details>
            </div>
"""
            
            editorial_section += """
        </div>
    </div>
"""
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: Georgia, serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #333; }}
        h1 {{ font-size: 2.5em; margin-bottom: 0.5em; border-bottom: 3px solid #333; padding-bottom: 0.3em; }}
        h2 {{ font-size: 1.8em; margin-top: 1.5em; margin-bottom: 0.5em; }}
        h3 {{ font-size: 1.3em; margin-top: 1em; }}
        p {{ margin-bottom: 1em; text-align: justify; }}
        a {{ color: #0066cc; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        strong {{ font-weight: bold; }}
        em {{ font-style: italic; }}
        sup {{ font-size: 0.8em; }}
        sup a {{ color: #0066cc; font-weight: bold; }}
        details {{ margin: 0.5em 0; }}
        summary {{ padding: 0.5em; background: #e8e8e8; }}
        summary:hover {{ background: #d8d8d8; }}
    </style>
</head>
<body>
{image_section}
{html_content}
{sources_section}
{editorial_section}
</body>
</html>"""


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )
    
    import os
    from pathlib import Path
    from datetime import datetime
    from config import OUTPUT_DIR
    
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    import sys
    
    # Get topic from command line or use default
    if len(sys.argv) > 1:
        topic = ' '.join(sys.argv[1:])
    else:
        topic = "AI bubble"
        logger.info("⚠️  No topic provided, using default: 'AI bubble'")
        logger.info("   Usage: python -m research_agent.agent 'your topic here'\n")
    
    # Research and write article (with memory enabled)
    agent = ResearchAgent(use_memory=True)
    
    logger.info("\n" + "=" * 70)
    logger.info("🚀 RESEARCH AGENT")
    logger.info(f"   Topic: {topic}")
    logger.info(f"   Memory: Enabled (AgentCore)")
    logger.info("=" * 70)
    
    # Research then write
    research_result = agent.research(topic)
    article = agent.write_article(topic, research_result)
    
    # Create workflow directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workflow_dir = OUTPUT_DIR / f"{topic.replace(' ', '_')}_{timestamp}"
    workflow_dir.mkdir(exist_ok=True)
    
    # Save initial draft
    draft_file = workflow_dir / "article_v1_draft.md"
    with open(draft_file, 'w') as f:
        f.write(article)
    
    logger.info(f"\n💾 Initial draft saved: {draft_file}")
    
    # Run editorial workflow
    from editorial_workflow import EditorialWorkflow
    
    workflow = EditorialWorkflow(region=AWS_REGION)
    result = workflow.process_article(article, topic, workflow_dir, research_findings=research_result['findings'])
    
    # Save final article as markdown
    final_md = workflow_dir / "article_final.md"
    with open(final_md, 'w') as f:
        f.write(result['final_article'])
    
    # Format for Medium.com
    logger.info("\n" + "=" * 70)
    logger.info("📱 FORMATTING FOR MEDIUM.COM")
    logger.info("=" * 70)
    
    try:
        from medium_formatter_agent import MediumFormatterAgent
        
        medium_formatter = MediumFormatterAgent()
        medium_result = medium_formatter.format_for_medium(result['final_article'], topic)
        
        # Save Medium-formatted markdown
        medium_md = workflow_dir / "article_medium.md"
        with open(medium_md, 'w') as f:
            f.write(medium_result.get('formatted_markdown', result['final_article']))
        
        # Save Medium HTML
        medium_html = workflow_dir / "article_medium.html"
        with open(medium_html, 'w') as f:
            f.write(medium_result.get('html', ''))
        
        # Save image metadata
        if medium_result.get('images'):
            images_json = workflow_dir / "article_images.json"
            with open(images_json, 'w') as f:
                json.dump(medium_result['images'], f, indent=2)
            logger.info(f"   ✓ Saved {len(medium_result['images'])} images metadata")
        
        logger.info(f"   ✓ Medium markdown: {medium_md}")
        logger.info(f"   ✓ Medium HTML: {medium_html}")
        
    except Exception as e:
        logger.error(f"   ✗ Medium formatting failed: {e}")
        medium_md = final_md
        medium_html = workflow_dir / "article_final.html"
    
    logger.info("=" * 70)
    
    # Convert original to HTML (fallback)
    html_content = markdown_to_html(result['final_article'], topic, workflow_dir)
    final_html = workflow_dir / "article_final.html"
    with open(final_html, 'w') as f:
        f.write(html_content)
    
    logger.info(f"\n✅ PUBLICATION READY")
    logger.info(f"   Final article (HTML): {final_html}")
    logger.info(f"   Final article (MD): {final_md}")
    logger.info(f"   Medium article (HTML): {medium_html}")
    logger.info(f"   Medium article (MD): {medium_md}")
    logger.info(f"   Editor grade: {result['editor_grade']}")
    logger.info(f"   Fact-check score: {result['fact_check_score']}/100")
    logger.info(f"   Ready to publish: {result['ready_to_publish']}")
    logger.info(f"   Total revisions: {result['total_revisions']}")
    logger.info(f"   Research confidence: {research_result['confidence']:.2f}")
    logger.info(f"   Word count: ~{len(result['final_article'].split())} words")
    logger.info("\n" + "=" * 70)
