# Server / Worker deployment profile

OpenDub Studio now supports a durable SQLite queue with independent worker processes.

## Local mode

start.bat starts the FastAPI app. The app starts one embedded worker by default, so existing local workflows keep working.

To run the worker separately instead, set OPENDUB_EMBED_WORKER=0 and start:

python -m backend.worker

The worker claims queued media/render jobs with a SQLite lease, sends heartbeats, and re-queues stale leases.

## Multi-worker / server mode

Run the API with:

uvicorn backend.app:app --host 0.0.0.0 --port 7860

Run one or more worker processes separately:

python -m backend.worker --worker-id gpu-01

All API and workers must point at the same persistent OPENDUB_DATA_DIR. The current storage implementation is filesystem-based, so a shared persistent volume is required when API and workers run on different machines.

## Docker

The repository includes Dockerfile and docker-compose.server.yml. The default compose profile uses one API container, one worker container, a shared persistent runtime volume, and FFmpeg installed in the image.

For GPU workers, build the image with the required GPU runtime and install the optional AI/model dependencies inside the worker image. The queue layer does not assume a specific GPU vendor.

## Remote storage

Project paths are rooted under OPENDUB_DATA_DIR, which makes persistent disks or a mounted network filesystem the current server storage contract.

Object-storage support (S3/GCS/Azure) is not enabled in this phase because source/video artifacts, random-access intermediate files, and SQLite require shared-filesystem semantics for the current pipeline. A future remote-storage adapter can sit behind the same project-root contract without changing the browser API.

## Job reliability

Workers use atomic SQLite claiming, per-job lease timestamps, worker heartbeat records, automatic stale-job recovery, and a configurable retry count via OPENDUB_MAX_JOB_ATTEMPTS.

This is durable queueing and restart recovery, not distributed transaction processing. A worker crash during FFmpeg/model execution causes that job to be retried from the stage boundary.
