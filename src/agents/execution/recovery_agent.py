import time

from src.core.active_game import active_package
from src.core.config import MAX_RECOVERY_ATTEMPTS, SAME_SCENE_RECOVERY_THRESHOLD
from src.device.device import launch_game, run_adb, tap


class RecoveryAgent:
    def __init__(self, executor):
        self.executor = executor

    def should_recover(self, memory):
        return memory.same_scene_count >= SAME_SCENE_RECOVERY_THRESHOLD

    def recover(self, state, memory):
        print("\n🛟 Recovery Agent invoked")
        scene = state.get("scene", "unknown")

        if scene == "loading":
            print("   Loading screen — waiting it out")
            time.sleep(5)
            return

        modal = state.get("blocking_modal", {})
        if modal.get("present") and modal.get("buttons"):
            btn = modal["buttons"][0]
            print(f"   Closing dialog: {btn.get('label')}")
            tap(btn["x"], btn["y"])
            memory.same_scene_count = 0
            return

        if scene == "dialog" and self.executor.tap_target(state, "OK"):
            memory.same_scene_count = 0
            return

        memory.recovery_attempts += 1
        if memory.recovery_attempts > MAX_RECOVERY_ATTEMPTS:
            print("   ⚠ Max recovery attempts exceeded — restarting app")
            run_adb(["shell", "am", "force-stop", active_package()])
            time.sleep(2)
            launch_game()
            memory.recovery_attempts = 0
        else:
            print(f"   No clear recovery path — nudging app (attempt {memory.recovery_attempts})")
            run_adb(["shell", "monkey", "-p", active_package(), "1"])

        memory.same_scene_count = 0
        time.sleep(5)
