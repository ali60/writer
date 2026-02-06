"""Medium Formatter Agent - Formats articles for Medium.com with images and HTML."""

import json
import logging
from datetime import datetime
from strands import Agent
from strands.models import BedrockModel
from strands.tools import tool
from config import AWS_REGION
from botocore.config import Config

logger = logging.getLogger(__name__)

MEDIUM_FORMATTER_PROMPT = """You are a Medium.com content formatter and visual editor.

CURRENT DATE: {current_date}

Your role is to transform magazine articles into engaging Medium.com posts with:

1. **Visual Enhancement**:
   - Add relevant images from the web using search_image tool
   - Place images strategically (hero image, section breaks, key people)
   - Include image captions with credits

2. **Medium Formatting**:
   - Use Medium's formatting conventions (headers, pull quotes, dividers)
   - Break long paragraphs into shorter, scannable chunks
   - Add subheadings for better navigation
   - Use bold/italic for emphasis
   - Add horizontal rules (---) between major sections

3. **HTML Generation**:
   - Generate clean, semantic HTML
   - Include proper image tags with alt text
   - Use Medium-style CSS classes
   - Ensure mobile-responsive layout

FORMATTING GUIDELINES:
- Hero image at the top (related to main topic)
- Images every 3-4 paragraphs
- Pull quotes for key insights
- Subheadings every 4-5 paragraphs
- Short paragraphs (2-3 sentences max)
- Bold for key terms and statistics

OUTPUT FORMAT:
Return a JSON object with:
- formatted_markdown: Medium-formatted markdown with image placeholders
- html: Complete HTML version
- images: List of image URLs with captions and credits
"""


@tool
def search_image(query: str, max_results: int = 3) -> str:
    """Search for relevant images on the web.
    
    Args:
        query: Search query for images
        max_results: Maximum number of results to return
        
    Returns:
        JSON with image URLs, titles, and sources
    """
    import requests
    import os
    
    # Use SerpAPI for image search
    api_key = os.getenv('SERP_API_KEY')
    if not api_key:
        return json.dumps({"error": "SERP_API_KEY not set"})
    
    try:
        response = requests.get(
            'https://serpapi.com/search',
            params={
                'engine': 'google_images',
                'q': query,
                'api_key': api_key,
                'num': max_results
            },
            timeout=10
        )
        response.raise_for_status()
        
        data = response.json()
        images = []
        
        for item in data.get('images_results', [])[:max_results]:
            images.append({
                'url': item.get('original'),
                'thumbnail': item.get('thumbnail'),
                'title': item.get('title', ''),
                'source': item.get('source', ''),
                'link': item.get('link', '')
            })
        
        return json.dumps({'images': images}, indent=2)
    
    except Exception as e:
        return json.dumps({'error': str(e)})


@tool
def fetch_image_from_unsplash(query: str) -> str:
    """Fetch a high-quality free image from Unsplash.
    
    Args:
        query: Search query for the image
        
    Returns:
        JSON with image URL and attribution
    """
    import requests
    
    try:
        # Use Unsplash's public API (no key needed for basic search)
        response = requests.get(
            'https://source.unsplash.com/featured/',
            params={'q': query},
            timeout=10,
            allow_redirects=True
        )
        
        if response.status_code == 200:
            return json.dumps({
                'url': response.url,
                'query': query,
                'source': 'Unsplash',
                'attribution': f'Photo by Unsplash (https://unsplash.com/?utm_source=research_agent&utm_medium=referral)'
            })
        else:
            return json.dumps({'error': f'Status code: {response.status_code}'})
    
    except Exception as e:
        return json.dumps({'error': str(e)})


class MediumFormatterAgent(Agent):
    """Agent that formats articles for Medium.com with images and HTML."""
    
    def __init__(self, model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"):
        boto_config = Config(
            read_timeout=7200,
            connect_timeout=600,
            retries={'max_attempts': 10, 'mode': 'adaptive'}
        )
        model = BedrockModel(
            model_id=model_id,
            region_name=AWS_REGION,
            temperature=0.3,
            max_tokens=60000,
            config=boto_config
        )
        
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        
        super().__init__(
            name="MediumFormatterAgent",
            model=model,
            system_prompt=MEDIUM_FORMATTER_PROMPT.format(current_date=current_date),
            tools=[search_image]
        )
    
    def format_for_medium(self, article: str, topic: str) -> dict:
        """Format article for Medium.com with images and HTML.
        
        Args:
            article: The article text to format
            topic: The article topic for image search
            
        Returns:
            Dict with formatted_markdown, html, and images
        """
        logger.info("\n" + "=" * 70)
        logger.info("📱 FORMATTING FOR MEDIUM.COM")
        logger.info("=" * 70)
        
        prompt = f"""Format this article for Medium.com with editorial enhancements.

ARTICLE TOPIC: {topic}

ARTICLE TEXT:
{article}

EDITORIAL TASKS:
1. **Remove inline source citations** - Move [Source: URL] to footnotes at the end
2. **Add pull quotes** - Extract 5-7 powerful sentences as blockquotes using >
3. **Highlight key sentences** - Bold 3-5 impactful sentences (not statistics)
4. **Break paragraphs** - Split long paragraphs into 2-3 sentences each
5. **Add subheadings** - Insert ## subheadings every 4-5 paragraphs
6. **Section breaks** - Add --- between major sections

FORMATTING RULES:
- Remove ALL [Source: URL] citations from body text
- Create a "Sources" section at the end with numbered references
- Use > for pull quotes (powerful standalone insights)
- Use **bold** for key impactful sentences (not just statistics)
- Keep the article's voice and flow

Return ONLY valid JSON:
{{
  "formatted_markdown": "the full formatted article with enhancements..."
}}
"""
        
        logger.info("   → Applying editorial enhancements...")
        
        response = self(prompt)
        result = response.result if hasattr(response, 'result') else str(response)
        
        # Parse JSON from response
        try:
            # Extract JSON from markdown code blocks if present
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0].strip()
            elif '```' in result:
                result = result.split('```')[1].split('```')[0].strip()
            
            formatted = json.loads(result)
            
            # Convert markdown to HTML using markdown library
            import markdown
            md_content = formatted.get('formatted_markdown', article)
            html_body = markdown.markdown(md_content, extensions=['extra', 'codehilite'])
            
            # Wrap in proper HTML with Medium-style CSS
            html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{topic}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
            line-height: 1.8;
            color: #242424;
            background: #fff;
            padding: 60px 20px;
        }}
        article {{
            max-width: 680px;
            margin: 0 auto;
        }}
        h1 {{
            font-size: 42px;
            font-weight: 700;
            line-height: 1.25;
            margin: 0 0 30px;
            letter-spacing: -0.02em;
        }}
        h2 {{
            font-size: 32px;
            font-weight: 600;
            line-height: 1.3;
            margin: 50px 0 20px;
            letter-spacing: -0.01em;
        }}
        h3 {{
            font-size: 24px;
            font-weight: 600;
            margin: 40px 0 15px;
        }}
        p {{
            font-size: 21px;
            line-height: 1.8;
            margin: 0 0 30px;
            color: #242424;
        }}
        blockquote {{
            border-left: 3px solid #242424;
            padding-left: 23px;
            margin: 40px 0;
            font-size: 26px;
            line-height: 1.6;
            font-style: italic;
            color: #242424;
            font-weight: 400;
        }}
        blockquote p {{
            font-size: 26px;
            margin: 0;
        }}
        strong {{
            font-weight: 700;
        }}
        em {{
            font-style: italic;
        }}
        a {{
            color: #0066cc;
            text-decoration: none;
            border-bottom: 1px solid rgba(0, 102, 204, 0.3);
            transition: border-color 0.2s;
        }}
        a:hover {{
            border-bottom-color: #0066cc;
        }}
        hr {{
            border: none;
            text-align: center;
            margin: 60px 0;
            height: 1px;
            background: transparent;
        }}
        hr:before {{
            content: "...";
            display: inline-block;
            font-size: 30px;
            letter-spacing: 20px;
            color: #ccc;
        }}
        img {{
            width: 100%;
            height: auto;
            margin: 40px 0;
            border-radius: 4px;
        }}
        code {{
            background: #f5f5f5;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, "Courier New", monospace;
            font-size: 18px;
        }}
        pre {{
            background: #f5f5f5;
            padding: 20px;
            border-radius: 4px;
            overflow-x: auto;
            margin: 30px 0;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        ul, ol {{
            margin: 0 0 30px;
            padding-left: 30px;
        }}
        li {{
            font-size: 21px;
            line-height: 1.8;
            margin: 10px 0;
        }}
        .sources {{
            margin-top: 60px;
            padding-top: 40px;
            border-top: 1px solid #e0e0e0;
        }}
        .sources h3 {{
            font-size: 20px;
            margin-bottom: 20px;
            color: #666;
        }}
        .sources ol {{
            font-size: 16px;
            line-height: 1.6;
            color: #666;
        }}
        .sources li {{
            font-size: 16px;
            margin: 8px 0;
        }}
        @media (max-width: 768px) {{
            body {{
                padding: 30px 15px;
            }}
            h1 {{
                font-size: 32px;
            }}
            h2 {{
                font-size: 26px;
            }}
            p, li {{
                font-size: 18px;
            }}
            blockquote {{
                font-size: 22px;
                padding-left: 15px;
            }}
            blockquote p {{
                font-size: 22px;
            }}
        }}
    </style>
</head>
<body>
    <article>
        {html_body}
    </article>
</body>
</html>"""
            
            formatted['html'] = html
            
            logger.info(f"   ✓ Editorial enhancements applied")
            logger.info("=" * 70)
            
            return formatted
            
        except json.JSONDecodeError as e:
            logger.error(f"   ✗ Failed to parse JSON: {e}")
            logger.error(f"   Response preview: {result[:200]}...")
            
            # Fallback: use markdown library directly
            import markdown
            html_body = markdown.markdown(article, extensions=['extra', 'codehilite'])
            html = f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{topic}</title></head><body><article>{html_body}</article></body></html>'
            
            return {
                'formatted_markdown': article,
                'html': html
            }
