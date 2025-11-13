FROM deepsearchjobs-base

WORKDIR /app

COPY . ./worker_async

CMD ["python", "-m", "worker_async.main"]