from flask import Flask, request, render_template, jsonify
from app.models.vector_store import EnhancedVectorStore
from app.services.llm_service import EnhancedLLMService
from app.utils.document_processor import DocumentProcessor, HybridChunker
import importlib.util
from config import Config
import os
import logging
import time
import signal
import sys
from contextlib import contextmanager
import threading

# Import the storage service module with hyphenated name
spec = importlib.util.spec_from_file_location("storage_service", "/Users/mounusha/Downloads/RAG_based_kms/app/services/storage-service.py")
storage_service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage_service_module)
S3Storage = storage_service_module.S3Storage

# Initialize configuration and logging
Config.setup_logging()
logger = logging.getLogger(__name__)

# Initialize Flask app with enhanced configuration
app = Flask(__name__, 
           template_folder='app/templates', 
           static_folder='app/static')

app.config.update({
    'SECRET_KEY': Config.SECRET_KEY,
    'MAX_CONTENT_LENGTH': Config.MAX_FILE_SIZE_MB * 1024 * 1024,
    'UPLOAD_FOLDER': Config.UPLOAD_FOLDER
})

# Simple rate limiting (basic implementation)
request_count = {}
request_lock = threading.Lock()

def check_rate_limit(remote_addr, limit_per_minute=60):
    """Basic rate limiting implementation"""
    current_time = time.time()
    minute_ago = current_time - 60
    
    with request_lock:
        if remote_addr not in request_count:
            request_count[remote_addr] = []
        
        # Remove old requests
        request_count[remote_addr] = [
            req_time for req_time in request_count[remote_addr] 
            if req_time > minute_ago
        ]
        
        # Check if limit exceeded
        if len(request_count[remote_addr]) >= limit_per_minute:
            return False
        
        # Add current request
        request_count[remote_addr].append(current_time)
        return True

# Initialize core services
vector_store = EnhancedVectorStore(persist_directory=Config.VECTOR_DB_PATH)
document_processor = DocumentProcessor(HybridChunker(
    chunk_size=Config.CHUNK_SIZE,
    chunk_overlap=Config.CHUNK_OVERLAP
))
storage_service = S3Storage()
llm_service = EnhancedLLMService(vector_store)

# Application metrics
app_metrics = {
    'total_uploads': 0,
    'total_queries': 0,
    'total_documents': 0,
    'documents_processed': 0,
    'chunks_created': 0,
    'startup_time': time.time(),
    'errors': {
        'upload_errors': 0,
        'query_errors': 0,
        'system_errors': 0
    }
}

# Thread lock for metrics
metrics_lock = threading.Lock()

@contextmanager
def error_handling(error_type: str):
    """Context manager for consistent error handling and metrics"""
    try:
        yield
    except Exception as e:
        with metrics_lock:
            app_metrics['errors'][error_type] += 1
        logger.error(f"{error_type}: {str(e)}")
        raise

def initialize_app():
    """Initialize application components"""
    logger.info("Initializing AI Knowledge Management System...")
    
    # Validate configuration
    try:
        Config.validate_config()
        logger.info("Configuration validated successfully")
    except Exception as e:
        logger.error(f"Configuration validation failed: {str(e)}")
        sys.exit(1)
    
    # Create necessary directories
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(os.path.dirname(Config.VECTOR_DB_PATH), exist_ok=True)
    
    logger.info("Application initialized successfully")

# Initialize the app immediately
initialize_app()

@app.route('/')
def index():
    """Render main application page"""
    return render_template('index.html')

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Check vector store
        vector_stats = vector_store.get_collection_stats()
        
        # Check LLM service
        llm_stats = llm_service.get_service_stats()
        
        uptime = time.time() - app_metrics['startup_time']
        
        return jsonify({
            'status': 'healthy',
            'uptime_seconds': int(uptime),
            'vector_store': vector_stats,
            'llm_service': llm_stats,
            'metrics': app_metrics,
            'timestamp': int(time.time())
        })
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': int(time.time())
        }), 500

@app.route('/upload', methods=['POST'])
def upload_document():
    """Enhanced document upload with comprehensive validation and processing"""
    
    # Basic rate limiting
    if not check_rate_limit(request.remote_addr, Config.RATE_LIMIT_PER_MINUTE):
        return jsonify({
            'error': 'Rate limit exceeded',
            'message': 'Too many requests. Please try again later.'
        }), 429
    
    with error_handling('upload_errors'):
        logger.info("Upload endpoint called")
        
        # Validate request
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Basic file validation
        if not file.filename:
            return jsonify({'error': 'Invalid filename'}), 400
            
        # Check file extension
        allowed_extensions = {'.pdf', '.txt', '.md', '.docx'}
        file_ext = os.path.splitext(file.filename.lower())[1]
        if file_ext not in allowed_extensions:
            return jsonify({
                'error': 'Unsupported file type',
                'supported_types': list(allowed_extensions)
            }), 400

        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)  # Reset file pointer
        
        max_size = Config.MAX_FILE_SIZE_MB * 1024 * 1024
        if file_size > max_size:
            return jsonify({
                'error': f'File too large. Maximum size: {Config.MAX_FILE_SIZE_MB}MB'
            }), 400

        logger.info(f"Processing file: {file.filename} ({file_size} bytes)")
        
        # Save file temporarily
        import tempfile
        temp_file_path = None
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
                temp_file_path = temp_file.name
                file.save(temp_file_path)
            
            # Validate file with DocumentProcessor
            if not document_processor.validate_file(temp_file_path):
                return jsonify({
                    'error': 'File validation failed',
                    'message': 'File could not be processed'
                }), 400

            # Process document
            chunks = document_processor.process_document(temp_file_path)
            
            logger.info(f"Document processing completed. Chunks generated: {len(chunks)}")
            
            if not chunks:
                logger.error(f"No chunks generated for file: {file.filename}")
                logger.error(f"File size: {file_size} bytes, Extension: {file_ext}")
                logger.error(f"Temp file path: {temp_file_path}")
                return jsonify({
                    'error': 'Document processing failed',
                    'message': 'No content could be extracted from the file',
                    'details': f'File: {file.filename}, Size: {file_size} bytes, Type: {file_ext}'
                }), 500

            # Store chunks in vector database
            # Convert chunks to LangChain Document objects
            from langchain.schema import Document
            
            documents = []
            for chunk in chunks:
                doc = Document(
                    page_content=chunk['content'],
                    metadata=chunk['metadata']
                )
                documents.append(doc)
            
            vector_store.add_documents(documents)
            
            # Upload to S3 if configured
            s3_url = None
            if Config.AWS_ACCESS_KEY_ID and Config.AWS_SECRET_ACCESS_KEY:
                try:
                    file.seek(0)  # Reset file pointer
                    s3_url = storage_service.upload_file(file, file.filename)
                    logger.info("File uploaded to S3")
                except Exception as e:
                    logger.warning(f"S3 upload failed: {str(e)}")
                    # Continue without S3 upload

            # Update metrics
            with metrics_lock:
                app_metrics['documents_processed'] += 1
                app_metrics['chunks_created'] += len(chunks)

            return jsonify({
                'success': True,
                'message': 'Document processed successfully',
                'filename': file.filename,
                'chunks_created': len(chunks),
                's3_url': s3_url,
                'processing_stats': document_processor.get_processing_stats()
            })

        except Exception as e:
            logger.error(f"Upload processing error: {str(e)}")
            return jsonify({
                'error': 'Failed to process document',
                'message': str(e)
            }), 500
        
        finally:
            # Clean up temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp file: {str(e)}")

@app.route('/query', methods=['POST'])
def query():
    """Enhanced query processing with comprehensive response"""
    
    # Basic rate limiting
    if not check_rate_limit(request.remote_addr, Config.RATE_LIMIT_PER_MINUTE):
        return jsonify({
            'error': 'Rate limit exceeded',
            'message': 'Too many requests. Please try again later.'
        }), 429
    
    with error_handling('query_errors'):
        data = request.json
        if not data or 'question' not in data:
            return jsonify({'error': 'No question provided'}), 400

        question = data['question'].strip()
        if not question:
            return jsonify({'error': 'Question cannot be empty'}), 400

        logger.info(f"Processing query: {question[:100]}...")

        # Get enhanced response
        response_data = llm_service.get_response(question)
        
        # Update metrics
        with metrics_lock:
            app_metrics['total_queries'] += 1

        # Return enhanced response
        return jsonify({
            'response': response_data['response'],
            'metadata': {
                'processing_time': response_data.get('processing_time', 0),
                'confidence': response_data.get('confidence', 0),
                'source_count': len(response_data.get('source_documents', [])),
                'cached': response_data.get('cached', False),
                'model': response_data.get('model_used', Config.OLLAMA_MODEL)
            },
            'sources': response_data.get('source_documents', [])
        })

@app.route('/stats')
def get_stats():
    """Get application statistics"""
    try:
        vector_stats = vector_store.get_collection_stats()
        llm_stats = llm_service.get_service_stats()
        
        return jsonify({
            'application': {
                'uptime_seconds': int(time.time() - app_metrics['startup_time']),
                'total_uploads': app_metrics['total_uploads'],
                'total_queries': app_metrics['total_queries'],
                'total_documents': app_metrics['total_documents'],
                'errors': app_metrics['errors']
            },
            'vector_store': vector_stats,
            'llm_service': llm_stats,
            'configuration': {
                'model': Config.OLLAMA_MODEL,
                'chunk_size': Config.CHUNK_SIZE,
                'embedding_model': Config.EMBEDDING_MODEL,
                'max_file_size_mb': Config.MAX_FILE_SIZE_MB
            }
        })
    except Exception as e:
        logger.error(f"Stats endpoint failed: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.errorhandler(413)
def file_too_large(e):
    """Handle file too large error"""
    return jsonify({
        'error': 'File too large',
        'message': f'File size exceeds the maximum limit of {Config.MAX_FILE_SIZE_MB}MB'
    }), 413

@app.errorhandler(500)
def internal_error(e):
    """Handle internal server errors"""
    with metrics_lock:
        app_metrics['errors']['system_errors'] += 1
    
    logger.error(f"Internal server error: {str(e)}")
    return jsonify({
        'error': 'Internal server error',
        'message': 'An unexpected error occurred. Please try again later.'
    }), 500

def signal_handler(sig, frame):
    """Graceful shutdown handler"""
    logger.info("Received shutdown signal, cleaning up...")
    sys.exit(0)

if __name__ == '__main__':
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info(f"Starting AI Knowledge Management System on {Config.HOST}:{Config.PORT}")
    logger.info(f"Environment: {Config.ENV}")
    logger.info(f"Debug mode: {Config.DEBUG}")
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        threaded=True
    )