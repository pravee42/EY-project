import os
# Fix for macOS fork safety crash
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
# Disable proxy config to prevent specific macOS crashes with Celery/Billiard network calls
os.environ["NO_PROXY"] = "*"
from celery import Celery

# Ensure directories exist
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BROKER_OUT = os.path.join(BASE_DIR, 'broker', 'out')
BROKER_PROCESSED = os.path.join(BASE_DIR, 'broker', 'processed')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')

os.makedirs(BROKER_OUT, exist_ok=True)
os.makedirs(BROKER_PROCESSED, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

celery_app = Celery(
    'tenders',
    broker='filesystem://',
    backend=f'file://{RESULTS_DIR}',
    include=['celery_tasks']
)

celery_app.conf.update(
    worker_pool='solo', # CRITICAL: Forces single-threaded execution to bypass macOS forking crashes entirely
    broker_transport_options={
        'data_folder_in': BROKER_OUT,
        'data_folder_out': BROKER_OUT,
        'data_folder_processed': BROKER_PROCESSED
    },
    result_persistent=True,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json']
)
