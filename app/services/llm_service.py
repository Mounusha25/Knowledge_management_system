from langchain.llms import Ollama
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferWindowMemory
from langchain.schema import HumanMessage, AIMessage
from langchain.prompts import PromptTemplate
from typing import Dict, List, Optional, Any
import time
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from config import Config

logger = logging.getLogger(__name__)

class EnhancedLLMService:
    """Enhanced LLM service with streaming, caching, and advanced prompt engineering"""
    
    def __init__(self, vector_store):
        self.vector_store = vector_store
        self.conversation_memory = ConversationBufferWindowMemory(
            memory_key="chat_history",
            return_messages=True,
            k=5  # Keep last 5 exchanges
        )
        
        # Initialize Ollama with enhanced configuration
        self.llm = Ollama(
            model=Config.OLLAMA_MODEL,
            base_url=Config.OLLAMA_BASE_URL,
            temperature=0.1,  # Lower temperature for more focused responses
            # Note: timeout is handled at the executor level
        )
        
        # Enhanced prompt template
        self.prompt_template = PromptTemplate(
            input_variables=["context", "question", "chat_history"],
            template="""You are an AI assistant specialized in analyzing and answering questions about documents. 
Use the following context from the uploaded documents to provide accurate, helpful, and detailed answers.

Context from documents:
{context}

Previous conversation:
{chat_history}

Question: {question}

Instructions:
1. Base your answer primarily on the provided context
2. If the context doesn't contain enough information, clearly state what information is missing
3. Provide specific quotes or references when possible
4. Structure your response clearly with bullet points or numbered lists when appropriate
5. If asked about topics not covered in the documents, politely redirect to available information

Answer:"""
        )
        
        # Initialize retrieval chain
        self.retrieval_chain = ConversationalRetrievalChain.from_llm(
            llm=self.llm,
            retriever=self.vector_store.vectorstore.as_retriever(
                search_kwargs={"k": Config.TOP_K_RETRIEVAL}
            ),
            memory=self.conversation_memory,
            combine_docs_chain_kwargs={"prompt": self.prompt_template},
            return_source_documents=True,
            verbose=True
        )
        
        # Response cache
        self.response_cache = {}
        self.executor = ThreadPoolExecutor(max_workers=3)
        
        logger.info("Enhanced LLM Service initialized successfully")
    
    def get_response(self, question: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Get response with timeout and comprehensive error handling"""
        timeout = timeout or 60  # Increased timeout to 60 seconds
        start_time = time.time()
        
        # Check cache first
        cache_key = self._generate_cache_key(question)
        cached_response = self._get_cached_response(cache_key)
        if cached_response:
            logger.info(f"Cache hit for question: {question[:50]}...")
            return cached_response
        
        try:
            # Submit task to executor with timeout
            future = self.executor.submit(self._process_query, question)
            result = future.result(timeout=timeout)
            
            processing_time = time.time() - start_time
            
            # Enhance response with metadata
            enhanced_result = {
                **result,
                'processing_time': round(processing_time, 2),
                'timestamp': int(time.time()),
                'model_used': Config.OLLAMA_MODEL,
                'cached': False
            }
            
            # Cache the response
            self._cache_response(cache_key, enhanced_result)
            
            logger.info(f"Query processed in {processing_time:.2f}s")
            return enhanced_result
            
        except TimeoutError:
            logger.error(f"Query timeout after {timeout}s: {question[:50]}...")
            return {
                'response': "I apologize, but the query is taking longer than expected to process. Please try again with a more specific question.",
                'error': 'timeout',
                'processing_time': timeout,
                'source_documents': []
            }
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}")
            return {
                'response': "I encountered an error while processing your question. Please try rephrasing your question or contact support if the issue persists.",
                'error': str(e),
                'processing_time': time.time() - start_time,
                'source_documents': []
            }
    
    def _process_query(self, question: str) -> Dict[str, Any]:
        """Internal method to process query with optimized performance"""
        start_time = time.time()
        
        try:
            logger.info(f"Starting _process_query for: {question[:50]}...")
            logger.info(f"Vector store type: {type(self.vector_store)}")
            logger.info(f"Vector store has similarity_search: {hasattr(self.vector_store, 'similarity_search')}")
            
            # Get relevant documents with enhanced search
            logger.info("About to call vector_store.similarity_search...")
            relevant_docs = self.vector_store.similarity_search(question, k=7)
            logger.info(f"Retrieved {len(relevant_docs)} documents for query: {question[:50]}...")
            
            if not relevant_docs:
                logger.warning(f"No relevant documents found for query: {question[:50]}...")
                return {
                    'response': "I couldn't find any relevant information in the uploaded documents to answer your question. Please make sure you have uploaded relevant documents or try rephrasing your question.",
                    'source_documents': [],
                    'confidence': 0.0,
                    'processing_time': round(time.time() - start_time, 2)
                }
            
            # Enhanced context preparation with intelligent truncation
            contexts = []
            total_chars = 0
            max_context_chars = 3000  # Increased for better context
            
            for i, doc in enumerate(relevant_docs):
                # Handle both old format (page_content) and new format (content key)
                if hasattr(doc, 'page_content'):
                    content = doc.page_content
                    metadata = doc.metadata
                elif isinstance(doc, dict):
                    content = doc.get('content', '')
                    metadata = doc.get('metadata', {})
                else:
                    continue
                
                if not content:
                    continue
                
                if total_chars + len(content) > max_context_chars:
                    # Intelligent truncation - prefer complete sentences
                    remaining_chars = max_context_chars - total_chars
                    if remaining_chars > 200:  # Only add if meaningful content can be added
                        truncated_content = self._intelligent_truncate(content, remaining_chars)
                        contexts.append(f"Source {i+1}: {truncated_content}")
                    break
                contexts.append(f"Source {i+1}: {content}")
                total_chars += len(content)
            
            context = "\n\n".join(contexts)
            logger.debug(f"Context length: {len(context)} characters")
            
            # Create optimized prompt
            prompt = self._create_optimized_prompt(question, context)
            
            # Get response from LLM with retry logic
            try:
                logger.info(f"Sending prompt to LLM (length: {len(prompt)} chars)")
                answer = self._call_llm_with_retry(prompt)
                logger.info(f"Received LLM response (length: {len(answer)} chars)")
            except Exception as llm_error:
                logger.error(f"LLM error: {str(llm_error)}")
                return {
                    'response': f"I found relevant documents but encountered an issue processing them. Please try again. Error: {str(llm_error)}",
                    'source_documents': self._format_source_documents(relevant_docs[:3]),
                    'confidence': 0.5,
                    'processing_time': round(time.time() - start_time, 2)
                }
            
            # Calculate enhanced confidence score
            confidence = self._calculate_enhanced_confidence(question, relevant_docs, answer)
            
            processing_time = round(time.time() - start_time, 2)
            logger.info(f"Query processed in {processing_time}s")
            
            return {
                'response': answer.strip(),
                'source_documents': self._format_source_documents(relevant_docs),
                'confidence': confidence,
                'retrieved_docs_count': len(relevant_docs),
                'processing_time': processing_time
            }
            
        except Exception as e:
            logger.error(f"Error in _process_query: {str(e)}")
            raise
    
    def _calculate_confidence(self, question: str, source_docs: List) -> float:
        """Calculate confidence score based on document relevance"""
        if not source_docs:
            return 0.0
        
        # Simple confidence calculation based on number of relevant docs
        # In a production system, this could be more sophisticated
        base_confidence = min(len(source_docs) / Config.TOP_K_RETRIEVAL, 1.0)
        
        # Boost confidence if docs contain question keywords
        question_words = set(question.lower().split())
        total_matches = 0
        
        for doc in source_docs:
            doc_words = set(doc.page_content.lower().split())
            matches = len(question_words.intersection(doc_words))
            total_matches += matches
        
        keyword_boost = min(total_matches / (len(question_words) * len(source_docs)), 0.3)
        
        return min(base_confidence + keyword_boost, 1.0)
    
    def _generate_cache_key(self, question: str) -> str:
        """Generate cache key for question"""
        import hashlib
        return hashlib.md5(question.lower().strip().encode()).hexdigest()
    
    def _get_cached_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached response if valid"""
        # Temporarily disable cache for debugging
        return None
    
    def _cache_response(self, cache_key: str, response: Dict[str, Any]):
        """Cache response"""
        if Config.ENABLE_QUERY_CACHE:
            self.response_cache[cache_key] = (response, time.time())
    
    def clear_memory(self):
        """Clear conversation memory"""
        self.conversation_memory.clear()
        logger.info("Conversation memory cleared")
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get conversation history"""
        messages = self.conversation_memory.chat_memory.messages
        history = []
        
        for message in messages:
            if isinstance(message, HumanMessage):
                history.append({"type": "human", "content": message.content})
            elif isinstance(message, AIMessage):
                history.append({"type": "ai", "content": message.content})
        
        return history
    
    def get_service_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        return {
            'model': Config.OLLAMA_MODEL,
            'cache_size': len(self.response_cache),
            'conversation_length': len(self.conversation_memory.chat_memory.messages),
            'vector_store_stats': self.vector_store.get_collection_stats()
        }
    
    def _intelligent_truncate(self, text, max_length):
        """Intelligently truncate text preferring complete sentences"""
        if len(text) <= max_length:
            return text
        
        # Try to truncate at sentence boundaries
        sentences = text.split('. ')
        truncated = ""
        
        for sentence in sentences:
            if len(truncated + sentence + ". ") <= max_length - 3:  # Leave space for "..."
                truncated += sentence + ". "
            else:
                break
        
        if truncated:
            return truncated.strip() + "..."
        else:
            # Fallback to character truncation
            return text[:max_length-3] + "..."
    
    def _create_optimized_prompt(self, question, context):
        """Create an optimized prompt for better LLM performance"""
        return f"""You are a helpful AI assistant that answers questions based on provided document content. 

Document Context:
{context}

Question: {question}

Instructions:
- Provide a comprehensive, accurate answer based on the document content
- If comparing or contrasting (like differences between versions), structure your response clearly
- If the documents don't contain enough information, state what is available and what might be missing
- Be specific and reference the document content when relevant
- Keep your answer focused and well-organized

Answer:"""
    
    def _call_llm_with_retry(self, prompt, max_retries=2):
        """Call LLM with retry logic for better reliability"""
        for attempt in range(max_retries + 1):
            try:
                response = self.llm(prompt)
                return response
            except Exception as e:
                if attempt == max_retries:
                    raise e
                logger.warning(f"LLM call attempt {attempt + 1} failed: {str(e)}, retrying...")
                time.sleep(1)  # Brief pause before retry
    
    def _format_source_documents(self, docs):
        """Format source documents for response"""
        formatted_docs = []
        
        for doc in docs:
            # Handle both old format (page_content) and new format (content key)
            if hasattr(doc, 'page_content'):
                content = doc.page_content
                metadata = doc.metadata
            elif isinstance(doc, dict):
                content = doc.get('content', '')
                metadata = doc.get('metadata', {})
            else:
                continue
            
            formatted_docs.append({
                'content': content[:300] + "..." if len(content) > 300 else content,
                'metadata': metadata,
                'source': metadata.get('source_file', metadata.get('filename', 'Unknown'))
            })
        
        return formatted_docs
    
    def _calculate_enhanced_confidence(self, question, docs, response):
        """Calculate enhanced confidence score"""
        if not docs:
            return 0.0
        
        base_confidence = min(len(docs) / 7, 1.0)  # Based on retrieval count
        
        # Boost confidence for longer, more detailed responses
        if len(response) > 200:
            base_confidence += 0.1
        
        # Boost confidence if response contains specific terms from question
        question_words = set(question.lower().split())
        response_words = set(response.lower().split())
        overlap = len(question_words.intersection(response_words)) / len(question_words)
        base_confidence += overlap * 0.2
        
        return min(1.0, base_confidence)

# Backward compatibility
class LLMService(EnhancedLLMService):
    """Backward compatibility alias"""
    
    def get_response(self, query):
        """Backward compatible method"""
        result = super().get_response(query)
        # Return just the response text for backward compatibility
        return result.get('response', 'Error processing query')