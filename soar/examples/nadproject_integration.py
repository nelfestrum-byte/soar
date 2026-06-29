"""
Примеры интеграции SOAR модуля с надпроектом.
"""
import atexit
from soar import setup_logging, connectors, actions, workflows


def init():
    setup_logging(level="INFO", log_file="/var/log/soar/soar.log")
    connectors.init()
    actions.init()
    workflows.init()


def list_workflows():
    for wf in workflows.list():
        print(wf)


def run_scheduled():
    result = workflows.execute("MyAlertCheck", context={})
    print(f"Success: {result.success}, data: {result.data}")


def handle_webhook(payload: dict):
    context = {"payload": payload}
    result = workflows.execute("SIEMAlert", context=context)
    return {"status": "ok" if result.success else "error"}


def run_manual():
    result = workflows.execute("InvestigateHost", context={"ip": "8.8.8.8"})
    print(f"Result: {result.data}")


if __name__ == "__main__":
    init()
    atexit.register(connectors.shutdown)

    list_workflows()
    run_scheduled()
    run_manual()
