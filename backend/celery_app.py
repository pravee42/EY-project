import os
from celery import Celery

# Ensure directories exist
os.makedirs('./broker/out', exist_ok=True)
os.makedirs('./broker/processed', exist_ok=True)
os.makedirs('./results', exist_ok=True)

celery_app = Celery(
    'tenders',
    broker='filesystem://',
    backend='file://./results',
    include=['celery_tasks']
)

celery_app.conf.update(
    broker_transport_options={
        'data_folder_in': './broker/out',
        'data_folder_out': './broker/out',
        'data_folder_processed': './broker/processed'
    },
    result_persistent=True,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json']
)
