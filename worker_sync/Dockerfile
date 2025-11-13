FROM deepsearchjobs-base

WORKDIR /app

COPY . ./worker_sync

CMD ["python", "-m", "worker_sync.main"]