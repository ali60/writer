"""Editorial Workflow - Orchestrates the writer-editor-fact-checker-authenticity revision cycle."""

import json
import logging
import time
from pathlib import Path
from datetime import datetime
from botocore.exceptions import EventStreamError
from editor_agent import EditorAgent
from writer_agent import WriterAgent
from fact_checker_agent import FactCheckerAgent
from authenticity_agent import AuthenticityAgent
from memory_manager import ResearchMemoryManager
from image_agent import ImageAgent
from humanizer_agent import HumanizerAgent
from layout_agent import LayoutAgent

logger = logging.getLogger(__name__)


def retry_on_bedrock_error(func, max_retries=3, initial_delay=5):
    """Retry function on Bedrock errors with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func()
        except EventStreamError as e:
            if attempt < max_retries - 1:
                delay = initial_delay * (2 ** attempt)
                logger.warning(f"   ⚠️  Bedrock error (attempt {attempt + 1}/{max_retries}): {e}")
                logger.info(f"   ⏳ Retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(f"   ❌ Failed after {max_retries} attempts")
                raise


class EditorialWorkflow:
    """Manages the editorial review, fact-checking, authenticity check, and revision process."""
    
    def __init__(self, region: str = "us-east-1", use_memory: bool = True):
        from agent import ResearchAgent
        self.editor = EditorAgent()
        self.writer = WriterAgent()
        self.fact_checker = FactCheckerAgent()
        self.authenticity = AuthenticityAgent()
        self.research_agent = ResearchAgent()
        self.image_agent = ImageAgent(region=region)
        self.humanizer = HumanizerAgent()
        self.layout_agent = LayoutAgent()
        self.max_iterations = 999  # Effectively unlimited
        self.use_memory = use_memory
        self.memory = ResearchMemoryManager(region=region) if use_memory else None
    
    def resume_from_version(self, article_path: str, user_feedback: str = None) -> dict:
        """Resume editorial workflow from a specific article version with optional user feedback."""
        article_path = Path(article_path)
        if not article_path.exists():
            raise FileNotFoundError(f"Article not found: {article_path}")
        
        # Parse version number from filename (e.g., article_v6.md -> 6)
        import re
        match = re.search(r'article_v(\d+)\.md', article_path.name)
        if not match:
            raise ValueError(f"Invalid article filename format: {article_path.name}")
        
        start_version = int(match.group(1))
        output_dir = article_path.parent
        
        # Extract topic from directory name
        topic_match = re.search(r'(.+)_\d{8}_\d{6}', output_dir.name)
        topic = topic_match.group(1).replace('_', ' ') if topic_match else "Unknown Topic"
        
        # Load article
        with open(article_path, 'r') as f:
            current_article = f.read()
        
        # Load previous feedback files
        editor_file = output_dir / f"editor_feedback_v{start_version}.json"
        fact_check_file = output_dir / f"fact_check_v{start_version}.json"
        authenticity_file = output_dir / f"authenticity_check_v{start_version}.json"
        
        previous_feedback = {}
        if editor_file.exists():
            with open(editor_file, 'r') as f:
                previous_feedback['editor'] = json.load(f)
        if fact_check_file.exists():
            with open(fact_check_file, 'r') as f:
                previous_feedback['fact_checker'] = json.load(f)
        if authenticity_file.exists():
            with open(authenticity_file, 'r') as f:
                previous_feedback['authenticity'] = json.load(f)
        
        # Add user feedback if provided
        if user_feedback:
            previous_feedback['user'] = {
                'feedback': user_feedback,
                'timestamp': datetime.now().isoformat()
            }
        
        # Load research cache if available
        research_findings = None
        cache_file = Path("output/research_cache") / f"{topic.replace(' ', '_')}.json"
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
                research_findings = cache_data.get('findings', [])
        
        logger.info("\n" + "=" * 70)
        logger.info("🔄 RESUMING EDITORIAL WORKFLOW")
        logger.info(f"   Topic: {topic}")
        logger.info(f"   Starting from: v{start_version}")
        logger.info(f"   User feedback: {'Yes' if user_feedback else 'No'}")
        logger.info(f"   Research cache: {'Loaded' if research_findings else 'Not found'}")
        logger.info("=" * 70)
        
        # Continue workflow from this version
        return self._continue_workflow(
            current_article=current_article,
            topic=topic,
            output_dir=output_dir,
            start_version=start_version,
            previous_feedback=previous_feedback,
            research_findings=research_findings
        )
    
    def process_article(self, article: str, topic: str, output_dir: Path, research_findings: list = None) -> dict:
        """Run the full editorial workflow: review → fact-check → authenticity → revise → repeat until ALL THREE approve."""
        logger.info("\n" + "=" * 70)
        logger.info("📰 EDITORIAL WORKFLOW STARTED")
        logger.info(f"   Topic: {topic}")
        logger.info(f"   Approval required: Editor (A-/A/A+) AND Fact-checker AND Authenticity")
        logger.info(f"   Max iterations: {self.max_iterations}")
        logger.info("=" * 70)
        
        return self._continue_workflow(
            current_article=article,
            topic=topic,
            output_dir=output_dir,
            start_version=0,
            previous_feedback=None,
            research_findings=research_findings
        )
    
    def _continue_workflow(self, current_article: str, topic: str, output_dir: Path, 
                          start_version: int, previous_feedback: dict = None, 
                          research_findings: list = None) -> dict:
        """Internal method to continue workflow from any version."""
        
        # Initialize memory
        if self.use_memory and self.memory:
            self.memory.initialize_memory(topic)
            if research_findings:
                self.memory.store_research_findings(research_findings, topic)
        
        revision_history = []
        
        # If resuming with previous feedback, apply it first
        if previous_feedback and start_version > 0:
            logger.info(f"\n{'='*70}")
            logger.info(f"📝 APPLYING PREVIOUS FEEDBACK (v{start_version})")
            logger.info(f"{'='*70}")
            
            # Combine all previous feedback
            combined_feedback = {
                'editor': previous_feedback.get('editor', {}),
                'fact_checker': previous_feedback.get('fact_checker', {}),
                'authenticity': previous_feedback.get('authenticity', {}),
                'user': previous_feedback.get('user', {}),
                'combined_issues': self._combine_issues(
                    previous_feedback.get('editor', {}),
                    previous_feedback.get('fact_checker', {}),
                    previous_feedback.get('authenticity', {})
                )
            }
            
            # Writer revises with all feedback including user feedback
            current_article = retry_on_bedrock_error(
                lambda: self.writer.revise_article(current_article, combined_feedback, topic)
            )
            
            # Save new revision
            next_version = start_version + 1
            revision_file = output_dir / f"article_v{next_version}.md"
            with open(revision_file, 'w') as f:
                f.write(current_article)
            logger.info(f"   💾 Revision saved: {revision_file.name}")
            
            # Update start version for next iteration
            start_version = next_version
        
        for revision_num in range(start_version, start_version + self.max_iterations):
            cycle_num = revision_num - start_version + 1
            logger.info(f"\n{'='*70}")
            logger.info(f"🔄 REVISION CYCLE {cycle_num}")
            logger.info(f"{'='*70}")
            
            # Step 1: Editor reviews (with fact-check context if available)
            previous_fact_check = None
            if revision_num > 1:
                # Load previous fact-check to inform editor
                prev_fact_check_file = output_dir / f"fact_check_v{revision_num - 1}.json"
                if prev_fact_check_file.exists():
                    with open(prev_fact_check_file, 'r') as f:
                        previous_fact_check = json.load(f)
            
            editor_feedback = retry_on_bedrock_error(
                lambda: self.editor.review_article(current_article, topic, previous_fact_check)
            )
            editor_grade = editor_feedback.get('grade', 'F')
            editor_ready = editor_grade in ['A', 'A+']  # Only A or A+ acceptable
            
            # Save editor feedback
            editor_file = output_dir / f"editor_feedback_v{revision_num}.json"
            with open(editor_file, 'w') as f:
                json.dump(editor_feedback, f, indent=2)
            logger.info(f"   💾 Editor feedback saved: {editor_file.name}")
            logger.info(f"   📝 Editor grade: {editor_grade}")
            logger.info(f"   {'✅' if editor_ready else '❌'} Editor approval: {editor_ready} (requires A or A+)")
            
            # Step 2: Fact-checker verifies
            fact_check = retry_on_bedrock_error(
                lambda: self.fact_checker.check_article(current_article, topic)
            )
            fact_check_ready = fact_check.get('ready_to_publish', False)
            critical_count = len([i for i in fact_check.get('issues', []) if i.get('severity') == 'CRITICAL'])
            
            # Save fact-check results
            fact_check_file = output_dir / f"fact_check_v{revision_num}.json"
            with open(fact_check_file, 'w') as f:
                json.dump(fact_check, f, indent=2)
            logger.info(f"   💾 Fact-check saved: {fact_check_file.name}")
            logger.info(f"   🔍 Verification score: {fact_check.get('verification_score', 0)}/100")
            logger.info(f"   ⚠️  Critical issues: {critical_count}")
            logger.info(f"   {'✅' if fact_check_ready else '❌'} Fact-checker approval: {fact_check_ready}")
            
            # Step 3: Authenticity check
            authenticity_check = retry_on_bedrock_error(
                lambda: self.authenticity.check_authenticity(current_article, topic)
            )
            authenticity_ready = authenticity_check.get('ready_to_publish', False)
            authenticity_score = authenticity_check.get('authenticity_score', 0)
            ai_patterns = len(authenticity_check.get('ai_patterns_found', []))
            
            # Save authenticity check
            authenticity_file = output_dir / f"authenticity_check_v{revision_num}.json"
            with open(authenticity_file, 'w') as f:
                json.dump(authenticity_check, f, indent=2)
            logger.info(f"   💾 Authenticity check saved: {authenticity_file.name}")
            logger.info(f"   🤖 Authenticity score: {authenticity_score}/100")
            logger.info(f"   ⚠️  AI patterns found: {ai_patterns}")
            logger.info(f"   {'✅' if authenticity_ready else '❌'} Authenticity approval: {authenticity_ready}")
            
            # Store in memory
            if self.use_memory and self.memory:
                self.memory.store_editorial_feedback(revision_num + 1, editor_feedback, fact_check, authenticity_check)
            
            # Track revision
            revision_history.append({
                'revision': revision_num + 1,
                'editor_grade': editor_grade,
                'editor_ready': editor_ready,
                'fact_check_score': fact_check.get('verification_score', 0),
                'fact_check_ready': fact_check_ready,
                'authenticity_score': authenticity_score,
                'authenticity_ready': authenticity_ready,
                'critical_issues': critical_count,
                'ai_patterns': ai_patterns
            })
            
            # Check if ALL THREE approve
            if editor_ready and fact_check_ready and authenticity_ready:
                logger.info("\n" + "=" * 70)
                logger.info("✅ APPROVED BY ALL THREE AGENTS")
                logger.info(f"   ✅ Editor: {editor_grade}")
                logger.info(f"   ✅ Fact-checker: {fact_check.get('verification_score', 0)}/100")
                logger.info(f"   ✅ Authenticity: {authenticity_score}/100")
                logger.info("   Article is ready to publish!")
                logger.info("=" * 70)
                break
            
            # Check if we've hit safety limit
            if revision_num >= self.max_iterations - 1:
                logger.warning("\n" + "=" * 70)
                logger.warning(f"⚠️  SAFETY LIMIT REACHED ({self.max_iterations} iterations)")
                logger.warning(f"   Editor approval: {editor_ready} (grade: {editor_grade})")
                logger.warning(f"   Fact-checker approval: {fact_check_ready}")
                logger.warning(f"   Authenticity approval: {authenticity_ready}")
                logger.warning("   Manual review required before publication")
                logger.warning("=" * 70)
                break
            
            # Step 4: Check if targeted research is needed
            # Trigger research if fact-checker score < 80 or has source issues
            fact_check_score = fact_check.get('verification_score', 0)
            has_source_issues = any(
                i.get('severity') in ['CRITICAL', 'HIGH'] and 
                ('source' in i.get('type', '').lower() or 'citation' in i.get('issue', '').lower())
                for i in fact_check.get('issues', [])
            )
            
            if fact_check_score < 80 or has_source_issues:
                # Extract research requests from feedback
                research_requests = self.research_agent.extract_research_requests(
                    fact_check, editor_feedback
                )
                
                if research_requests:
                    logger.info(f"\n   🔬 Source issues detected - triggering targeted research")
                    logger.info(f"   → {len(research_requests)} claims need better sources")
                    
                    # Do targeted research
                    new_findings = self.research_agent.do_targeted_research(
                        research_requests, topic
                    )
                    
                    if new_findings:
                        # Add to research findings
                        if research_findings is None:
                            research_findings = []
                        research_findings.extend(new_findings)
                        
                        # Update memory with new findings
                        if self.use_memory and self.memory:
                            self.memory.store_research_findings(new_findings, topic)
                        
                        logger.info(f"   ✓ Added {len(new_findings)} new sources to research cache")
            
            # Step 5: Combine feedback for writer
            combined_feedback = {
                'editor': editor_feedback,
                'fact_checker': fact_check,
                'authenticity': authenticity_check,
                'combined_issues': self._combine_issues(editor_feedback, fact_check, authenticity_check)
            }
            
            # Step 6: Writer revises based on combined feedback
            logger.info(f"\n   ❌ Not approved - continuing to revision {revision_num + 1}")
            current_article = retry_on_bedrock_error(
                lambda: self.writer.revise_article(current_article, combined_feedback, topic)
            )
            
            # Save revision
            revision_file = output_dir / f"article_v{revision_num + 1}.md"
            with open(revision_file, 'w') as f:
                f.write(current_article)
            logger.info(f"   💾 Revision saved: {revision_file.name}")
        
        logger.info("\n" + "=" * 70)
        logger.info("📰 EDITORIAL WORKFLOW COMPLETE")
        logger.info("=" * 70)
        
        # Humanize the final article
        current_article = retry_on_bedrock_error(
            lambda: self.humanizer.humanize(current_article, topic)
        )
        
        # Save humanized version
        humanized_file = output_dir / "article_final.md"
        with open(humanized_file, 'w') as f:
            f.write(current_article)
        logger.info(f"   💾 Humanized article saved: {humanized_file.name}")
        
        # Enhance layout with rich formatting
        layout_result = self.layout_agent.enhance_layout(current_article, topic, output_dir)
        
        # Generate article image
        image_result = self.image_agent.generate_image(current_article, topic, output_dir)
        
        # Final approval status
        final_editor_ready = editor_grade in ['A', 'A+', 'A-']
        final_fact_check_ready = fact_check.get('ready_to_publish', False)
        final_authenticity_ready = authenticity_check.get('ready_to_publish', False)
        all_approved = final_editor_ready and final_fact_check_ready and final_authenticity_ready
        
        return {
            'final_article': current_article,
            'editor_grade': editor_grade,
            'editor_ready': final_editor_ready,
            'fact_check_score': fact_check.get('verification_score', 0),
            'fact_check_ready': final_fact_check_ready,
            'authenticity_score': authenticity_score,
            'authenticity_ready': final_authenticity_ready,
            'ready_to_publish': all_approved,
            'total_revisions': len(revision_history),
            'revision_history': revision_history,
            'image': image_result,
            'layout': layout_result
        }
    
    def _combine_issues(self, editor_feedback: dict, fact_check: dict, authenticity_check: dict) -> list:
        """Combine editor, fact-checker, and authenticity issues into prioritized list."""
        issues = []
        
        # Add critical fact-check issues first
        for issue in fact_check.get('issues', []):
            if issue.get('severity') == 'CRITICAL':
                issues.append({
                    'source': 'fact-checker',
                    'priority': 'CRITICAL',
                    'issue': issue
                })
        
        # Add high-severity AI patterns from authenticity check
        for pattern in authenticity_check.get('ai_patterns_found', []):
            if pattern.get('severity') == 'HIGH':
                issues.append({
                    'source': 'authenticity',
                    'priority': 'HIGH',
                    'issue': pattern
                })
        
        # Add editor critical issues
        for issue in editor_feedback.get('critical_issues', []):
            issues.append({
                'source': 'editor',
                'priority': 'CRITICAL',
                'issue': issue
            })
        
        # Add high priority fact-check issues
        for issue in fact_check.get('issues', []):
            if issue.get('severity') == 'HIGH':
                issues.append({
                    'source': 'fact-checker',
                    'priority': 'HIGH',
                    'issue': issue
                })
        
        # Add medium-severity AI patterns
        for pattern in authenticity_check.get('ai_patterns_found', []):
            if pattern.get('severity') == 'MEDIUM':
                issues.append({
                    'source': 'authenticity',
                    'priority': 'MEDIUM',
                    'issue': pattern
                })
        
        return issues


if __name__ == "__main__":
    # Test the workflow
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # Read the most recent article
    output_dir = Path(__file__).parent.parent / 'output'
    articles = sorted(output_dir.glob('article_*.md'))
    
    if not articles:
        print("No articles found to review")
        exit(1)
    
    latest_article = articles[-1]
    print(f"\n📄 Testing editorial workflow on: {latest_article.name}\n")
    
    with open(latest_article, 'r') as f:
        article = f.read()
    
    # Extract topic from filename
    topic = latest_article.stem.replace('article_', '').replace('_', ' ')
    
    # Create workflow output directory
    workflow_dir = output_dir / f"editorial_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    workflow_dir.mkdir(exist_ok=True)
    
    # Run workflow
    workflow = EditorialWorkflow()
    result = workflow.process_article(article, topic, workflow_dir)
    
    # Save final article
    final_file = workflow_dir / "article_final.md"
    with open(final_file, 'w') as f:
        f.write(result['final_article'])
    
    print(f"\n✅ Final article: {final_file}")
    print(f"   Editor grade: {result['editor_grade']}")
    print(f"   Fact-check score: {result['fact_check_score']}/100")
    print(f"   Ready to publish: {result['ready_to_publish']}")
    print(f"   Revisions: {result['total_revisions']}")
