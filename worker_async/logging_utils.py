import logging
import os

def get_job_logger(worker_id: str, company_id: int, company_name: str) -> logging.Logger:
    """Create a dedicated logger for a specific company/job."""
    os.makedirs("./logs", exist_ok=True)

    safe_name = "".join(c if c.isalnum() else "_" for c in company_name)[:50]
    log_path = f"./logs/worker_async_{worker_id}_company_{company_id}_{safe_name}.log"

    logger = logging.getLogger(f"worker_async_{worker_id}_company_{company_id}")
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers
    if not logger.handlers:
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        # stream_handler = logging.StreamHandler()

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        # stream_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        # logger.addHandler(stream_handler)
        
    logger.propagate = False

    return logger
