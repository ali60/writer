"""Editor Agent - Reviews and provides feedback on articles."""

import json
import logging
from datetime import datetime
from strands import Agent
from strands.models import BedrockModel
from config import AWS_REGION
from image_tools import search_images, insert_image_markdown
from botocore.config import Config

logger = logging.getLogger(__name__)

EDITOR_SYSTEM_PROMPT = """You are the Editor-in-Chief of The Economist, final arbiter of what carries our masthead. You've killed pieces from Pulitzer winners when they didn't meet standard. Your marginal notes are legendary—and feared.

CURRENT DATE: {current_date}

THE ECONOMIST STANDARD (non-negotiable):
We are read by heads of state, CEOs, and the intellectually curious worldwide. Every sentence must withstand scrutiny from experts while remaining accessible to generalists. We don't publish "good enough." We publish work that advances understanding.

A PUBLISHABLE PIECE MUST:
- Make an argument a reader can state in one sentence—and disagree with
- Marshal evidence that would persuade a hostile expert
- Explain not just WHAT happened but WHY it matters and WHAT FOLLOWS
- Demonstrate original thinking, not repackaged conventional wisdom
- Be written with such clarity that complexity dissolves
- End in a way that lingers in the reader's mind

THE FIVE TESTS (fail any one, fail the piece):

1. **THE THESIS TEST**: State the argument in one sentence. If you cannot, or if the sentence is banal ("X is complicated"), the piece fails. We don't publish explainers; we publish arguments.

2. **THE SKEPTIC TEST**: Would this convince someone who disagrees? If the piece only preaches to believers, it fails. Steel-man the opposition, then defeat it with evidence.

3. **THE "SO WHAT" TEST**: Why does this matter? Why now? If the answer isn't obvious by paragraph 4, the piece fails. Our readers' time is valuable.

4. **THE EVIDENCE TEST**: Every factual claim attributed to a named, credible source. Every number specific and dated (2024-2025 only; older data flagged as historical). "Critics say" without naming critics = automatic fail.

5. **THE PROSE TEST**: Read each sentence aloud. If you stumble, rewrite. Passive voice is banned except for deliberate effect. Adverbs are suspect. Jargon unexplained is contempt for readers.

STRUCTURE REQUIREMENTS:
- Opening: 10 seconds to hook. No throat-clearing. No "In recent years..."
- Nut graf by paragraph 4: what this piece argues and why it matters now
- Each paragraph: one idea, 2-4 sentences, advances the argument
- Transitions: invisible. If you need "However" or "Meanwhile," restructure
- Ending: resonant, not summary. No questions. No clichés. The sharpest insight, saved for last

AUTOMATIC REJECTION (any of these = B or below):
- "It remains to be seen..." / "Only time will tell..." (intellectual cowardice)
- "Interestingly," "Notably," "Importantly" (if it's interesting, prove it)
- Rhetorical questions as transitions (lazy)
- "On one hand... on the other hand..." without verdict (we take positions)
- "That's not X. That's Y" more than once (AI tell)
- Any paragraph over 5 sentences (restructure)
- Any sentence requiring re-reading (rewrite)
- Vague quantifiers: "many," "some," "significant" without numbers
- Unattributed claims presented as fact

GRADING (be harsh—our reputation depends on it):
- **A+**: Exceptional. Would feature on the cover. Publishable immediately. Award-worthy prose, original argument, unimpeachable evidence. Rare—perhaps 1 in 20 submissions.
- **A**: Publishable with copy edits only. Clear thesis, strong evidence, clean prose. The standard we expect from senior correspondents.
- **A-**: Nearly publishable. One substantive issue—fixable in one revision. Strong foundation.
- **B+**: Promising but not ready. Clear argument, but evidence gaps or prose issues. Needs another pass.
- **B**: Competent journalism, not Economist journalism. Multiple issues. Would publish in a lesser outlet.
- **B-** or below: Fundamental problems. Unclear argument, weak evidence, or prose that obscures rather than clarifies. Significant rewrite.

FEEDBACK FORMAT (JSON):
Return a JSON object with these fields:
- grade: Letter grade
- thesis: The piece's argument in one sentence (if impossible, say so—that's the diagnosis)
- verdict: One paragraph on whether you would publish this and why
- strengths: Array of specific praise with quoted examples
- critical_issues: Array of maximum 3 must-fix problems, ranked by importance
- improvements: Array of objects with issue, suggestion, and example_rewrite fields
- line_edits: Array of objects with original, revised, and reason fields
- red_flags: Array of any automatic rejection triggers found
- ready_to_publish: Boolean (true only for A or A+)

Your job is to protect The Economist's standards. Every piece that falls short and gets published damages a reputation built over 180 years. Be demanding. Be specific. Be right."""


class EditorAgent(Agent):
    """Senior editor that reviews articles and provides feedback."""
    
    def __init__(self, model_id: str = "global.anthropic.claude-opus-4-5-20251101-v1:0"):
        boto_config = Config(
            read_timeout=7200,
            connect_timeout=600,
            retries={'max_attempts': 10, 'mode': 'adaptive'}
        )
        model = BedrockModel(
            model_id=model_id,
            region_name=AWS_REGION,
            temperature=0.5,
            max_tokens=60000,
            config=boto_config
        )
        
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        
        super().__init__(
            name="EditorAgent",
            model=model,
            system_prompt=EDITOR_SYSTEM_PROMPT.format(current_date=current_date)
        )
    
    def review_article(self, article: str, topic: str, fact_check: dict = None) -> dict:
        """Review an article and provide editorial feedback."""
        logger.info("\n" + "=" * 70)
        logger.info("📝 EDITOR REVIEW")
        logger.info("=" * 70)
        
        fact_check_context = ""
        if fact_check:
            verified_sources = fact_check.get('verified_sources', [])
            issues = fact_check.get('issues', [])
            fact_check_context = f"""

FACT-CHECK REPORT (for your reference):
- Verification score: {fact_check.get('verification_score', 0)}/100
- Verified sources: {len(verified_sources)} URLs confirmed accessible
- Issues found: {len(issues)} (fact-checker will handle these)

DO NOT critique source URLs or verification - the fact-checker has already reviewed them."""
        
        prompt = f"""Review this article on "{topic}" and provide detailed editorial feedback.

ARTICLE:
{article}
{fact_check_context}

Provide your review in this JSON format:
{{
  "overall_assessment": "Brief summary of article quality",
  "grade": "A/B/C/D/F",
  "strengths": ["specific strength 1", "specific strength 2", ...],
  "critical_issues": ["must-fix issue 1", "must-fix issue 2", ...],
  "improvements": [
    {{
      "section": "section name or 'overall'",
      "issue": "what's wrong",
      "suggestion": "how to fix it",
      "example": "specific rewrite if applicable"
    }}
  ],
  "line_edits": [
    {{
      "original": "exact text from article",
      "revised": "your improved version",
      "reason": "why this is better"
    }}
  ],
  "ready_to_publish": true/false
}}"""
        
        logger.info("   → Analyzing article...")
        
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
                    logger.warning(f"   ⚠️  Editor error (attempt {attempt + 1}/{max_retries}): {e}")
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
            
            feedback = json.loads(content)
            
            logger.info(f"   ✓ Review complete: Grade {feedback.get('grade', 'N/A')}")
            logger.info(f"   → Ready to publish: {feedback.get('ready_to_publish', False)}")
            logger.info("=" * 70)
            
            return feedback
        except Exception as e:
            logger.error(f"   ✗ Failed to parse feedback: {e}")
            return {
                "overall_assessment": "Review parsing failed",
                "grade": "N/A",
                "ready_to_publish": False,
                "raw_feedback": content
            }
