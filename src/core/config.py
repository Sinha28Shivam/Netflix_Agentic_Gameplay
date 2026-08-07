import os
import shutil

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("WARNING: python-dotenv not installed (pip install -r requirements.txt) "
          "-- .env will not be loaded; falling back to real environment variables.")


def _resolve_adb_path() -> str:
    """
    Resolve adb from the environment first, then PATH, then common SDK dirs.
    This keeps the repo portable across different Windows user profiles.
    """
    raw_env = os.environ.get("ADB_PATH", "").strip().strip('"')
    if raw_env:
        env_path = os.path.abspath(os.path.expanduser(os.path.expandvars(raw_env)))
        if os.path.isfile(env_path):
            return env_path

    which_adb = shutil.which("adb")
    if which_adb:
        return os.path.abspath(which_adb)

    sdk_roots = [
        os.environ.get("ANDROID_SDK_ROOT", ""),
        os.environ.get("ANDROID_HOME", ""),
        r"C:\Program Files\platform-tools",
        r"C:\Program Files (x86)\platform-tools",
    ]
    for root in sdk_roots:
        if not root:
            continue
        adb_path = os.path.join(os.path.expanduser(os.path.expandvars(root)), "adb.exe")
        if os.path.isfile(adb_path):
            return os.path.abspath(adb_path)

    # Keep env override if one was provided, even if it is currently invalid,
    # so downstream error messages point to the path the user set explicitly.
    if raw_env:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(raw_env)))

    return "adb"

# ============================================================
# DEVICE / GAME CONFIG
# ============================================================
ADB_PATH = _resolve_adb_path()
DEVICE_SERIAL = os.environ.get("DEVICE_SERIAL", "")  # blank = use only connected device

GAME_PACKAGE = os.environ.get("GAME_PACKAGE", "com.netflix.NGP.BloonsTDSix")
GAME_ACTIVITY = os.environ.get("GAME_ACTIVITY", "")

# Which registered game plugin is active. Resolved once by src/core/active_game.py
# (mirrors how EXECUTION_MODE selects a device backend). Set via --game or GAME_ID.
GAME_ID = os.environ.get("GAME_ID", "bloons_td6")

# ============================================================
# DEVICE BACKEND (ADB vs Appium) — see REINFORCEMENT_LEARNING.md / migration plan
# ============================================================
# All device I/O is routed through src/device/device.py. EXECUTION_MODE picks
# the backend at import time; default "adb" keeps the original behaviour with
# zero change. Set EXECUTION_MODE=appium to drive the device through Appium
# (requires a running Appium server + Appium-Python-Client installed).
EXECUTION_MODE      = os.environ.get("EXECUTION_MODE", "adb").strip().lower()
APPIUM_SERVER_URL   = os.environ.get("APPIUM_SERVER_URL", "http://127.0.0.1:4723")
APPIUM_PLATFORM_NAME = os.environ.get("APPIUM_PLATFORM_NAME", "Android")

# Real-time capture/input backend for reflex games (see src/device/fast_io.py).
# auto = scrcpy if installed else adb fallback; scrcpy = require scrcpy; adb = slow.
FAST_IO_BACKEND = os.environ.get("FAST_IO_BACKEND", "auto").strip().lower()

# ============================================================
# LLM / VLM CONFIG
# Uses Anthropic's Claude API directly (native Messages API via the
# `anthropic` SDK, not an OpenAI-compatible shim).
# ============================================================
# Leave LLM_BASE_URL empty to use Anthropic's default endpoint. Only set it
# if you're routing through Bedrock/Vertex/a proxy instead -- and if you do,
# use the bare domain (e.g. "https://api.anthropic.com"), NOT including
# "/v1". The anthropic SDK appends "/v1/messages" itself; including "/v1"
# here doubles it into ".../v1/v1/messages", which 404s on every call.

LLM_BASE_URL  = os.environ.get("LLM_BASE_URL",  "https://api.anthropic.com/v1")
LLM_API_KEY   = os.environ.get("LLM_API_KEY",   "")  # set in .env or the environment -- never hardcode a real key here
VISION_MODEL  = os.environ.get("VISION_MODEL",  "claude-opus-4-8")
DECIDER_MODEL = os.environ.get("DECIDER_MODEL", VISION_MODEL)


# Legacy alias used by original agents
QWEN_MODEL = VISION_MODEL

# ============================================================
# SEED / DATA FILES
# ============================================================
SEED_FILE  = os.environ.get("SEED_FILE",  "data/seeds/bloons_seed.json")
SPECS_FILE = os.environ.get("SPECS_FILE", "data/seeds/specs.json")

# ============================================================
# MISSION CONFIG (Gameplay)
# ============================================================
MISSION = {
    "game":         "Bloons TD 6",
    "map":          "Monkey Meadow",
    "difficulty":   "Easy",
    "mode":         "Standard",
    "target_round": 10,
}

# ============================================================
# GAMEPLAY CONSTANTS (used by executor_agent / run_one_game)
# ============================================================
PLAY_MINUTES  = int(os.environ.get("PLAY_MINUTES",  "10"))
DART_COST     = int(os.environ.get("DART_COST",     "170"))   # Dart Monkey on Easy
CASH_RESERVE  = int(os.environ.get("CASH_RESERVE",  "150"))   # never spend below this
MAX_MONKEYS   = int(os.environ.get("MAX_MONKEYS",   "12"))

# ============================================================
# LOOP / RECOVERY CONFIG
# ============================================================
SAME_SCENE_RECOVERY_THRESHOLD = 5
MAX_RECOVERY_ATTEMPTS         = 3
LOOP_SLEEP_SECONDS            = 2

# ============================================================
# REINFORCEMENT LEARNING (see REINFORCEMENT_LEARNING.md)
# ============================================================
# When USE_RL_POLICY is truthy AND a trained Q-table exists, the decision loop
# routes through RLDecisionAgent (a policy learned offline from the MapStore
# graph) instead of the LLM DecisionAgent. Off by default -> no change to the
# production pipeline unless explicitly enabled.
USE_RL_POLICY   = os.environ.get("USE_RL_POLICY", "").strip().lower() in ("1", "true", "yes", "on")
RL_POLICY_FILE  = os.environ.get("RL_POLICY_FILE", "")  # blank -> outputs/rl/<game>_qtable.json
RL_GOAL_SCENE   = os.environ.get("RL_GOAL_SCENE", "in_game")

# ============================================================
# PERFORMANCE THRESHOLDS
# ============================================================
MIN_ACCEPTABLE_FPS        = 30
MAX_ACCEPTABLE_MEMORY_MB  = 1024
MAX_ACCEPTABLE_LOAD_SECONDS = 8.0

# ============================================================
# COMPLIANCE CONFIG
# ============================================================
MIN_TAP_TARGET_PX       = 48     # advisory
MIN_TEXT_CONTRAST_RATIO = 4.5    # WCAG AA, advisory

# ============================================================
# OUTPUT
# ============================================================
REPORT_DIR = os.environ.get("REPORT_DIR", "outputs/reports")
MAPS_DIR   = os.environ.get("MAPS_DIR",   "data/maps")
PLANS_DIR  = os.environ.get("PLANS_DIR",  "data/plans")
LOG_DIR    = os.environ.get("LOG_DIR",    "outputs/logs")
