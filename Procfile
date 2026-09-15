web: gunicorn src.server.app:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
worker: python worker.py
