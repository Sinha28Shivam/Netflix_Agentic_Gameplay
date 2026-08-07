# Reinforcement Learning in the Netflix Game QA Pipeline

**Status: implemented (navigation) + roadmap (in-match combat).**
This document is both the feasibility answer and the spec for the RL layer that
now ships under [`src/rl/`](src/rl/). It is written to be executed from, not just
read.

---

## 1. Executive summary & feasibility verdict

**Is it possible to implement Reinforcement Learning here? Yes — and it is now
implemented for the navigation problem, with a clear roadmap for in-match play.**

The pipeline already contains every structural piece of a Markov Decision
Process (MDP); it was simply wired for VLM prompting instead of learning. The
decisive enabler is the **MapStore** ([`src/models/map_store.py`](src/models/map_store.py)):
a persisted graph of `screen --action--> screen` transitions with visit counts.
That graph **is** a tabular MDP model, which means a navigation policy can be
trained **entirely offline** — no device, no LLM, no API cost — and then
deployed on a real device as a drop-in replacement for the (currently unwired)
`DecisionAgent`.

The scope splits cleanly into two problems:

| Problem | Difficulty | Status |
|---|---|---|
| **Menu navigation** (title → in_game) | Small, discrete, fully-observed | **Shipped** — tabular Q-learning, trained offline, unit-tested |
| **In-match combat** (tower placement/upgrades to survive rounds) | Large, noisy, slow feedback | **Roadmap** — reward function shipped; needs live training + function approximation |

What ships today learns the optimal navigation policy from the real committed
map and reaches the `in_game` screen in a mean of **5.33 taps** — identical to
the exact value-iteration optimum — with a **99.9% success rate**, trained in a
fraction of a second. See [§8](#8-training--deployment-workflow) to run it.

---

## 2. Why RL fits this codebase

Every MDP element already exists as a concrete hook:

| MDP element | Existing hook | Location |
|---|---|---|
| Observation / state | `VisionAgent.observe()` → `{scene, resources{cash,lives,round}, actionable_elements, confidence}` | [`src/agents/core/vision_agent.py`](src/agents/core/vision_agent.py) (schema lines 12–21) |
| Low-level state | `read_hud()` (cash/round), `solidly_in_match()` | [`src/core/qa_common.py`](src/core/qa_common.py) |
| Discrete action space | `tap(target)`, `wait`, `swipe_{left,right,up,down}`, `done` | [`src/agents/core/decision_agent.py`](src/agents/core/decision_agent.py) (prompt lines 13–20) |
| Policy interface | `DecisionAgent.decide(state, memory)` — LLM-backed, **not on the production path** | [`src/agents/core/decision_agent.py`](src/agents/core/decision_agent.py) |
| Action execution | `ExecutorAgent.execute(decision, state)` → bool | [`src/agents/execution/executor_agent.py`](src/agents/execution/executor_agent.py) |
| **Transition model** | `MapStore` graph: `node(screen) --edge(action)--> node`, with `seen_count` + `is_terminal` | [`src/models/map_store.py`](src/models/map_store.py), [`data/maps/bloons_td6.json`](data/maps/bloons_td6.json) |
| Terminal reward | `OracleAgent.verify(state)` → victory/defeat/target_round | [`src/agents/core/oracle_agent.py`](src/agents/core/oracle_agent.py) |
| Dense reward | round advance, cash delta, `same_scene_count` stuck penalty | executor / [`src/core/memory.py`](src/core/memory.py) |
| Reset primitives | `force_stop()` / `launch_game()` | [`src/device/android/adb_utils.py`](src/device/android/adb_utils.py) |

### The two control paths — and where RL plugs in

The codebase has **two** control paths, and this distinction is why the RL
insertion is low-risk:

- **Path A — the per-step decision loop** (`VisionAgent → DecisionAgent →
  ExecutorAgent → OracleAgent`). These four agents exist and are LLM-wired, but
  the loop that ties them together is **not** what runs in production. This is
  the natural, regression-free RL insertion point.
- **Path B — the production orchestrator** ([`src/core/orchestrator.py`](src/core/orchestrator.py))
  drives the game with scripted `navigate()` / `play()` routines. This is what
  `main.py` actually runs.

Because `DecisionAgent.decide()` is not on Path B, swapping in a learned policy
adds a real RL controller **without changing the running pipeline's default
behaviour**. The RL policy is opt-in via `USE_RL_POLICY` ([§7](#7-integration-points)).

---

## 3. MDP formulation

### 3.1 State space

**Navigation (shipped).** A state is a *logical screen*, taken from the MapStore
node `label`. The raw graph stores ~40 hash-suffixed ids (`menu_41956de1`,
`menu_b656b781`, …) for the same logical screen, so [`NavigationMDP`](src/rl/mdp.py)
**collapses nodes by label**. For `bloons_td6` this yields exactly 5 states:

```
['difficulty_select', 'home', 'in_game', 'menu', 'title']
```

The observation source at deploy time is `VisionAgent.observe()`'s `scene`
field, bridged to a state label by `SCENE_TO_STATE_ALIASES` in
[`src/rl/rl_decision_agent.py`](src/rl/rl_decision_agent.py) (e.g. `main_menu → menu`,
`difficulty_selection → difficulty_select`).

**In-match (roadmap).** The combat state is not a single screen; it is
continuous and partially observed. The proposed discretization is a tuple of
coarse buckets read from `read_hud()`:

```
s = (round_bucket, cash_bucket, lives_bucket, towers_placed_bucket)
```

with, e.g., `round ∈ {1–5, 6–10, 11+}`, `cash ∈ {<DART_COST, DART_COST–2×, 2×+}`,
`lives ∈ {full, hurt, critical}`. This keeps the table small enough for tabular
methods initially and defines the observation for later function approximation.

### 3.2 Action space

The discrete action vocabulary is the `DecisionAgent` shape. For the navigation
MDP it is the set of `(action_type, target)` pairs observed as graph edges;
targets are **normalized** to fold OCR noise (`normalize_target("STAnDARD") ==
"STANDARD"`). For `bloons_td6`:

```
['tap EASY', 'tap MONKEY MEADOW', 'tap PLAY', 'tap STANDARD', 'tap START']
```

A policy action is emitted verbatim in `DecisionAgent` JSON so it drops onto the
existing executor:

```json
{"action": "tap", "target": "Monkey Meadow", "why": "RL optimal policy from state 'menu'"}
```

The full vocabulary (`wait`, `swipe_{left,right,up,down}`, `done`) is preserved
for the deployed agent; `done` is emitted automatically on reaching the goal.

### 3.3 Transition dynamics

`T(s' | s, a)` is estimated from the graph by normalizing edge `seen_count`s per
`(from_label, action)`. Crucially, **the recorded dynamics are genuinely
stochastic** — this is a real MDP, not a deterministic path lookup. Example from
the committed `bloons_td6` map:

```
menu --tap MONKEY MEADOW--> difficulty_select   (count 6  →  p ≈ 0.43)
menu --tap MONKEY MEADOW--> menu                 (count 8  →  p ≈ 0.57)   # self-loop
difficulty_select --tap STANDARD--> in_game      (count 5  →  p = 1.0)
```

An `(s, a)` pair with no observed edge is defined as a self-loop with the step
cost, keeping the MDP complete and well-defined for value iteration. This is why
a *learned* policy beats a naive script: the optimal behaviour is "keep tapping
MONKEY MEADOW until the (probabilistic) transition to `difficulty_select`
fires" — the agent discovers the retry policy on its own.

### 3.4 Reward function (exhaustive)

All constants live in [`src/rl/reward.py`](src/rl/reward.py) and
[`src/core/config.py`](src/core/config.py).

**Navigation reward** (`NavigationReward`, and baked into `NavigationMDP.P`):

| Event | Reward | Rationale |
|---|---|---|
| Transition into goal screen (`in_game`) | `+GOAL_REWARD` (= 1.0), terminal | Sparse task-completion signal |
| Any transition | `−STEP_COST` (= 0.01) | Shortest-path pressure (fewer taps) |

**In-match reward** (`GameplayReward`, roadmap Phase 2):

| Component | Source | Sign / shaping |
|---|---|---|
| Victory | `OracleAgent.verify` → `PASS` | `+1.0` terminal |
| Defeat | `OracleAgent.verify` → `FAIL` | `−1.0` terminal |
| Round advanced | `read_hud` round delta (`r1 > r0`) | `+0.20 × Δround` |
| Tower placed | `read_hud` cash delta (`cash1 < cash0`) | `+0.05` (verified spend) |
| Screen made progress | `screen_signature` changed | `+0.01` |
| Stuck | `memory.same_scene_count ≥ SAME_SCENE_RECOVERY_THRESHOLD` (5) | `−0.10` |
| Low FPS | perf `< MIN_ACCEPTABLE_FPS` (30) | `−0.10` |
| Over memory budget | perf `> MAX_ACCEPTABLE_MEMORY_MB` (1024) | `−0.10` |
| Per-step time cost | every step | `−STEP_COST` |

Compliance/performance specs in [`data/seeds/specs.json`](data/seeds/specs.json)
(splash ≥ 2000 ms, fps ≥ 30, no crash over 600 s, cash decreases on placement,
round counter increases) are machine-checkable predicates and become additional
terminal reward terms for QA-objective-directed training.

### 3.5 Episode, reset, termination

- **Reset**: offline — start at the inferred entry screen (`title`); on-device —
  `force_stop()` + `launch_game()` ([`LiveDeviceEnv.reset`](src/rl/env.py)).
- **Termination** (`terminated`): reaching the goal screen (navigation) or a
  victory/defeat verdict (combat).
- **Truncation** (`truncated`): `max_steps` reached without termination
  (default 50 offline / 40 on-device) — bounds runaway episodes.

---

## 4. Algorithm choice & rationale

**Shipped: tabular Q-learning** (off-policy TD control), with **value iteration**
as an exact model-based baseline.

- **Q-learning** ([`src/rl/qlearning.py`](src/rl/qlearning.py)) learns purely from
  sampled experience against the environment — it does not need the transition
  model, so the identical agent transfers to the live device where the model is
  unknown.
- **Value iteration** exploits the fact that `NavigationMDP` exposes the full `P`,
  giving the provably-optimal policy. It is the ground truth the tests assert
  against (the learned policy must match it — zero regret).

**Why not deep RL (DQN/PPO) yet?** Three practical constraints:

1. **No ML runtime installed** — `requirements.txt` has no torch/tf/gym/sb3.
   The tabular agent runs on the **stdlib alone** (numpy optional), so it works
   in this environment today.
2. **Step latency** — every ADB primitive sleeps 0.5–1.2 s and OCR ≈ 25 s/call.
   Deep RL needs 10⁴–10⁶ live steps; at seconds-per-step that is infeasible for
   on-device training now.
3. **Reward noise** — HUD reward comes from best-effort OCR. Tabular methods on
   a compact, model-backed state space are far more sample-efficient and robust
   here.

Deep RL (DQN with the §3.1 in-match state, or PPO) is the right tool **once**
combat training moves to an emulator farm or a faster instrumented reward
channel — see [§11](#11-roadmap).

---

## 5. Architecture of the shipped code

```
                 offline (no device, no LLM, no API cost)
 data/maps/<game>.json ──► NavigationMDP ──► QANavEnv ──► QLearningAgent.train
 (MapStore graph)          (mdp.py)          (env.py)      (qlearning.py)
                                │                              │
                                │ value_iteration (baseline)   ▼
                                └───────────► compare ◄── outputs/rl/<game>_qtable.json
                                                                │
 ───────────────────────────────────────────────────────────  │ deploy
                 on-device (real ADB + VisionAgent)             ▼
 VisionAgent.observe ──► scene ──► RLDecisionAgent.decide ──► DecisionAgent JSON
 (existing perception)             (rl_decision_agent.py)          │
                                                                   ▼
                                              ExecutorAgent.execute (existing)
```

Module map ([`src/rl/`](src/rl/)):

| Module | Responsibility |
|---|---|
| [`mdp.py`](src/rl/mdp.py) | `NavigationMDP` — build states/actions/`P`/reward from a MapStore graph; label collapsing; target normalization; emit `DecisionAgent` JSON |
| [`reward.py`](src/rl/reward.py) | `NavigationReward`, `GameplayReward` — the reward tables of §3.4, single source of truth |
| [`env.py`](src/rl/env.py) | `QANavEnv` (offline, Gymnasium-style) + `LiveDeviceEnv` (real device, reuses existing agents) |
| [`qlearning.py`](src/rl/qlearning.py) | `QLearningAgent` (train/act/save/load) + `value_iteration` + `expected_steps_to_goal` |
| [`rl_decision_agent.py`](src/rl/rl_decision_agent.py) | `RLDecisionAgent` — `DecisionAgent`-compatible policy backed by a trained Q-table, with LLM fallback |
| [`train.py`](src/rl/train.py) | CLI: build → train → compare to VI → save Q-table |

We implement the Gymnasium `reset`/`step` contract by hand rather than depend on
the `gymnasium` package (not installed), keeping the layer dependency-light.

---

## 6. Pseudocode & hyperparameters

**Q-learning update** (per step), as in `QLearningAgent.train`:

```
for each episode:
    s ← env.reset()
    repeat until terminated or truncated:
        a ← argmax_a Q[s,a]   with prob 1−ε,   else random     # ε-greedy
        s', r, done ← env.step(a)
        Q[s,a] ← Q[s,a] + α · (r + γ · max_a' Q[s',a'] − Q[s,a])
        s ← s'
    ε ← max(ε_end, ε · ε_decay)
```

**Default hyperparameters** (starting points; tune per game/map size):

| Symbol | Value | Meaning |
|---|---|---|
| `α` (alpha) | 0.5 | Learning rate |
| `γ` (gamma) | 0.95 | Discount — favours short paths without ignoring the goal |
| `ε_start → ε_end` | 1.0 → 0.02 | Exploration, annealed |
| `ε_decay` | 0.995 | Per-episode multiplicative decay |
| `episodes` | 5000 | Ample for a 5-state MDP; scale with `|S|·|A|` |
| `GOAL_REWARD` | 1.0 | Terminal task-completion reward |
| `STEP_COST` | 0.01 | Per-step penalty |
| `max_steps` | 50 | Episode truncation bound |

Ties in `argmax` are broken randomly (seeded) so the policy does not bias toward
low action indices.

---

## 7. Integration points

- **Config flags** ([`src/core/config.py`](src/core/config.py)):
  - `USE_RL_POLICY` (env `USE_RL_POLICY=1`) — route the decision loop through RL.
  - `RL_POLICY_FILE` — override the Q-table path (default `outputs/rl/<game>_qtable.json`).
  - `RL_GOAL_SCENE` (default `in_game`) — the goal screen label.
- **Policy factory** (`make_decision_policy(client, game_id)` in
  [`src/agents/core/decision_agent.py`](src/agents/core/decision_agent.py)):
  returns an `RLDecisionAgent` (with the LLM `DecisionAgent` as its off-policy
  **fallback** — a hybrid learned+LLM controller) when `USE_RL_POLICY` is set and
  a Q-table exists, otherwise the plain `DecisionAgent`. Both share the
  `decide(state, memory)` contract, so callers are unchanged.
- **On-device demo**: [`scripts/rl_navigate.py`](scripts/rl_navigate.py) mirrors
  `scripts/run_plan.py`'s wiring but drives the device from the trained policy.

Default behaviour is unchanged: with `USE_RL_POLICY` unset, the pipeline runs
exactly as before.

---

## 8. Training & deployment workflow

```bash
# 1. Train offline from the committed map — NO device, NO LLM, NO API key.
python -m src.rl.train --game bloons_td6 --episodes 5000
#    → prints the learned path + value-iteration optimum, writes
#      outputs/rl/bloons_td6_qtable.json

# 2. (optional) Enable the RL policy in the live decision loop.
export USE_RL_POLICY=1            # Windows: $env:USE_RL_POLICY = "1"

# 3. (optional, needs a device) Drive real navigation with the trained policy.
python scripts/rl_navigate.py --game bloons_td6
```

Observed training output on the committed map:

```
MDP: NavigationMDP(states=5, actions=5, start='title', goal='in_game')
Value iteration (optimal):  mean taps : 5.33
Q-learning (5000 episodes): success_rate : 0.999   mean taps : 5.33
  vs value iteration : MATCHES optimal [OK]
```

The **offline→online transfer story**: the Q-table is learned against the graph
model, then loaded on-device where `RLDecisionAgent` maps the live `VisionAgent`
scene to a state and looks up the greedy action. Because both use the same state
labels and action JSON, no retraining is needed to deploy; on-device episodes
can later *fine-tune* the same table (Phase 3).

---

## 9. Evaluation metrics

| Metric | Definition | Where |
|---|---|---|
| Success rate | Fraction of training episodes that reach the goal | `train()` summary |
| Path length (mean taps) | Monte-Carlo mean steps to goal under the greedy policy | `expected_steps_to_goal()` |
| Regret vs optimal | `path_length(π_learned) − path_length(π_value_iteration)` | test asserts ≈ 0 |
| Sample efficiency | Episodes to reach a success-rate threshold | `episode_returns` history |
| On-device transfer | Steps to goal on a real device vs offline estimate | `scripts/rl_navigate.py` |

---

## 10. Limitations & risks

| Risk | Impact | Mitigation |
|---|---|---|
| **State aliasing** | Many hash-suffixed nodes per logical screen | Collapse by `label` (done); revisit if two logical screens share a label |
| **OCR reward noise/latency** | Combat reward is slow (~25 s/OCR) and best-effort | Navigation reward avoids OCR entirely; combat needs a faster reward channel before scaling |
| **Live-device exploration cost** | Seconds/step makes on-device exploration expensive | Train offline on the graph model; use the device only for eval/fine-tune |
| **Map coverage bias** | Policy is only as good as the recorded graph | The existing "Learning Loop" (`orchestrator._relearn_on_gaps`) extends the map; retrain after re-map |
| **Non-stationarity** | Game updates change screens/dynamics | Re-map + retrain per game version; Q-table is a cheap artifact |
| **Reward hacking** | Agent games a proxy (e.g. self-loops for step reward) | Step cost is negative, goal reward is sparse+positive → no incentive to loop; verified by the zero-regret test |
| **Broken repo `.venv`** | Existing `.venv` is a uv shim pointing at a missing interpreter | Use a real interpreter (see below); documented, not silently assumed |

---

## 11. Roadmap

- **Phase 1 — Navigation (done).** Tabular Q-learning over the MapStore graph;
  offline-trained, unit-tested, deployable as `RLDecisionAgent`.
- **Phase 2 — In-match reward wiring.** `GameplayReward` (shipped) driving a
  tabular policy over the §3.1 discretized combat state, trained via
  `LiveDeviceEnv` on a small number of real episodes (or an emulator).
- **Phase 3 — Function approximation.** Replace the table with a small network
  (DQN) once a faster reward channel / emulator farm removes the latency ceiling;
  optionally online fine-tuning of the navigation policy from device episodes.
- **Phase 4 — Curriculum & transfer.** Curriculum over maps/difficulties;
  multi-game transfer by sharing the action vocabulary and warm-starting the
  Q-table from a related game's map.

---

## 12. How to run (quick reference)

```bash
# Train (offline)
python -m src.rl.train --game bloons_td6 --episodes 5000

# Test the RL layer (offline; no device, no LLM)
python -m pytest tests/test_rl.py -v      # 10 tests, ~0.3 s

# Inspect a decision programmatically
python -c "from src.rl.rl_decision_agent import RLDecisionAgent; \
           rl=RLDecisionAgent.from_files('bloons_td6'); \
           print(rl.decide({'scene':'menu'}, None))"

# Drive a live device (needs ADB + game + LLM client)
USE_RL_POLICY=1 python scripts/rl_navigate.py --game bloons_td6
```

> **Interpreter note.** The repo's `.venv` is a broken uv shim (it points at a
> different user's interpreter, `C:\Users\v-moanis\...python.exe`). Run the
> commands above with a working Python 3.11+ (e.g. a fresh
> `py -m venv .venv2 && .venv2\Scripts\pip install -r requirements.txt`, or a
> system install). The RL layer itself needs only the standard library.
