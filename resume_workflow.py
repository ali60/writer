#!/usr/bin/env python3
"""Resume editorial workflow from a specific article version with optional user feedback."""

import sys
import logging
from pathlib import Path
from editorial_workflow import EditorialWorkflow
from medium_formatter_agent import MediumFormatterAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def main():
    if len(sys.argv) < 2:
        print("Usage: python resume_workflow.py <article_path> [user_feedback]")
        print("\nExample:")
        print("  python resume_workflow.py output/generated/LLM_models_releases_on_2025_20251122_222925/article_v6.md")
        print('  python resume_workflow.py output/generated/LLM_models_releases_on_2025_20251122_222925/article_v6.md "Add more examples about..."')
        sys.exit(1)
    
    article_path = sys.argv[1]
    user_feedback = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Initialize workflow
    workflow = EditorialWorkflow()
    
    # Resume from version
    result = workflow.resume_from_version(article_path, user_feedback)
    
    # Get output directory
    output_dir = Path(article_path).parent
    
    # Format for Medium
    formatter = MediumFormatterAgent()
    final_article = result['final_article']
    topic = Path(article_path).parent.name.split('_')[0].replace('_', ' ')
    
    medium_result = formatter.format_for_medium(final_article, topic)
    
    # Save Medium files
    md_path = output_dir / 'article_medium.md'
    html_path = output_dir / 'article_medium.html'
    
    with open(md_path, 'w') as f:
        f.write(medium_result.get('formatted_markdown', final_article))
    
    with open(html_path, 'w') as f:
        f.write(medium_result.get('html', ''))
    
    # Print summary
    logger.info("\n✅ PUBLICATION READY")
    logger.info(f"   Final article (HTML): {output_dir / 'article_final.html'}")
    logger.info(f"   Final article (MD): {output_dir / 'article_final.md'}")
    logger.info(f"   Medium article (HTML): {html_path}")
    logger.info(f"   Medium article (MD): {md_path}")
    logger.info(f"   Editor grade: {result['editor_grade']}")
    logger.info(f"   Fact-check score: {result['fact_check_score']}/100")
    logger.info(f"   Ready to publish: {result['ready_to_publish']}")
    logger.info(f"   Total revisions: {result['total_revisions']}")
    
    # Word count estimate
    word_count = len(final_article.split())
    logger.info(f"   Word count: ~{word_count} words")
    logger.info("\n" + "=" * 70)


if __name__ == "__main__":
    main()
