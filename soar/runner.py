import json
import os
import sys

from soar.actions import actions
from soar.connectors import connectors
from soar.logger import setup_logging
from soar.workflows import workflows

setup_logging(level="INFO")
workflows.init()
connectors.init()
actions.init()


def main():
    os.environ.get("SOAR_JOB_ID", "")
    workflow_name = os.environ.get("SOAR_WORKFLOW_NAME", "")
    context_str = os.environ.get("SOAR_CONTEXT", "{}")
    os.environ.get("SOAR_LOG_PATH", "")

    try:
        context = json.loads(context_str)
    except json.JSONDecodeError:
        context = {}

    result = workflows.execute(workflow_name, context)

    output = {
        "success": result.success,
        "workflow_name": result.workflow_name,
        "duration_seconds": result.duration_seconds,
        "data": result.data,
    }
    if result.error:
        output["error"] = str(result.error)

    print(json.dumps(output))

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
