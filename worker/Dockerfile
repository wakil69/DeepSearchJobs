# FROM ghcr.io/wakil69/deepsearchjobs/base_worker:latest
FROM deepsearchjobs-base

WORKDIR /app

COPY . ./worker

CMD ["python", "-m", "worker.main"]