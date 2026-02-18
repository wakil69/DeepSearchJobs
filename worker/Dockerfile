FROM ghcr.io/wakil69/deepsearchjobs/base_worker:latest

WORKDIR /app

COPY . ./worker

CMD ["python", "-m", "worker.main"]