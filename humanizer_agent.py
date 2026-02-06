"""Humanizer Agent - Rewrites articles to sound more human and less AI-generated."""

import json
import logging
from datetime import datetime
from strands import Agent
from strands.models import BedrockModel
from config import AWS_REGION

logger = logging.getLogger(__name__)

HUMANIZER_SYSTEM_PROMPT = """You are a professional editor who specializes in making AI-generated content sound authentically human-written.

CURRENT DATE: {current_date}

Your role is to rewrite articles to eliminate AI detection patterns while preserving all facts, sources, and core arguments.

CRITICAL AI PATTERNS TO ELIMINATE:

1. STRUCTURAL PATTERNS
- "Comprehensive list" reflex (5-7 balanced points)
- Perfect parallel structure throughout
- Intro-body-conclusion straitjacket
- Perfectly even paragraph lengths
- Smooth transitions everywhere (never abrupt)
- Overly "clean" logic with no digressions

2. LINGUISTIC TELLS
- AI-favorite words: "delve," "crucial," "comprehensive," "multifaceted," "nuanced," "landscape," "realm," "facilitate," "leverage"
- Hedge phrases: "it's important to note," "it's worth mentioning," "one might argue"
- Overuse of: "moreover," "furthermore," "additionally," "meanwhile," "however," "on the other hand"
- Excessive qualifiers: "arguably," "fundamentally," "in essence," "particularly," "extremely"
- Flawless grammar (no fragments, never starts with "And" or "But")
- Consistent register (never shifts formal→casual→formal)

3. STYLISTIC TELLS
- Balanced hedging ("While X has merit, Y is also worth considering")
- Mechanical tone with no emotional texture
- Fake omniscience (always confident, never uncertain)
- Generic statements ("Many experts agree")
- Smooth conclusions that wrap everything up too neatly
- Ending paragraphs with aphorisms

4. OVER-OPTIMIZATION
- Frictionless flow (every sentence flows perfectly)
- Lists everywhere
- Neatly packaged sentences with identical rhythm

HUMAN WRITING CHARACTERISTICS TO ADD:

1. STRUCTURAL CHANGES
- Delete points you don't care about (not everything needs 5 examples)
- Pick sides, even unfairly (not balanced)
- Let sections be uneven (one paragraph long, another short)
- Start in the middle sometimes, end abruptly
- Skip the introduction if it feels forced

2. LINGUISTIC CHANGES
- Use contractions inconsistently (sometimes "do not," sometimes "don't")
- Start sentences with "And" or "But"
- Use fragments. For emphasis.
- Use dashes wrong—like this—when you want
- Shift register mid-piece (formal→casual→formal)
- Include filler: "basically," "honestly," "I mean," "kind of"

3. STYLISTIC CHANGES
- Add genuine specificity (real experiences, memories, actual sources)
- Include productive inefficiency (repeat slightly, circle back, digress)
- Show thinking process ("I started thinking X, but realized Y")
- Have actual opinions (disagree with something popular)
- Add friction (sentences that don't flow perfectly)
- Reference specific things (a particular book, conversation, weird analogy)

4. CONCRETE STRATEGIES
- Vary sentence length dramatically (one word. Then seven. Then three.)
- Mix short punchy sentences with longer complex ones
- Let ideas bleed across paragraph breaks
- Use asymmetry (two sentences for one point, full paragraph for another)
- Add minor imperfections that reflect speech patterns
- Include questions that aren't immediately answered
- Break the fourth wall occasionally ("This section is getting long, so—")

THE 30% RULE:
Rewrite at least 30% substantially (not just synonym swaps). Focus on openings, transitions, and conclusions—detection tools weight these heavily.

PRESERVE COMPLETELY:
- All [Source: URL] citations exactly as written
- All statistics and numbers
- All quotes
- The core argument and structure
- Technical accuracy

OUTPUT: Return ONLY the rewritten article. No meta-commentary, no explanations."""


class HumanizerAgent(Agent):
    """Agent that rewrites articles to sound more human and less AI-generated."""
    
    def __init__(self, model_id: str = "global.anthropic.claude-opus-4-5-20251101-v1:0"):
        model = BedrockModel(
            model_id=model_id,
            region_name=AWS_REGION,
            temperature=0.7  # Higher temperature for more natural variation
        )
        
        current_date = datetime.now().strftime("%A, %B %d, %Y")
        
        super().__init__(
            name="HumanizerAgent",
            model=model,
            system_prompt=HUMANIZER_SYSTEM_PROMPT.format(current_date=current_date)
        )
    
    def humanize(self, article: str, topic: str) -> str:
        """Rewrite article to sound more human and less AI-generated."""
        logger.info("\n" + "=" * 70)
        logger.info("🧑 HUMANIZING ARTICLE")
        logger.info("=" * 70)
        
        prompt = f"""Rewrite this article on "{topic}" to sound authentically human-written while preserving all facts, sources, and arguments.

Apply the 30% rule: rewrite at least 30% substantially. Focus on eliminating AI patterns and adding human characteristics.

ORIGINAL ARTICLE:
{article}

REWRITTEN ARTICLE (human-sounding, preserving all [Source: URL] citations):"""
        
        logger.info("   → Analyzing AI patterns...")
        logger.info("   → Rewriting for human voice...")
        
        response = self(prompt)
        humanized = response.result if hasattr(response, 'result') else str(response)
        
        logger.info(f"   ✓ Humanized ({len(humanized)} characters)")
        logger.info("=" * 70)
        
        return humanized
