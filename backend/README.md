# Backend Structure

- `config.py`: environment loading, paths, runtime config
- `logging_setup.py`: console/file logging and size-based rotation
- `knowledge_base.py`: local knowledge base loading and retrieval
- `chat_service.py`: RAG reply generation and model access
- `inquiry_service.py`: inquiry validation and persistence
- `http_server.py`: HTTP routes and request logging
- `main.py`: application wiring and server startup

Compatibility entrypoint:

- `../sever_main.py`
