"""Free read-only example; requires a task already owned by your API Key."""

import argparse

from suno_crewai import SunoRetrieveTaskTool

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("task_id")
args = parser.parse_args()
print(SunoRetrieveTaskTool().run(task_id=args.task_id, wait_seconds=0))
