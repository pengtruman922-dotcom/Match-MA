from backend.app.jobs.queue import JobClaim


def execute_job(job: JobClaim) -> dict[str, object]:
    """First worker version only proves queue mechanics; real handlers come next."""
    return {
        "handled": False,
        "job_type": job.job_type,
        "message": "No real job handler is implemented yet.",
    }
