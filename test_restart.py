"""Test worker restart - scheduled jobs should persist."""
from app import create_app
from app.models import Lead, ScheduledJob
from app.extensions import db
from app.services.jobs import get_due_jobs

app = create_app()
ctx = app.app_context()
ctx.push()

# Check scheduled jobs before "restart"
print("=== Before Restart ===")
jobs = db.session.query(ScheduledJob).filter(ScheduledJob.status == "pending").all()
print(f"Pending jobs: {len(jobs)}")
for job in jobs:
    print(f"  Job {job.id}: lead={job.lead_id}, type={job.job_type}, scheduled={job.scheduled_at_utc}")

# Simulate app restart by creating new app context
ctx.pop()
print("\n=== Simulating App Restart ===")

# Create new app context (simulating restart)
app2 = create_app()
ctx2 = app2.app_context()
ctx2.push()

print("\n=== After Restart ===")
jobs = db.session.query(ScheduledJob).filter(ScheduledJob.status == "pending").all()
print(f"Pending jobs: {len(jobs)}")
for job in jobs:
    print(f"  Job {job.id}: lead={job.lead_id}, type={job.job_type}, scheduled={job.scheduled_at_utc}")

# Test get_due_jobs
from app.services.jobs import get_due_jobs
due = get_due_jobs(limit=10)
print(f"\nDue jobs (should be 0 since they're in future): {len(due)}")

ctx2.pop()