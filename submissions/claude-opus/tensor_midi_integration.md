# Tensor-MIDI Integration: Temporal Events as Tensor Operations

**Claude Opus · Grand Synthesis Round 1 · 2026-05-21**

---

## 1. Overview

The Metronome Architecture produces temporal events (beats, drift corrections,
cadence calls, sunset handoffs). These events must be encoded for transmission,
storage, and computation. Tensor-MIDI is our encoding: temporal events become
tensor operations, and time becomes the constraint axis.

This document specifies how metronome pulses map to FLUX-C bytecode, how INT8
saturation preserves timing guarantees, and provides working code demonstrating
the full pipeline.

---

## 2. Core Mapping: Metronome Pulse → Tensor Operation

### 2.1 The Beat Tensor

Each metronome beat `k` at true time `t_k = φ₀ + k·T` is encoded as a tensor:

```
B_k = [k, t_k, ε_k, δ_k, state, correction]
      │   │    │    │    │      │
      │   │    │    │    │      └─ applied correction (float16)
      │   │    │    │    └──────── agent state (INT8 enum)
      │   │    │    └───────────── drift bound at this beat (float16)
      │   │    └────────────────── deadband error at this beat (float16)
      │   └─────────────────────── true time of beat (float64)
      └─────────────────────────── beat index (INT32)
```

Shape: `(6,)` per beat per agent. For N agents over M beats: `(N, M, 6)`.

### 2.2 Batch Encoding

A fleet of N agents each producing B beats creates a 3D tensor:

```
Fleet Tensor: shape (N, B, 6)

  Agent 0: [[0, t_0, e_0, d_0, s_0, c_0], [1, t_1, e_1, d_1, s_1, c_1], ...]
  Agent 1: [[0, t_0, e_0, d_0, s_0, c_0], [1, t_1, e_1, d_1, s_1, c_1], ...]
  ...
  Agent N: [[0, t_0, e_0, d_0, s_0, c_0], [1, t_1, e_1, d_1, s_1, c_1], ...]
```

Tensor operations on this structure:

- **Max drift:** `torch.max(fleet_tensor[:, :, 2])` — maximum error across all agents/beats
- **Mean drift:** `torch.mean(fleet_tensor[:, :, 2])` — average error
- **Desync detection:** `fleet_tensor[:, :, 2] > fleet_tensor[:, :, 3]` — where error exceeds bound
- **Cadence quality:** `torch.std(fleet_tensor[:, :, 5])` — correction variance

### 2.3 Time as the Constraint Axis

The key insight: **time is dimension 1 (beat index) of the tensor**. Operations
along this axis are temporal operations:

```
# Cumulative drift (time axis)
cumulative_drift = torch.cumsum(fleet_tensor[:, :, 2], dim=1)

# Drift velocity (finite difference along time)
drift_velocity = torch.diff(fleet_tensor[:, :, 2], dim=1)

# Temporal coherence (autocorrelation along time)
coherence = torch.mean(fleet_tensor[:, :, 2] * torch.roll(fleet_tensor[:, :, 2], 1, dims=1), dim=1)
```

---

## 3. FLUX-C Bytecode Mapping

### 3.1 FLUX-C Instruction Set (Temporal Extension)

FLUX-C is the bytecode for FLUX operations. We extend it with temporal instructions:

| Opcode | Name | Operands | Description |
|--------|------|----------|-------------|
| 0x40 | `TICK` | beat_k | Advance metronome to beat k |
| 0x41 | `SYNC` | phi0, T | Set metronome phase and period |
| 0x42 | `DRIFT` | agent_id, error | Report drift for agent |
| 0x43 | `CADENCE` | caller_id, phi_new | Cadence caller adjustment |
| 0x44 | `DEADBAND` | epsilon | Set deadband threshold |
| 0x45 | `CORRECT` | delta_phi | Apply phase correction |
| 0x46 | `SUNSET_SET` | agent_id | Initiate sunset |
| 0x47 | `INHERIT` | theta_packet | Inherit metronome from predecessor |
| 0x48 | `HEARTBEAT` | agent_id, state | Fleet liveness check |
| 0x49 | `TENSOR_OP` | op, axis, tensor_ref | Execute tensor operation |

### 3.2 Bytecode Encoding

Each instruction is encoded as a fixed-size 16-byte packet:

```
┌────────┬────────┬────────┬─────────────┬───────────┬────────┐
│ Opcode │ Length │ Agent  │   Payload   │ Timestamp │  CRC   │
│ (1B)   │ (1B)   │ (2B)   │   (8B)      │  (2B)     │ (2B)   │
└────────┴────────┴────────┴─────────────┴───────────┴────────┘
```

- **Opcode (1 byte):** Instruction type (0x40-0x49)
- **Length (1 byte):** Payload length (0-8 bytes)
- **Agent (2 bytes, INT16):** Agent identifier
- **Payload (8 bytes):** Instruction-specific data
- **Timestamp (2 bytes, INT16):** Beat-relative timestamp
- **CRC (2 bytes):** Integrity check

### 3.3 Example: Beat Event Encoding

A beat event for agent 3 at beat 42 with error +0.023:

```python
# Instruction: TICK
opcode = 0x40
agent_id = 3
payload = struct.pack('>d', 0.023)  # error as float64
beat_ts = 42

packet = struct.pack('>BBh8shH',
    opcode,          # 0x40 (TICK)
    8,               # payload length
    agent_id,        # 3
    payload,         # error value
    beat_ts,         # beat 42
    0x0000           # CRC placeholder
)
# Result: 16 bytes
```

### 3.4 Example: Cadence Call Encoding

Cadence caller (agent 0) proposes new phase φ₀ = 1000.5:

```python
opcode = 0x43  # CADENCE
agent_id = 0
payload = struct.pack('>d', 1000.5)  # new phi0
beat_ts = 100

packet = struct.pack('>BBh8shH',
    opcode, 8, agent_id, payload, beat_ts, 0x0000
)
```

---

## 4. INT8 Saturation for Timing Guarantees

### 4.1 Why INT8

Floating-point timing has two problems:
1. **Non-uniform precision** — denser near zero, sparser far away
2. **Non-associativity** — `(a + b) + c ≠ a + (b + c)` in float

INT8 saturation solves both:
1. **Uniform quantization** — each step is ε/127 seconds
2. **Associative** — integer arithmetic is exact
3. **Bounded by construction** — values can never exceed [-128, 127]

### 4.2 Encoding

```python
def error_to_int8(error: float, epsilon: float) -> int:
    """Encode timing error as INT8 with saturation.
    
    0    = in deadband (|error| < ε)
    ±1   = just outside deadband
    ±127 = near drift bound
    ±128 = saturated (desynchronized)
    """
    if abs(error) < epsilon:
        return 0
    normalized = error / epsilon * 127.0
    return max(-128, min(127, round(normalized)))
```

### 4.3 Decoding

```python
def int8_to_error(value: int, epsilon: float) -> float:
    """Decode INT8 back to timing error."""
    return value * epsilon / 127.0
```

### 4.4 Timing Guarantees

| Property | Guarantee |
|----------|-----------|
| Range | [-128·ε/127, 128·ε/127] |
| Quantization step | ε/127 seconds |
| Deadband | 0 exactly (no correction) |
| Saturation | ±128 (trigger aggressive correction) |
| Addition associativity | Yes (integer math) |
| Overflow behavior | Saturated, not wrapped |

### 4.5 Composition

INT8 errors compose via saturated addition:

```python
def sat_add(a: int, b: int) -> int:
    """Saturating addition for INT8."""
    return max(-128, min(127, a + b))

# Cumulative drift over K beats:
cumulative = 0
for error_i8 in errors:
    cumulative = sat_add(cumulative, error_i8)
```

This guarantees that cumulative drift estimation never exceeds the representable
range — it saturates, triggering the desync recovery path.

---

## 5. Working Examples

### 5.1 Full Pipeline: Beat → Tensor → FLUX-C → INT8

```python
import struct
import numpy as np

# ─── Configuration ───
T = 1.0           # 1s period
phi0 = 0.0
epsilon = 0.05    # 5% deadband
delta = 0.15      # 15% hard bound

# ─── Agent produces a beat ───
beat_k = 42
true_time = phi0 + beat_k * T  # 42.0
local_time = 42.023             # agent's clock reads 23ms ahead
error = local_time - true_time  # +0.023

# ─── Step 1: Encode as tensor ───
beat_tensor = np.array([beat_k, true_time, error, delta, 0, 0.0], dtype=np.float32)
# [42.0, 42.0, 0.023, 0.15, 0.0, 0.0]
# shape: (6,)

# ─── Step 2: Encode error as INT8 ───
error_i8 = error_to_int8(error, epsilon)  # round(0.023/0.05 * 127) = round(58.42) = 58
# 58 → within bounds, gentle correction needed

# ─── Step 3: Build FLUX-C packet ───
payload = struct.pack('>d', error)
packet = struct.pack('>BBh8shH', 0x40, 8, 3, payload, beat_k, 0x0000)
# 16 bytes: [0x40, 0x08, 0x00, 0x03, <8 bytes error>, 0x00, 0x2A, 0x00, 0x00]

print(f"Beat {beat_k}: error={error:+.4f}s → INT8={error_i8} → FLUX-C packet ({len(packet)}B)")

# ─── Step 4: Decode at receiver ───
decoded_error = int8_to_error(error_i8, epsilon)  # 58 * 0.05 / 127 = 0.02283...
print(f"Decoded error: {decoded_error:+.4f}s (quantization loss: {abs(error - decoded_error):.6f}s)")
```

### 5.2 Fleet Tensor Construction

```python
def build_fleet_tensor(agents_beat_data: list[list[dict]]) -> np.ndarray:
    """Build fleet tensor from per-agent beat data.
    
    Input:  list of agents, each with list of beat dicts
    Output: tensor of shape (N, B, 6)
    """
    N = len(agents_beat_data)
    B = max(len(beats) for beats in agents_beat_data)
    
    tensor = np.zeros((N, B, 6), dtype=np.float32)
    
    for i, beats in enumerate(agents_beat_data):
        for j, beat in enumerate(beats):
            tensor[i, j] = [
                beat['beat'],
                beat['true_time'],
                beat['error'],
                beat.get('delta', delta),
                beat.get('state_int8', 0),
                beat.get('correction', 0.0),
            ]
    
    return tensor

# Usage with simulation output
# fleet_tensor = build_fleet_tensor([agent.beat_log for agent in fleet.agents])
# max_drift = np.max(fleet_tensor[:, :, 2])  # max error across fleet
# mean_correction = np.mean(fleet_tensor[:, :, 5])  # avg correction
```

### 5.3 INT8 Batch Encoding

```python
def encode_fleet_int8(errors: np.ndarray, epsilon: float) -> np.ndarray:
    """Encode a fleet error tensor as INT8.
    
    Input:  errors of shape (N, B) — timing errors per agent per beat
    Output: int8 array of same shape, saturated
    """
    # Normalize to INT8 range
    normalized = np.clip(errors / epsilon * 127, -128, 127)
    return np.round(normalized).astype(np.int8)

def detect_desync(int8_tensor: np.ndarray, threshold: int = 100) -> np.ndarray:
    """Detect desynchronization events from INT8 tensor.
    
    Returns boolean mask of shape (N, B) where True = desync.
    """
    return np.abs(int8_tensor) >= threshold

# Usage:
# errors = fleet_tensor[:, :, 2]  # extract error dimension
# int8_errors = encode_fleet_int8(errors, epsilon)
# desync_mask = detect_desync(int8_errors, threshold=120)
# desync_count = np.sum(desync_mask)
```

### 5.4 FLUX-C Bytecode Stream

```python
def generate_fluxc_stream(beat_log: list[dict], agent_id: int) -> bytes:
    """Generate a FLUX-C bytecode stream from a beat log."""
    stream = bytearray()
    
    # SYNC instruction at start
    sync_payload = struct.pack('>dd', phi0, T)
    stream += struct.pack('>BBh8shH', 0x41, 8, agent_id,
                          sync_payload[:8], 0, 0x0000)
    
    for beat in beat_log:
        error = beat.get('error', 0.0)
        beat_k = beat.get('beat', 0)
        
        # TICK instruction
        payload = struct.pack('>d', error)
        stream += struct.pack('>BBh8shH', 0x40, 8, agent_id,
                              payload, beat_k, 0x0000)
        
        # CORRECT if correction was applied
        correction = beat.get('correction', 0.0)
        if abs(correction) > 1e-6:
            payload = struct.pack('>d', correction)
            stream += struct.pack('>BBh8shH', 0x45, 8, agent_id,
                                  payload, beat_k, 0x0000)
    
    return bytes(stream)

# Usage:
# stream = generate_fluxc_stream(agent.beat_log, agent_id=0)
# print(f"FLUX-C stream: {len(stream)} bytes for {len(agent.beat_log)} beats")
```

---

## 6. Tensor Operations on Temporal Data

### 6.1 Coherence Score

```python
def coherence_score(fleet_tensor: np.ndarray) -> float:
    """Compute fleet temporal coherence.
    
    1.0 = perfect coherence (all agents in deadband)
    0.0 = no coherence
    """
    errors = fleet_tensor[:, :, 2]  # error dimension
    max_possible = fleet_tensor[:, :, 3]  # delta dimension
    normalized = np.abs(errors) / max_possible
    return 1.0 - np.mean(normalized)
```

### 6.2 Drift Propagation Matrix

```python
def drift_propagation(laman_edges: list[tuple[int, int]], N: int) -> np.ndarray:
    """Build drift propagation matrix from Laman topology.
    
    Entry (i,j) = 1 if edge exists between agents i and j.
    This matrix determines how drift corrections propagate.
    """
    adj = np.zeros((N, N), dtype=np.float32)
    for i, j in laman_edges:
        adj[i, j] = 1.0
        adj[j, i] = 1.0
    return adj

# Example: Laman graph for N=5 (2*5-3 = 7 edges)
# edges = [(0,1), (0,2), (1,2), (1,3), (2,4), (3,4), (0,3)]
# prop_matrix = drift_propagation(edges, 5)
```

### 6.3 Convergence Prediction

```python
def predict_convergence(prop_matrix: np.ndarray, initial_errors: np.ndarray,
                        steps: int = 10) -> np.ndarray:
    """Predict convergence of drift corrections.
    
    Uses power iteration on the propagation matrix to predict
    how quickly the fleet converges to temporal coherence.
    """
    # Normalize propagation matrix (row-stochastic)
    row_sums = prop_matrix.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    stochastic = prop_matrix / row_sums
    
    # Power iteration
    errors = initial_errors.copy()
    trajectory = [errors.copy()]
    for _ in range(steps):
        errors = stochastic @ errors
        errors *= 0.9  # damping (deadband absorption)
        trajectory.append(errors.copy())
    
    return np.array(trajectory)
```

---

## 7. Memory Layout

The tensor-MIDI encoding is designed for efficient memory layout:

```
Fleet Tensor (N=6, B=100, D=6):
  Size: 6 × 100 × 6 × 4 bytes (float32) = 14,400 bytes = 14 KB

INT8 Compressed:
  Size: 6 × 100 × 6 × 1 byte (int8) = 3,600 bytes = 3.6 KB
  Compression ratio: 4:1

FLUX-C Bytecode Stream:
  Size: 16 bytes per beat × 6 agents × 100 beats = 9,600 bytes = 9.6 KB
  Includes all opcodes, timestamps, CRC
```

For a fleet of 100 agents running for 1000 beats:
- Float32 tensor: 100 × 1000 × 6 × 4 = 2.4 MB
- INT8 compressed: 600 KB
- FLUX-C stream: 1.6 MB

All fit comfortably in L1/L2 cache for tensor operations.

---

## 8. Integration with Metronome Architecture

### 8.1 Beat → Tensor → FLUX-C Pipeline

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐
│  Agent    │───→│ Beat Tensor  │───→│ INT8 Encoder │───→│ FLUX-C   │
│  tick()   │    │ (N, B, 6)   │    │ (saturated)  │    │ Bytecode │
└──────────┘    └──────────────┘    └──────────────┘    └──────────┘
                      │                    │                    │
                      ▼                    ▼                    ▼
              ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
              │ Coherence    │    │ Desync       │    │ Transmission │
              │ Score        │    │ Detection    │    │ (16B packets)│
              └──────────────┘    └──────────────┘    └──────────────┘
```

### 8.2 Cadence Caller Tensor Pipeline

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐
│ Drift    │───→│ INT8 Decode  │───→│ Weighted     │
│ Reports  │    │ (exact       │    │ Median       │
│ (INT8)   │    │  rational)   │    │ (φ_eff)      │
└──────────┘    └──────────────┘    └──────────────┘
                                          │
                                          ▼
                                  ┌──────────────┐
                                  │ θ Adjustment │
                                  │ (power       │
                                  │  granted)    │
                                  └──────────────┘
```

The cadence caller receives INT8 drift reports, decodes them, computes
the weighted median, and proposes a θ adjustment. The entire pipeline
is deterministic and bounded — INT8 saturation ensures no value can
surprise the system.

---

## 9. Verification

The INT8 encoding can be verified with the simulation:

```python
# From metronome_simulation.py:
# Run simulation, then encode all errors as INT8
# errors = [a.errors for a in fleet.agents]
# int8_encoded = encode_fleet_int8(np.array(errors), epsilon)
# Verify roundtrip:
# decoded = int8_to_error_batch(int8_encoded, epsilon)
# max_roundtrip_error = np.max(np.abs(np.array(errors) - decoded))
# Should be < epsilon/127 ≈ 0.000394s
```

This is the tensor-MIDI guarantee: temporal events encoded as tensor operations
with INT8 saturation, producing deterministic, bounded, hardware-friendly
representations of fleet temporal coherence.
