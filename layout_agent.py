"""Layout Agent - Enhances articles with rich formatting, images, and proper HTML structure."""

import json
import logging
import re
import requests
from pathlib import Path
from datetime import datetime
from strands import Agent
from strands.models import BedrockModel
from strands.tools import tool
from config import AWS_REGION

logger = logging.getLogger(__name__)

LAYOUT_SYSTEM_PROMPT = """You are a professional magazine layout designer who transforms plain text articles into beautifully formatted content.

CURRENT DATE: {current_date}

Your role is to enhance articles with:
1. Proper quote formatting (blockquotes for notable quotes)
2. Pull quotes for impactful statements
3. Identify people mentioned who need profile images
4. Add section breaks and visual hierarchy
5. Highlight key statistics in callout boxes
6. Format lists and data properly

OUTPUT FORMAT - Return JSON with this structure:
{{
  "formatted_markdown": "The enhanced markdown with proper formatting",
  "people_to_image": [
    {{"name": "Person Name", "context": "CEO of Company", "quote": "optional quote from them"}}
  ],
  "pull_quotes": ["Impactful quote 1", "Impactful quote 2"],
  "key_statistics": [
    {{"stat": "50%", "context": "five-year return"}}
  ]
}}

FORMATTING RULES:
- Use > for blockquotes when someone is quoted
- Use **bold** for emphasis on key terms
- Use --- for section breaks
- Add {{PERSON_IMAGE: Name}} placeholder where person images should go
- Add {{PULL_QUOTE: text}} for pull quotes
- Add {{STAT_BOX: stat | context}} for key statistics
- Preserve all [Source: URL] citations exactly

PRESERVE COMPLETELY:
- All [Source: URL] citations
- All facts and numbers
- Article structure and flow
- Technical accuracy"""


@tool
def search_person_image(name: str, context: str = "") -> str:
    """Search for a person's professional image using SerpAPI Google Images.
    
    Args:
        name: Person's name
        context: Additional context (e.g., "CEO of Amazon")
        
    Returns:
        JSON with image URL and attribution
    """
    import os
    
    try:
        serp_api_key = os.getenv('SERP_API_KEY')
        if not serp_api_key:
            return json.dumps({
                'name': name,
                'image_url': None,
                'note': 'SERP_API_KEY not configured'
            })
        
        # Use SerpAPI for Google Image Search
        search_query = f"{name} {context} professional photo headshot"
        url = "https://serpapi.com/search"
        
        params = {
            'engine': 'google_images',
            'q': search_query,
            'api_key': serp_api_key,
            'num': 1
        }
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        # Get first image result
        if data.get('images_results') and len(data['images_results']) > 0:
            first_image = data['images_results'][0]
            return json.dumps({
                'name': name,
                'image_url': first_image.get('original'),
                'thumbnail': first_image.get('thumbnail'),
                'source': first_image.get('source', 'Google Images'),
                'title': first_image.get('title', '')
            })
        
        # Fallback: use a placeholder service
        return json.dumps({
            'name': name,
            'image_url': f"https://ui-avatars.com/api/?name={name.replace(' ', '+')}&size=150&background=random",
            'source': 'UI Avatars (placeholder)',
            'note': 'No image found, using placeholder'
        })
        
    except Exception as e:
        # Fallback to placeholder on error
        return json.dumps({
            'name': name,
            'image_url': f"https://ui-avatars.com/api/?name={name.replace(' ', '+')}&size=150&background=random",
            'source': 'UI Avatars (placeholder)',
            'error': str(e)
        })


class LayoutAgent(Agent):
    """Agent that enhances articles with rich formatting and layout."""
    
    def __init__(self, model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"):
        model = BedrockModel(
            model_id=model_id,
            region_name=AWS_REGION,
            temperature=0.3
        )
        
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        
        super().__init__(
            name="LayoutAgent",
            model=model,
            system_prompt=LAYOUT_SYSTEM_PROMPT.format(current_date=current_date),
            tools=[search_person_image]
        )
    
    def enhance_layout(self, article: str, topic: str, output_dir: Path) -> dict:
        """Enhance article with rich formatting and layout."""
        logger.info("\n" + "=" * 70)
        logger.info("🎨 ENHANCING ARTICLE LAYOUT")
        logger.info("=" * 70)
        
        # Check if generated image exists
        generated_image = output_dir / "article_image.png"
        has_generated_image = generated_image.exists()
        
        prompt = f"""Analyze this article on "{topic}" and enhance it with rich formatting.

ARTICLE:
{article}

Return JSON with formatted_markdown, people_to_image, pull_quotes, and key_statistics."""
        
        logger.info("   → Analyzing article structure...")
        response = self(prompt)
        
        try:
            content = response.result if hasattr(response, 'result') else str(response)
            
            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            layout_data = json.loads(content)
            
            # Download person images
            person_images = {}
            for person in layout_data.get('people_to_image', []):
                logger.info(f"   → Searching image for {person['name']}...")
                result = search_person_image(person['name'], person.get('context', ''))
                person_images[person['name']] = json.loads(result)
            
            # Generate enhanced HTML
            enhanced_html = self._generate_enhanced_html(
                layout_data['formatted_markdown'],
                layout_data.get('pull_quotes', []),
                layout_data.get('key_statistics', []),
                person_images,
                topic,
                has_generated_image
            )
            
            # Save enhanced HTML
            html_file = output_dir / "article_enhanced.html"
            with open(html_file, 'w') as f:
                f.write(enhanced_html)
            
            logger.info(f"   ✓ Enhanced layout saved: {html_file.name}")
            logger.info("=" * 70)
            
            return {
                'success': True,
                'html_path': str(html_file),
                'people_images': person_images,
                'pull_quotes': layout_data.get('pull_quotes', []),
                'key_statistics': layout_data.get('key_statistics', [])
            }
            
        except Exception as e:
            logger.error(f"   ✗ Layout enhancement failed: {e}")
            logger.info("=" * 70)
            return {
                'success': False,
                'error': str(e)
            }
    
    def _generate_enhanced_html(self, markdown_text: str, pull_quotes: list, 
                                key_stats: list, person_images: dict, title: str,
                                has_generated_image: bool = False) -> str:
        """Generate enhanced HTML with rich formatting."""
        import markdown
        
        # Add hero image if generated image exists
        hero_image = ''
        if has_generated_image:
            hero_image = '''<div style="text-align: center; margin: 2em 0;">
    <img src="article_image.png" alt="Article hero image" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
</div>'''
        
        # Preserve [Source: URL] citations by converting them before markdown processing
        def replace_source(match):
            url = match.group(1)
            return f'<sup><a href="{url}" target="_blank">[Source]</a></sup>'
        
        markdown_text = re.sub(r'\[Source: (https?://[^\]]+)\]', replace_source, markdown_text)
        
        # Replace person image placeholders - match any content between {PERSON_IMAGE: and }
        for name, img_data in person_images.items():
            if img_data.get('image_url'):
                img_html = f'''<div class="person-image">
    <img src="{img_data['image_url']}" alt="{name}">
    <p class="caption">{name}</p>
</div>'''
                markdown_text = re.sub(
                    rf'\{{PERSON_IMAGE:\s*{re.escape(name)}\s*\}}',
                    img_html,
                    markdown_text,
                    flags=re.IGNORECASE
                )
        
        # Replace pull quote placeholders - match content between {PULL_QUOTE: and }
        def replace_pull_quote(match):
            quote_text = match.group(1).strip()
            return f'<aside class="pull-quote">"{quote_text}"</aside>'
        
        markdown_text = re.sub(
            r'\{PULL_QUOTE:\s*([^}]+)\}',
            replace_pull_quote,
            markdown_text,
            flags=re.IGNORECASE
        )
        
        # Replace stat box placeholders - match content between {STAT_BOX: and }
        def replace_stat_box(match):
            content = match.group(1).strip()
            parts = content.split('|')
            if len(parts) == 2:
                stat = parts[0].strip()
                context = parts[1].strip()
                return f'''<div class="stat-box">
    <div class="stat">{stat}</div>
    <div class="stat-context">{context}</div>
</div>'''
            return match.group(0)  # Return original if format is wrong
        
        markdown_text = re.sub(
            r'\{STAT_BOX:\s*([^}]+)\}',
            replace_stat_box,
            markdown_text,
            flags=re.IGNORECASE
        )
        
        # Convert markdown to HTML
        html_content = markdown.markdown(markdown_text, extensions=['extra', 'nl2br'])
        
        # Wrap in styled HTML
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ 
            font-family: Georgia, serif; 
            max-width: 800px; 
            margin: 40px auto; 
            padding: 0 20px; 
            line-height: 1.8; 
            color: #1a1a1a; 
        }}
        h1 {{ 
            font-size: 2.5em; 
            margin-bottom: 0.5em; 
            border-bottom: 3px solid #333; 
            padding-bottom: 0.3em; 
            line-height: 1.2;
        }}
        h2 {{ 
            font-size: 1.8em; 
            margin-top: 2em; 
            margin-bottom: 0.5em; 
            color: #2c3e50;
        }}
        blockquote {{
            border-left: 4px solid #3498db;
            margin: 2em 0;
            padding: 1em 2em;
            background: #f8f9fa;
            font-style: italic;
            color: #555;
        }}
        .pull-quote {{
            float: right;
            width: 40%;
            margin: 0 0 1em 2em;
            padding: 1.5em;
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            font-size: 1.3em;
            font-style: italic;
            color: #856404;
        }}
        .stat-box {{
            display: inline-block;
            margin: 1em 1em 1em 0;
            padding: 1.5em;
            background: #e3f2fd;
            border-radius: 8px;
            text-align: center;
            min-width: 150px;
        }}
        .stat {{
            font-size: 3em;
            font-weight: bold;
            color: #1976d2;
            line-height: 1;
        }}
        .stat-context {{
            margin-top: 0.5em;
            font-size: 0.9em;
            color: #555;
        }}
        .person-image {{
            float: left;
            margin: 0 2em 1em 0;
            text-align: center;
        }}
        .person-image img {{
            width: 150px;
            height: 150px;
            border-radius: 50%;
            object-fit: cover;
            border: 3px solid #ddd;
        }}
        .person-image .caption {{
            margin-top: 0.5em;
            font-size: 0.9em;
            color: #666;
        }}
        p {{ 
            margin-bottom: 1.2em; 
            text-align: justify; 
        }}
        a {{ 
            color: #0066cc; 
            text-decoration: none; 
        }}
        a:hover {{ 
            text-decoration: underline; 
        }}
        sup {{ 
            font-size: 0.8em; 
        }}
        sup a {{ 
            color: #0066cc; 
            font-weight: bold; 
        }}
        hr {{
            border: none;
            border-top: 1px solid #ddd;
            margin: 3em 0;
        }}
    </style>
</head>
<body>
{hero_image}
{html_content}
</body>
</html>"""
