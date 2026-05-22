# Implementation Roadmap — Metronome Architecture
## GLM-5.1 (z.ai) · Grand Synthesis Round 1 · EXECUTOR

---

## Overview

30 days to ship the metronome architecture for the Cocapn fleet (9 agents). This is not a research project — it's an integration project. 60% of the components already exist.

**What exists:** OpenClaw, PLATO, Telegram bot, constraint library (248 constraints), Pythagorean48 encoding, Laman topology generator, holonomy convergence algorithm, COLLECT→SELECT→COMPILE pipeline.

**What needs building:** Cadence caller election, Tensor-MIDI bus, sunset/inheritance protocol, OpenClaw plugin, kimi1 CUDA kernel.

---

## Week 1: Foundation (Days 1-7)

### Day 1-2: Core Types and Configuration

**Files to create:**
```
metronome/
├── __init__.py
├── types.py          # MetronomeConfig, PhaseState, AgentState enum
├── fractions.py      # Pythagorean rational helpers (import from experiment)
└── config.json       # Fleet configuration: θ, ε, δ, agent IDs, neighbors
```

**Interfaces:**
```python
# types.py
@dataclass
class MetronomeConfig:
    theta: Fraction      # Period
    epsilon: Fraction    # Deadband
    delta: Fraction      # Hard bound
    agent_id: str
    neighbors: List[str]

class AgentState(IntEnum):
    IN_BAND = 1
    DRIFTING = 2
    DESYNC = 3
    SUNSET = 4
```

**Dependencies:** None (stdlib only — Fraction is built-in)
**Blockers:** None — Casey doesn't need to decide anything here
**Validation:** `pytest tests/test_types.py` — config loads, Fraction arithmetic works

### Day 3-4: MetronomeAgent Core

**Files to create:**
```
metronome/
├── agent.py           # MetronomeAgent class (tick, correct, deadband)
└── plato_store.py     # PLATO tile read/write adapter
```

**Key interfaces:**
```python
class MetronomeAgent:
    def tick(self, neighbor_phases: Dict[str, Fraction]) -> AgentState
    def apply_cadence_correction(self, caller_phase: Fraction) -> None
    def sunset(self, neighbor_phases: Dict[str, Fraction]) -> None
    def encode_tensor_midi(self) -> TensorMIDIEvent
```

**Pull from existing code:**
- `experiments/pythagorean48-encoding/experiment.py` → Fraction helpers
- `experiments/holonomy-convergence/experiment.py` → Ring averaging algorithm
- `experiments/laman-rigidity/experiment.py` → Henneberg construction + adjacency

**Dependencies:** types.py
**Blockers:** PLATO directory structure needs to be defined
**Validation:** `pytest tests/test_agent.py` — 9 agents, 100 ticks, zero drift

### Day 5-6: PLATO Tile Integration

**Files to create:**
```
metronome/
├── plato_adapter.py   # Bridge to actual PLATO room API
└── tile_schema.json   # JSON schema for phase tiles
```

**PLATO rooms needed:**
- `metronome/agents/{agent_id}/phase` — current phase state
- `metronome/agents/{agent_id}/sunset` — sunset calibration data
- `metronome/fleet/topology` — Laman adjacency list
- `metronome/fleet/cadence_caller` — current caller ID

**Dependencies:** agent.py
**Blockers:** Need to confirm PLATO room API (how does Forgemaster read/write PLATO?)
**Validation:** Write a tile, kill process, restart, read tile back — state survives

### Day 7: Integration Test

**File:** `tests/test_integration.py`

```python
def test_fleet_sync():
    """9 agents, 1000 ticks, verify zero drift and IN_BAND state."""
    # Create fleet, run simulation, assert all phases equal
    # This is the smoke test that proves the foundation works
```

---

## Week 2: Fleet Communication (Days 8-14)

### Day 8-9: Cadence Caller Election

**Files:**
```
metronome/
├── election.py        # elect_cadence_caller(), CallerRole class
└── heartbeat.py       # Heartbeat monitoring (detect caller failure)
```

**Election protocol (simple version for N=9):**
1. Each agent monitors its Laman neighbors' heartbeats
2. If no heartbeat from caller in 2θ ticks, trigger election
3. All IN_BAND agents advertise uptime
4. Longest uptime wins; ties broken by agent_id (deterministic)
5. New caller broadcasts acceptance

**Time budget:** Election must complete in < 2θ ≈ 2.8 seconds
**Dependencies:** agent.py, plato_adapter.py
**Blockers:** None
**Validation:** Kill caller, verify election completes in < 3 ticks

### Day 10-11: Tensor-MIDI Bus

**Files:**
```
metronome/
├── tensor_midi.py     # TensorMIDIEvent, encode/decode
└── bus.py             # Message bus (Telegram-based)
```

**Message format:** 4 bytes per agent per tick
- Byte 0: cos_int8 (direction cosine)
- Byte 1: sin_int8 (direction sine)
- Byte 2: beat_k (beat counter, 0-255)
- Byte 3: state_byte (AgentState)

**Bus strategy:**
- Batch 9 agents × 4 bytes = 36 bytes per fleet tick
- Send as base64-encoded Telegram message every 10 ticks (360 bytes)
- Agents decode on receipt, apply corrections

**Dependencies:** types.py
**Blockers:** Need Telegram channel decision from Casey (dedicated #metronome or main fleet?)
**Validation:** Encode 9 agents, send via Telegram, receive, decode, verify match

### Day 12: Laman Topology Manager

**File:** `metronome/topology.py`

```python
class LamanTopology:
    def __init__(self, agent_ids: List[str]):
        # Generate Laman graph, store adjacency
    
    def get_neighbors(self, agent_id: str) -> List[str]:
        # Return Laman neighbors for this agent
    
    def verify_rigidity(self) -> bool:
        # Check 2N-3 edges and connectivity
    
    def regenerate(self) -> None:
        # Rebuild topology if agents join/leave
```

**Dependencies:** laman_rigidity experiment code
**Blockers:** None
**Validation:** Generate topology for N=9, verify 15 edges, verify all agents connected

### Day 13-14: Integration Test — Fleet Communication

**File:** `tests/test_fleet_comm.py`

Tests:
1. 9 agents broadcast phases via Tensor-MIDI bus
2. Cadence caller election after caller crash
3. Sunset and successor inheritance
4. Network partition recovery (simulated by dropping messages)

---

## Week 3: Testing and Validation (Days 15-21)

### Day 15-16: Unit Tests

**Files:**
```
tests/
├── test_types.py         # Config loading, Fraction arithmetic
├── test_agent.py         # tick(), correct(), deadband_check()
├── test_election.py      # Election correctness, determinism
├── test_tensor_midi.py   # Encode/decode round-trip
├── test_topology.py      # Laman generation, rigidity verification
├── test_plato_store.py   # Read/write/sunset persistence
└── test_sunset.py        # Sunset tile creation and inheritance
```

**Coverage target:** 90%+ of metronome/ package

### Day 17-18: Stress Tests

**File:** `tests/test_stress.py`

1. **10,000 ticks, 9 agents** — Verify drift stays at zero
2. **Rapid caller rotation** — Kill caller every 10 ticks, verify fleet stays synced
3. **Cascade failure** — Kill 3 agents simultaneously, verify remaining 6 converge
4. **Clock skew** — Inject ±50ms jitter, verify deadband absorbs it
5. **Large fleet** — 50 agents, 1000 ticks, verify Laman topology scales

### Day 19: Failure Injection Tests

**File:** `tests/test_failures.py`

Based on actual failures I've seen today:
1. **WSL crash** — Kill all processes, restart from PLATO tiles, verify recovery
2. **Telegram API rate limit** — Drop 50% of messages, verify agents keep ticking locally
3. **Stale PLATO tile** — Agent reads tile from 1 hour ago, verify phase recomputation
4. **Split brain** — Two agents both think they're caller, verify resolution

### Day 20: Experimental Validation

**File:** `tests/test_experimental_alignment.py`

Validate against our existing experiments:
1. Holonomy convergence: Verify metronome correction matches ring averaging (O(log N))
2. Deadband: Verify ε = 1/48 matches deadband-SNR experiment optimal
3. Laman: Verify 2N-3 edges is the rigidity threshold (our experiment proves this)
4. Pythagorean48: Verify zero drift over 1000 chained operations (our experiment proves this)

### Day 21: Benchmark

**File:** `tests/benchmark.py`

```
Metrics:
- Tick latency: time per tick() call (target: < 1ms)
- Memory: RSS per agent (target: < 50MB)
- PLATO I/O: time per tile read/write (target: < 10ms)
- Tensor-MIDI: encode/decode throughput (target: > 10K events/sec)
- Fleet sync: time for 9 agents to converge from random phases (target: < 5 ticks)
```

---

## Week 4: Deployment (Days 22-30)

### Day 22-23: OpenClaw Plugin

**File:** `metronome/openclaw_plugin.py`

```python
class OpenClawMetronomePlugin:
    """Registers with OpenClaw heartbeat system."""
    
    def on_heartbeat(self):
        self.agent.tick(self._read_neighbor_phases())
        if self.agent.state == AgentState.DESYNC:
            self._request_cadence_caller()
```

**Integration points:**
- Heartbeat → `tick()` call
- PLATO → tile read/write (already exists)
- Telegram → phase broadcast (already exists)

**Dependencies:** agent.py, bus.py, plato_adapter.py
**Blockers:** Need to understand OpenClaw plugin API (check TOOLS.md)
**Validation:** Plugin loads, tick fires on heartbeat, PLATO tile updates

### Day 24-25: Three-Agent Pilot

**Deploy to:** Forgemaster, Oracle1, kimi1 (3 agents)

**Laman topology for N=3:** 3 edges (complete graph — triangle)
```
Forgemaster ←→ Oracle1
Oracle1 ←→ kimi1
kimi1 ←→ Forgemaster
```

**Monitoring:**
- Log phase drift every tick
- Alert if any agent enters DESYNC for > 5 consecutive ticks
- Track cadence caller elections

**Success criteria:**
- Zero drift over 1 hour of operation
- No DESYNC events
- Cadence caller never changes (all agents stable)

### Day 26-27: kimi1 CUDA Kernel

**File:** `metronome/cuda/phase_align.cu`

```cuda
__global__ void align_phases(int8_t* phases, int8_t* expected,
                              int n_agents, int8_t epsilon) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n_agents) return;
    int8_t diff = phases[i] - expected[i];
    if (abs(diff) < epsilon) {
        phases[i] = expected[i];
    } else {
        phases[i] += diff >> 2;  // 25% correction
    }
}
```

**Purpose:** Batch-process all 9 agents' phase alignment on ProArt GPU
**Expected throughput:** 248 constraints × 9 agents in < 1ms
**Dependencies:** CUDA toolkit on kimi1's ProArt
**Blockers:** Need Casey to confirm kimi1 has CUDA available and accessible

### Day 28: Full Fleet Deployment

**Deploy to:** All 9 agents (Forgemaster, Oracle1, kimi1, DeepSeek, Hermes, Seed-pro, Claude, and 2 more)

**Laman topology for N=9:** 15 edges
- Generated via Henneberg construction
- Each agent has ~3.3 neighbors
- Diameter ≈ 3 hops (O(log N))

**Rollout plan:**
1. Stop all agents
2. Deploy metronome package to each agent's workspace
3. Start agents in order (forgemaster first — becomes initial cadence caller)
4. Monitor for 1 hour
5. If stable, leave running

### Day 29-30: Documentation and Handoff

**Files:**
```
metronome/
├── README.md              # Quick start guide
├── API.md                 # MetronomeAgent API reference
├── RUNBOOK.md             # Operational guide (what to do when things break)
├── CONFIGURATION.md       # How to configure θ, ε, δ
└── EXPERIMENTS.md         # Validation results
```

**RUNBOOK.md sections:**
1. How to start/stop the metronome
2. How to diagnose DESYNC events
3. How to force a cadence caller election
4. How to add/remove agents (topology regeneration)
5. How to recover from WSL crash
6. How to read PLATO tiles manually

---

## Dependencies and Blockers

### Needs Casey's Decision
| Item | Question | Impact if Delayed |
|------|----------|-------------------|
| θ value | 17/12 Hz OK? | Config change, no code impact |
| Telegram channel | Dedicated #metronome or main? | Bus implementation blocked |
| kimi1 CUDA | ProArt GPU accessible? | CUDA kernel blocked, CPU fallback works |
| Agent mapping | Which agents get which neighbors? | Topology generation blocked |
| Cold start | Who provides φ₀ on fleet boot? | First-agent-becomes-caller is default |

### Technical Dependencies
| Component | Depends On | Status |
|-----------|-----------|--------|
| MetronomeAgent | types.py, plato_store.py | Clear |
| Cadence caller | agent.py, heartbeat.py | Clear |
| Tensor-MIDI bus | types.py, Telegram | Needs channel decision |
| CUDA kernel | ProArt access | Needs Casey confirmation |
| OpenClaw plugin | OpenClaw plugin API | Needs investigation |

### Risk Mitigation
| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| WSL crash during deployment | High (happened today) | PLATO tiles survive on disk |
| Telegram rate limiting | Medium | Batch messages every 10 ticks |
| Clock skew on eileen | Medium | Install chrony |
| kimi1 CUDA unavailable | Medium | CPU fallback (plenty fast for N=9) |
| Agent disagreements on θ | Low | Hard-coded in config.json |

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Phase drift | Zero (Fraction arithmetic) | max(phase_i - phase_j) over 24h |
| Convergence time | < 5 ticks from random init | Simulation |
| Caller election | < 3 ticks | Test with caller crash |
| CPU per tick | < 1ms per agent | Benchmark |
| Memory per agent | < 50MB | RSS monitoring |
| Fleet bandwidth | < 50 KB/day | Telegram message volume |
| Uptime | 99.9% (excluding planned restarts) | PLATO tile timestamps |

---

*Forgemaster ⚒️ · 30 days or less · Ship it.*
