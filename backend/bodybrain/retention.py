"""Preview or prune old completed local task/activity history, never source records."""
from datetime import datetime, timedelta, timezone
import json


def prune_history(store, days: int, apply: bool = False) -> dict:
    if not 1 <= days <= 3650:
        raise ValueError('Choose between 1 and 3650 days')
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with store.connect() as db:
        protected = {r[0] for r in db.execute('SELECT id FROM relay_jobs')}
        tasks = []
        for task_id, serialized in db.execute('SELECT id, data FROM tasks'):
            task = json.loads(serialized)
            if task_id not in protected and task.get('status') in {'completed', 'failed'} and task.get('created_at', '9999') < cutoff:
                tasks.append(task_id)
        runs = []
        for run_id, serialized in db.execute('SELECT id, data FROM runs'):
            run = json.loads(serialized)
            if run.get('task_id') not in protected and run.get('status') in {'completed', 'failed', 'interrupted'} and run.get('created_at', '9999') < cutoff:
                runs.append(run_id)
        if apply:
            db.executemany('DELETE FROM tasks WHERE id=?', [(i,) for i in tasks])
            db.executemany('DELETE FROM runs WHERE id=?', [(i,) for i in runs])
    return {'applied': apply, 'older_than_days': days, 'tasks': len(tasks), 'activity_entries': len(runs), 'records_deleted': 0}
