# 06 — Reinforcement Learning (RL) Engine Architecture

This document details the Reinforcement Learning subsystem in **NetflixGameTestHCL**, covering environment wrappers, Markov Decision Process (MDP) formulation, tabular Q-Learning algorithms, reward shaping, decision agent integration, and training loops.

![Reinforcement Learning Architecture Diagram](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/images/06_reinforcement_learning.png)

---

## 1. Subsystem Architecture

The RL engine provides autonomous navigation and decision-making capabilities without relying on static hardcoded scripts. It supports both offline policy training (simulated MDP graph environment) and live on-device policy evaluation.

```
       +-------------------------------------------------------------+
       |                     RL Subsystem Architecture                |
       +-------------------------------------------------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
        +---------------------+                 +---------------------+
        |  Offline Simulation |                 |  Live Device Env    |
        |     (QANavEnv)      |                 |   (LiveDeviceEnv)   |
        +---------------------+                 +---------------------+
                   |                                       |
                   +-------------------+-------------------+
                                       |
                                       v
                        +----------------------------+
                        |      Q-Learning Agent      |
                        |      (QLearningAgent)      |
                        +----------------------------+
                                       |
                                       v
                        +----------------------------+
                        |   q_table_<game>.json      |
                        +----------------------------+
```

---

## 2. Environment Wrappers (`src/rl/env.py`)

### 2.1 QANavEnv (Offline Environment)
- **Contract**: Gymnasium-style interface (`reset(seed)`, `step(action_index)`).
- **Features**: Fully offline, deterministic simulation of UI graph transitions without requiring device connections or LLM API calls. Executes in milliseconds.

### 2.2 LiveDeviceEnv (On-Device Environment)
- **Contract**: Identical step/reset interface, backed by physical devices and vision processing.
- **Workflow**:
  - `observation`: Captured via `VisionAgent.observe()` & OCR scene classification.
  - `action`: Dispatched to `ExecutorAgent`.
  - `reset`: Triggers device `force_stop()` and `launch_game()`.

---

## 3. MDP Formulation (`src/rl/mdp.py`)

- **State Space ($S$)**: Discrete set of UI screens/scenes (e.g. `title`, `age_gate`, `main_menu`, `difficulty_select`, `in_game`, `defeat`, `victory`).
- **Action Space ($A$)**: Normalized discrete UI interactions (e.g. `tap_play`, `tap_difficulty_medium`, `tap_start_match`, `dismiss_popup`).
- **Transition Dynamics ($P(s' | s, a)$)**: Probability table mapping (state, action) pairs to next states, accommodating non-deterministic system lag or random popup dialogs.

---

## 4. Q-Learning Algorithm (`src/rl/qlearning.py`)

Implements tabular Q-learning with $\epsilon$-greedy exploration:

### Update Equation
$$Q(s, a) \leftarrow Q(s, a) + \alpha \left[ r + \gamma \max_{a'} Q(s', a') - Q(s, a) \right]$$

- **Hyperparameters**:
  - Learning Rate ($\alpha$): `0.1`
  - Discount Factor ($\gamma$): `0.95`
  - Exploration Rate ($\epsilon$): Decays from `1.0` to `0.05` over training episodes.
- **Persistence**: Saves trained Q-tables to `outputs/results/q_table_<game_id>.json`.

---

## 5. Reward Shaping (`src/rl/reward.py`)

Calculates step rewards to guide policy convergence:
- **Goal Reached (`+100.0`)**: Reaching target goal scene (e.g., entering `in_game` or achieving `victory`).
- **Step Penalty (`-1.0`)**: Encourages shortest-path navigation trajectories.
- **Invalid Action / Loop Penalty (`-5.0`)**: Penalizes repetitive taps on unresponsive screen elements.
- **Defeat State (`-50.0`)**: Penalizes losing the match during gameplay evaluation.

---

## 6. Decision Integration & Training (`src/rl/rl_decision_agent.py` & `src/rl/train.py`)

- **`RLDecisionAgent`**: Plugs trained Q-table policies directly into the `DecisionAgent` action selection pipeline. When high confidence exists in the Q-table, it executes optimal actions directly; otherwise, it falls back to VLM reasoning.
- **`train.py`**: Command-line trainer script (`python -m src.rl.train`) executing episodic offline training loops to pre-converge navigation Q-tables.
