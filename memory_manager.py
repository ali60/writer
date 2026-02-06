"""AgentCore Memory integration for research and editorial workflow."""

import logging
import boto3
from typing import List, Dict

logger = logging.getLogger(__name__)


class ResearchMemoryManager:
    """Manages memory for research findings, sources, and editorial feedback using Bedrock AgentCore."""
    
    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.control_client = boto3.client('bedrock-agentcore-control', region_name=region)
        self.runtime_client = boto3.client('bedrock-agentcore', region_name=region)
        self.memory_id = None
        self.session_id = None
        
    def initialize_memory(self, topic: str) -> str:
        """Create or get memory resource for this research session."""
        logger.info("🧠 Initializing AgentCore Memory...")
        
        memory_name = "ResearchEditorialMemory"
        
        # Check if memory already exists
        try:
            response = self.control_client.list_memories()
            for memory in response.get('memories', []):
                # Check both name field and ID (ID contains name as prefix)
                mem_name = memory.get('name')
                mem_id = memory.get('id', '')
                if mem_name == memory_name or mem_id.startswith(f"{memory_name}-"):
                    self.memory_id = mem_id
                    # Sanitize session ID: only alphanumeric, hyphens, underscores
                    self.session_id = ''.join(c if c.isalnum() or c in '-_' else '_' for c in topic)[:50]
                    logger.info(f"   ✓ Using existing memory: {self.memory_id}")
                    return self.memory_id
        except Exception as e:
            logger.warning(f"   ⚠️  Could not list memories: {e}")
        
        try:
            response = self.control_client.create_memory(
                name=memory_name,
                description="Memory store for research findings, sources, and editorial feedback",
                eventExpiryDuration=30,
                memoryStrategies=[
                    {'semanticMemoryStrategy': {'name': 'researchSemanticMemory'}},
                    {'summaryMemoryStrategy': {'name': 'researchSummaryMemory'}}
                ]
            )
            self.memory_id = response.get('id')
            # Sanitize session ID: only alphanumeric, hyphens, underscores
            self.session_id = ''.join(c if c.isalnum() or c in '-_' else '_' for c in topic)[:50]
            logger.info(f"   ✓ Created new memory: {self.memory_id}")
            return self.memory_id
        except Exception as e:
            logger.error(f"   ❌ Failed to initialize memory: {e}")
            logger.info(f"   → Continuing without memory")
            return None
    
    def store_research_findings(self, findings: list, topic: str):
        """Store research findings in short-term memory."""
        if not self.memory_id or not self.session_id:
            return
            
        logger.info(f"   💾 Storing {len(findings)} research findings...")
        
        try:
            from datetime import datetime
            for i, finding in enumerate(findings, 1):
                content = f"Finding #{i}: {finding.get('source', 'Unknown')}\n{finding.get('content', '')[:500]}"
                # Truncate and sanitize URL for metadata
                url = finding.get('url', '')
                # Remove invalid characters and truncate to 256 chars
                url = ''.join(c for c in url if c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._:/=+@-')
                url = url[:256]
                
                self.runtime_client.create_event(
                    memoryId=self.memory_id,
                    sessionId=self.session_id,
                    actorId="ResearchAgent",
                    eventTimestamp=int(datetime.now().timestamp()),
                    payload=[{
                        'conversational': {
                            'role': 'OTHER',
                            'content': {'text': content}
                        }
                    }],
                    metadata={
                        'source': {'stringValue': finding.get('source', '')[:256]},
                        'url': {'stringValue': url},
                        'finding_num': {'stringValue': str(i)}
                    }
                )
        except Exception as e:
            logger.warning(f"   ⚠️  Failed to store findings: {e}")
    
    def store_editorial_feedback(self, revision_num: int, editor_feedback: dict, fact_check: dict, authenticity_check: dict):
        """Store editorial feedback in short-term memory."""
        if not self.memory_id or not self.session_id:
            return
            
        logger.info(f"   💾 Storing editorial feedback v{revision_num}...")
        
        try:
            from datetime import datetime
            timestamp = int(datetime.now().timestamp())
            
            self.runtime_client.create_event(
                memoryId=self.memory_id,
                sessionId=self.session_id,
                actorId="EditorAgent",
                eventTimestamp=timestamp,
                payload=[{
                    'conversational': {
                        'role': 'ASSISTANT',
                        'content': {'text': f"Revision {revision_num}: Grade {editor_feedback.get('grade')}, {len(editor_feedback.get('critical_issues', []))} critical issues"}
                    }
                }],
                metadata={
                    'revision': {'stringValue': str(revision_num)},
                    'grade': {'stringValue': editor_feedback.get('grade', '')}
                }
            )
            
            self.runtime_client.create_event(
                memoryId=self.memory_id,
                sessionId=self.session_id,
                actorId="FactCheckerAgent",
                eventTimestamp=timestamp,
                payload=[{
                    'conversational': {
                        'role': 'ASSISTANT',
                        'content': {'text': f"Revision {revision_num}: Score {fact_check.get('verification_score')}/100"}
                    }
                }],
                metadata={
                    'revision': {'stringValue': str(revision_num)},
                    'score': {'stringValue': str(fact_check.get('verification_score', 0))}
                }
            )
            
            self.runtime_client.create_event(
                memoryId=self.memory_id,
                sessionId=self.session_id,
                actorId="AuthenticityAgent",
                eventTimestamp=timestamp,
                payload=[{
                    'conversational': {
                        'role': 'ASSISTANT',
                        'content': {'text': f"Revision {revision_num}: Score {authenticity_check.get('authenticity_score')}/100"}
                    }
                }],
                metadata={
                    'revision': {'stringValue': str(revision_num)},
                    'score': {'stringValue': str(authenticity_check.get('authenticity_score', 0))}
                }
            )
        except Exception as e:
            logger.warning(f"   ⚠️  Failed to store feedback: {e}")
    
    def retrieve_relevant_context(self, query: str, max_results: int = 10) -> List[Dict]:
        """Retrieve relevant memories using semantic search."""
        if not self.memory_id:
            return []
            
        try:
            response = self.runtime_client.retrieve_memory_records(
                memoryId=self.memory_id,
                query=query,
                maxResults=max_results
            )
            return response.get('memoryRecords', [])
        except Exception as e:
            logger.warning(f"   ⚠️  Failed to retrieve memories: {e}")
            return []
    
    def get_session_history(self) -> List[Dict]:
        """Get all events from current session."""
        if not self.memory_id or not self.session_id:
            return []
            
        try:
            response = self.runtime_client.list_events(
                memoryId=self.memory_id,
                sessionId=self.session_id
            )
            return response.get('events', [])
        except Exception as e:
            logger.warning(f"   ⚠️  Failed to get session history: {e}")
            return []
    
    def cleanup(self):
        """Delete memory resource."""
        if self.memory_id:
            try:
                logger.info(f"   🗑️  Cleaning up memory: {self.memory_id}")
                self.control_client.delete_memory(memoryId=self.memory_id)
            except Exception as e:
                logger.warning(f"   ⚠️  Failed to cleanup memory: {e}")
