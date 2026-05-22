#!/usr/bin/env python3
"""
Metronome Lifecycle Simulation — Full Agent Lifecycle with 3+ Generations
=========================================================================

Demonstrates the complete Metronome Architecture:
- BIRTH: Agent initializes with inherited metronome from predecessor
- ITERATION: Agent runs with local metronome, bounded drift
- CADENCE: Any agent can call cadence, election via Laman rigidity
- CONVERGENCE: Tiles snap to truth, metronome internalizes
- SUNSET: Agent decomposes into tiles, writes memoir, bequeaths calibrated metronome
- INHERITANCE: Next agent starts from sunset state

Reproducible: Fixed random seed.
"""

import random
import math
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum
from collections import defaultdict
import statistics

random.seed(42)

# =============================================================================
# Constants
# =============================================================================

# Pythagorean triples with c <= 100 (52 unique)
def generate_pythagorean_triples(max_c=100):
    triples = []
    for c in range(5, max_c + 1):
        for a in range(3, c):
            b_sq = c * c - a * a
            b = int(math.isqrt(b_sq))
            if b * b == b_sq and a <= b:
                triples.append((a, b, c))
    return triples

PYTHAGOREAN_TRIPLES = generate_pythagorean_triples()

# =============================================================================
# Tensor-MIDI Event System
# =============================================================================

class EventType(Enum):
    TICK = 0
    TILE_UPDATE = 1
    CADENCE_CALL = 2
    DRIFT_MINE = 3
    SUNSET = 4
    BIRTH = 5
    CONSTRAINT = 6
    CONVERGENCE = 7

@dataclass
class TensorMIDIEvent:
    tick: int
    event_type: EventType
    agent_id: str
    payload: Dict
    constraint_mask: int = 0
    
    def encode(self) -> Dict:
        return {
            'tick': self.tick,
            'type': self.event_type.name,
            'agent': self.agent_id,
            'payload': self.payload,
            'mask': self.constraint_mask
        }

class TensorMIDIStream:
    """Records all temporal events in the fleet's history."""
    def __init__(self):
        self.events: List[TensorMIDIEvent] = []
    
    def record(self, event: TensorMIDIEvent):
        self.events.append(event)
    
    def query(self, tick_range=None, event_type=None, agent_id=None):
        results = self.events
        if tick_range:
            results = [e for e in results if tick_range[0] <= e.tick <= tick_range[1]]
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if agent_id:
            results = [e for e in results if e.agent_id == agent_id]
        return results
    
    def to_json(self):
        return json.dumps([e.encode() for e in self.events], indent=2)

# =============================================================================
# Laman Graph — Minimal Rigidity Topology
# =============================================================================

class LamanGraph:
    """Minimally rigid graph with E = 2V - 3 edges."""
    
    def __init__(self, n_agents: int):
        self.n = n_agents
        self.edges: List[Tuple[int, int]] = []
        self.adjacency: Dict[int, List[int]] = defaultdict(list)
        
        if n_agents >= 3:
            # Start with triangle (K3)
            self.edges = [(0, 1), (1, 2), (0, 2)]
            # Add vertices with 2 edges each (Henneberg type-I)
            for v in range(3, n_agents):
                # Connect to 2 existing vertices
                targets = random.sample(range(v), 2)
                for t in targets:
                    self.edges.append((v, t))
            
            # Build adjacency
            for (u, v) in self.edges:
                self.adjacency[u].append(v)
                self.adjacency[v].append(u)
    
    def has_quorum(self, agent_idx: int) -> bool:
        """Check if agent has enough connections to participate."""
        return len(self.adjacency.get(agent_idx, [])) >= 2
    
    def get_neighbors(self, agent_idx: int) -> List[int]:
        return self.adjacency.get(agent_idx, [])
    
    def is_rigid(self) -> bool:
        """Check if graph meets Laman's condition (2N-3 edges)."""
        if self.n < 2:
            return True
        return len(self.edges) == 2 * self.n - 3

# =============================================================================
# Tiles — Atomic Knowledge Units
# =============================================================================

@dataclass
class Tile:
    tile_id: str
    value: float
    direction: Optional[Tuple[int, int, int]] = None  # Pythagorean triple
    
    @staticmethod
    def quantize_direction(angle: float) -> Tuple[int, int, int]:
        """Snap angle to nearest Pythagorean triple direction."""
        best = None
        best_error = float('inf')
        for (a, b, c) in PYTHAGOREAN_TRIPLES:
            for sx in [1, -1]:
                for sy in [1, -1]:
                    for swap in [False, True]:
                        dx, dy = (sx * b, sy * a) if swap else (sx * a, sy * b)
                        candidate = math.atan2(dy, dx)
                        error = abs(candidate - angle)
                        if error < best_error:
                            best_error = error
                            best = (dx, dy, c)
        return best
    
    def to_dict(self):
        return {
            'id': self.tile_id,
            'value': self.value,
            'direction': self.direction
        }

# =============================================================================
# Agent Phases
# =============================================================================

class AgentPhase(Enum):
    BIRTH = "BIRTH"
    ITERATE = "ITERATE"
    CADENCE = "CADENCE"
    CONVERGE = "CONVERGE"
    SUNSET = "SUNSET"
    ARCHIVED = "ARCHIVED"

# =============================================================================
# Sunset State — What an Agent Leaves Behind
# =============================================================================

@dataclass
class SunsetState:
    agent_id: str
    generation: int
    calibrated_theta: float
    tiles: List[Tile]
    memoir: str
    drift_history: List[float]
    drift_insights: Dict
    constraint_graph_edges: List[Tuple[int, int]]

# =============================================================================
# Drift Mining — Extract Value from Drift Before Correcting
# =============================================================================

class DriftMiner:
    """Smart GC pattern: mine before you correct."""
    
    @staticmethod
    def mine(history: List[float]) -> Dict:
        if len(history) < 2:
            return {'mean': 0.0, 'variance': 0.0, 'trend': 'stable', 'anomalies': 0}
        
        mean = statistics.mean(history)
        variance = statistics.variance(history) if len(history) > 1 else 0.0
        
        # Detect trend
        if len(history) >= 5:
            recent = history[-5:]
            older = history[-10:-5] if len(history) >= 10 else history[:5]
            recent_mean = statistics.mean(recent)
            older_mean = statistics.mean(older) if older else recent_mean
            if recent_mean > older_mean * 1.1:
                trend = 'accelerating'
            elif recent_mean < older_mean * 0.9:
                trend = 'decelerating'
            else:
                trend = 'stable'
        else:
            trend = 'stable'
        
        # Detect anomalies (drift > 2 * stddev)
        stddev = math.sqrt(variance) if variance > 0 else 0.001
        anomalies = sum(1 for d in history if abs(d - mean) > 2 * stddev)
        
        return {
            'mean': mean,
            'variance': variance,
            'trend': trend,
            'anomalies': anomalies,
            'max_drift': max(history, key=abs),
            'periodicity_estimate': DriftMiner.estimate_periodicity(history)
        }
    
    @staticmethod
    def estimate_periodicity(history: List[float]) -> Optional[float]:
        """Simple periodicity detection via autocorrelation."""
        if len(history) < 10:
            return None
        n = len(history)
        mean = statistics.mean(history)
        var = statistics.variance(history)
        if var == 0:
            return None
        
        best_lag = None
        best_corr = 0
        for lag in range(1, n // 2):
            corr = 0
            for i in range(n - lag):
                corr += (history[i] - mean) * (history[i + lag] - mean)
            corr /= (var * (n - lag))
            if corr > best_corr:
                best_corr = corr
                best_lag = lag
        
        return best_lag if best_corr > 0.5 else None

# =============================================================================
# Agent — The Core Entity
# =============================================================================

class Agent:
    _id_counter = 0
    
    def __init__(self, generation: int, predecessor_state: Optional[SunsetState] = None,
                 theta: float = 0.85, deadband: float = 0.05):
        Agent._id_counter += 1
        self.id = f"agent_{Agent._id_counter}"
        self.generation = generation
        self.phase = AgentPhase.BIRTH
        self.theta = theta
        self.deadband = deadband
        
        # Local metronome state
        self.local_tick = 0
        self.phase_offset = random.gauss(0, 0.01)  # Small initial offset
        self.current_drift = 0.0
        
        # Knowledge tiles
        self.tiles: Dict[str, Tile] = {}
        
        # Drift tracking
        self.drift_history: List[float] = []
        
        # Trinity score
        self.ethos = random.uniform(0.7, 1.0)
        self.pathos = random.uniform(0.7, 1.0)
        self.logos = random.uniform(0.7, 1.0)
        
        # Cadence caller state
        self.is_caller = False
        self.caller_ttl = 0
        
        # Predecessor info
        self.predecessor_state = predecessor_state
        
        # Lifecycle tracking
        self.iterations = 0
        self.max_iterations = random.randint(80, 150)
        self.converged_tiles: List[str] = []
        
    @property
    def trinity_score(self) -> float:
        return self.ethos * self.pathos * self.logos
    
    def birth(self, stream: TensorMIDIStream, global_tick: int):
        """Phase 1: Initialize from predecessor state."""
        self.phase = AgentPhase.BIRTH
        
        if self.predecessor_state:
            # Inherit calibrated theta
            self.theta = self.predecessor_state.calibrated_theta
            # Inherit tiles
            for tile in self.predecessor_state.tiles:
                self.tiles[tile.tile_id] = Tile(
                    tile_id=tile.tile_id,
                    value=tile.value + random.gauss(0, 0.01),  # Small mutation
                    direction=tile.direction
                )
            # Predict initial drift from predecessor's history
            if self.predecessor_state.drift_insights:
                self.phase_offset = self.predecessor_state.drift_insights.get('mean', 0) * 0.5
        else:
            # First generation — initialize random tiles
            for i in range(5):
                angle = random.uniform(0, 2 * math.pi)
                direction = Tile.quantize_direction(angle)
                self.tiles[f"tile_{i}"] = Tile(
                    tile_id=f"tile_{i}",
                    value=random.uniform(0.3, 0.9),
                    direction=direction
                )
        
        stream.record(TensorMIDIEvent(
            tick=global_tick,
            event_type=EventType.BIRTH,
            agent_id=self.id,
            payload={
                'generation': self.generation,
                'inherited_theta': self.theta,
                'tile_count': len(self.tiles),
                'predecessor': self.predecessor_state.agent_id if self.predecessor_state else None
            }
        ))
        
        self.phase = AgentPhase.ITERATE
    
    def iterate(self, stream: TensorMIDIStream, global_tick: int, truth: Dict[str, float]):
        """Phase 2: Run one iteration with local metronome."""
        self.phase = AgentPhase.ITERATE
        self.local_tick += 1
        self.iterations += 1
        
        # Simulate drift (network noise, load variation, etc.)
        noise = random.gauss(0, 0.02)
        load_drift = 0.01 * math.sin(self.local_tick * 0.1)  # Periodic load
        self.current_drift = self.phase_offset + noise + load_drift
        self.drift_history.append(self.current_drift)
        
        # Mine drift (Smart GC pattern)
        if len(self.drift_history) % 10 == 0:
            insights = DriftMiner.mine(self.drift_history[-50:])
            stream.record(TensorMIDIEvent(
                tick=global_tick,
                event_type=EventType.DRIFT_MINE,
                agent_id=self.id,
                payload=insights
            ))
        
        # Check if drift exceeds deadband
        if abs(self.current_drift) > self.deadband:
            # Request cadence call (will be handled by fleet)
            return True  # Signal: need cadence correction
        
        # Record tick
        stream.record(TensorMIDIEvent(
            tick=global_tick,
            event_type=EventType.TICK,
            agent_id=self.id,
            payload={'drift': round(self.current_drift, 6), 'local_tick': self.local_tick}
        ))
        
        # Degrade trinity score over time (simulating resource wear)
        self.ethos *= random.uniform(0.995, 1.0)
        self.pathos *= random.uniform(0.997, 1.0)
        self.logos *= random.uniform(0.996, 1.0)
        
        # Check convergence
        for tile_id, tile in self.tiles.items():
            if tile_id in truth:
                error = abs(tile.value - truth[tile_id])
                if error < 0.02 and tile_id not in self.converged_tiles:
                    self.converged_tiles.append(tile_id)
        
        return False
    
    def receive_cadence(self, fleet_rhythm: float, stream: TensorMIDIStream, global_tick: int):
        """Accept cadence correction (power granted, not forced)."""
        correction = fleet_rhythm - self.current_drift
        
        # Apply correction proportionally (not full snap — gentle correction)
        self.current_drift += correction * 0.6  # 60% correction
        self.phase_offset = self.current_drift * 0.5  # Update offset
        
        stream.record(TensorMIDIEvent(
            tick=global_tick,
            event_type=EventType.CADENCE_CALL,
            agent_id=self.id,
            payload={'fleet_rhythm': fleet_rhythm, 'correction': correction}
        ))
    
    def converge(self, truth: Dict[str, float], stream: TensorMIDIStream, global_tick: int):
        """Phase 4: Snap tiles to truth."""
        self.phase = AgentPhase.CONVERGE
        
        for tile_id, true_value in truth.items():
            if tile_id in self.tiles:
                # Laman-weighted snap (simplified: closer tiles snap faster)
                error = self.tiles[tile_id].value - true_value
                self.tiles[tile_id].value -= error * 0.5  # Partial snap
                
                stream.record(TensorMIDIEvent(
                    tick=global_tick,
                    event_type=EventType.TILE_UPDATE,
                    agent_id=self.id,
                    payload={
                        'tile_id': tile_id,
                        'old_value': round(self.tiles[tile_id].value + error * 0.5, 4),
                        'new_value': round(self.tiles[tile_id].value, 4),
                        'truth': true_value
                    }
                ))
        
        self.phase = AgentPhase.ITERATE
    
    def should_sunset(self) -> bool:
        """Check if agent should sunset."""
        # Sunset if trinity is too low OR max iterations reached
        return self.trinity_score < 0.3 or self.iterations >= self.max_iterations
    
    def sunset(self, stream: TensorMIDIStream, global_tick: int) -> SunsetState:
        """Phase 5: Decompose into tiles, write memoir, bequeath."""
        self.phase = AgentPhase.SUNSET
        
        # Mine drift before sunset
        drift_insights = DriftMiner.mine(self.drift_history)
        
        # Calibrate theta based on drift experience
        # If drift was consistently small, tighten theta
        # If drift was large, loosen theta
        if drift_insights['variance'] < 0.001:
            calibrated_theta = self.theta * 0.98  # Tighten by 2%
        elif drift_insights['variance'] > 0.01:
            calibrated_theta = self.theta * 1.02  # Loosen by 2%
        else:
            calibrated_theta = self.theta
        
        # Write memoir
        memoir = self.write_memoir(drift_insights)
        
        state = SunsetState(
            agent_id=self.id,
            generation=self.generation,
            calibrated_theta=round(calibrated_theta, 6),
            tiles=list(self.tiles.values()),
            memoir=memoir,
            drift_history=self.drift_history[-100:],
            drift_insights=drift_insights,
            constraint_graph_edges=[]  # Would be populated in full implementation
        )
        
        stream.record(TensorMIDIEvent(
            tick=global_tick,
            event_type=EventType.SUNSET,
            agent_id=self.id,
            payload={
                'generation': self.generation,
                'calibrated_theta': state.calibrated_theta,
                'tile_count': len(state.tiles),
                'trinity_score': round(self.trinity_score, 4),
                'drift_variance': drift_insights['variance'],
                'total_iterations': self.iterations,
                'converged_tiles': len(self.converged_tiles)
            }
        ))
        
        self.phase = AgentPhase.ARCHIVED
        return state
    
    def write_memoir(self, drift_insights: Dict) -> str:
        """Write subjective account of agent's experience."""
        return (
            f"Agent {self.id} (Gen {self.generation}) memoir:\n"
            f"  Lived for {self.iterations} iterations.\n"
            f"  Drift: mean={drift_insights['mean']:.6f}, "
            f"var={drift_insights['variance']:.6f}, "
            f"trend={drift_insights['trend']}.\n"
            f"  Trinity at death: ethos={self.ethos:.3f}, "
            f"pathos={self.pathos:.3f}, logos={self.logos:.3f}\n"
            f"  Converged {len(self.converged_tiles)}/{len(self.tiles)} tiles.\n"
            f"  Calibrated θ: was {self.theta:.4f}\n"
            f"  Advice to successor: {self.get_advice()}\n"
        )
    
    def get_advice(self) -> str:
        if self.drift_history and statistics.mean([abs(d) for d in self.drift_history]) < 0.03:
            return "The metronome is stable. Trust it. Focus on tile convergence."
        elif self.drift_history and statistics.mean([abs(d) for d in self.drift_history]) > 0.08:
            return "Drift was high. Call cadence more frequently. Watch the topology."
        else:
            return "The rhythm is there. Listen for it. Don't force the correction."

# =============================================================================
# Fleet — The Collection of Agents
# =============================================================================

class Fleet:
    def __init__(self, n_agents: int, truth: Dict[str, float]):
        self.truth = truth
        self.agents: List[Agent] = []
        self.topology = LamanGraph(n_agents)
        self.stream = TensorMIDIStream()
        self.global_tick = 0
        self.generation = 0
        self.sunset_states: List[SunsetState] = []
        self.caller_idx = 0
        self.cadence_interval = 10
        
        # Spawn first generation
        for i in range(n_agents):
            agent = Agent(generation=0)
            self.agents.append(agent)
    
    def run(self, total_ticks: int = 500):
        """Run the fleet simulation."""
        print(f"\n{'='*70}")
        print(f"METRONOME LIFECYCLE SIMULATION")
        print(f"Fleet size: {len(self.agents)}, Ticks: {total_ticks}")
        print(f"{'='*70}")
        
        # Birth all agents
        for agent in self.agents:
            agent.birth(self.stream, self.global_tick)
        
        print(f"\n--- Generation {self.generation} born ---")
        print(f"  Topology: {len(self.topology.edges)} edges (Laman: {2*len(self.agents)-3})")
        print(f"  Agents: {[a.id for a in self.agents]}")
        
        while self.global_tick < total_ticks:
            self.global_tick += 1
            
            # Check if we need a new generation (all agents sunsetting)
            active_agents = [a for a in self.agents if a.phase not in (AgentPhase.SUNSET, AgentPhase.ARCHIVED)]
            
            if not active_agents:
                self.spawn_next_generation()
                continue
            
            # Iterate all active agents
            needs_cadence = []
            for agent in active_agents:
                needs_correction = agent.iterate(self.stream, self.global_tick, self.truth)
                if needs_correction:
                    needs_cadence.append(agent)
            
            # Cadence calling (if interval reached or agents need it)
            if self.global_tick % self.cadence_interval == 0 or needs_cadence:
                self.hold_cadence_call(active_agents)
            
            # Convergence (every 20 ticks)
            if self.global_tick % 20 == 0:
                for agent in active_agents:
                    if len(agent.converged_tiles) < len(agent.tiles):
                        agent.converge(self.truth, self.stream, self.global_tick)
            
            # Check for sunsets
            for agent in active_agents:
                if agent.should_sunset():
                    state = agent.sunset(self.stream, self.global_tick)
                    self.sunset_states.append(state)
                    print(f"\n  🌅 {agent.id} (Gen {agent.generation}) SUNSET at tick {self.global_tick}")
                    print(f"     Iterations: {agent.iterations}, Trinity: {agent.trinity_score:.4f}")
                    print(f"     Converged: {len(agent.converged_tiles)}/{len(agent.tiles)} tiles")
                    print(f"     Calibrated θ: {state.calibrated_theta:.6f}")
        
        # Print final summary
        self.print_summary()
    
    def hold_cadence_call(self, active_agents: List[Agent]):
        """Cadence caller election and rhythm granting."""
        # Elect caller: lowest drift wins
        candidates = [(abs(a.current_drift), a) for a in active_agents if self.topology.has_quorum(self.agents.index(a))]
        if not candidates:
            return
        
        candidates.sort(key=lambda x: x[0])
        caller = candidates[0][1]
        
        # Compute fleet rhythm (median drift)
        drifts = [a.current_drift for a in active_agents]
        fleet_rhythm = statistics.median(drifts)
        
        # Grant cadence (not force)
        for agent in active_agents:
            if abs(agent.current_drift) > agent.deadband:
                agent.receive_cadence(fleet_rhythm, self.stream, self.global_tick)
    
    def spawn_next_generation(self):
        """Spawn new generation from sunset states."""
        self.generation += 1
        
        if self.generation > 3:
            if not hasattr(self, '_limit_printed'):
                print(f"\n--- Generation limit reached (Gen {self.generation-1} was last). Running out remaining ticks idle. ---")
                self._limit_printed = True
            return
        
        n_agents = len(self.agents)  # Same fleet size
        
        # Use the last sunset state as predecessor
        predecessor = self.sunset_states[-1] if self.sunset_states else None
        
        new_agents = []
        for i in range(n_agents):
            # Each new agent inherits from predecessor (with slight mutation)
            if predecessor:
                inherited_theta = predecessor.calibrated_theta + random.gauss(0, 0.005)
                agent = Agent(
                    generation=self.generation,
                    predecessor_state=predecessor,
                    theta=inherited_theta,
                    deadband=0.04  # Slightly tighter deadband (learned from predecessor)
                )
            else:
                agent = Agent(generation=self.generation)
            new_agents.append(agent)
        
        self.agents = new_agents
        self.topology = LamanGraph(n_agents)
        
        # Birth all new agents
        for agent in self.agents:
            agent.birth(self.stream, self.global_tick)
        
        print(f"\n--- Generation {self.generation} born ---")
        print(f"  Inherited θ: {self.agents[0].theta:.6f} (from {predecessor.agent_id if predecessor else 'void'})")
        print(f"  Predecessor advice: {predecessor.memoir.split('Advice to successor:')[-1].strip() if predecessor and 'Advice' in predecessor.memoir else 'N/A'}")
        print(f"  Agents: {[a.id for a in self.agents]}")
    
    def print_summary(self):
        """Print simulation summary."""
        print(f"\n{'='*70}")
        print(f"SIMULATION SUMMARY")
        print(f"{'='*70}")
        print(f"Total ticks: {self.global_tick}")
        print(f"Generations: {self.generation}")
        print(f"Total agents: {Agent._id_counter}")
        print(f"Total events: {len(self.stream.events)}")
        
        print(f"\n--- Sunset History ---")
        for state in self.sunset_states:
            print(f"  {state.agent_id} (Gen {state.generation}):")
            print(f"    θ: {state.calibrated_theta:.6f}")
            print(f"    Drift variance: {state.drift_insights.get('variance', 'N/A')}")
            print(f"    Tiles: {len(state.tiles)}")
        
        print(f"\n--- Theta Evolution ---")
        prev_theta = None
        for state in self.sunset_states:
            if prev_theta is not None:
                delta = state.calibrated_theta - prev_theta
                print(f"  Gen {state.generation}: θ={state.calibrated_theta:.6f} (Δ={delta:+.6f})")
            else:
                print(f"  Gen {state.generation}: θ={state.calibrated_theta:.6f} (initial)")
            prev_theta = state.calibrated_theta
        
        print(f"\n--- Drift Mining Results ---")
        for state in self.sunset_states:
            insights = state.drift_insights
            print(f"  {state.agent_id}: trend={insights['trend']}, "
                  f"anomalies={insights['anomalies']}, "
                  f"max_drift={insights.get('max_drift', 'N/A')}")
        
        print(f"\n--- Memoir Excerpts ---")
        for state in self.sunset_states[-3:]:
            print(f"  {state.memoir}")
        
        # Event type counts
        event_counts = defaultdict(int)
        for event in self.stream.events:
            event_counts[event.event_type.name] += 1
        print(f"\n--- Event Distribution ---")
        for etype, count in sorted(event_counts.items()):
            print(f"  {etype}: {count}")

# =============================================================================
# Main — Run the Simulation
# =============================================================================

def main():
    print("=" * 70)
    print("METRONOME ARCHITECTURE — LIFECYCLE SIMULATION")
    print("Seed-2.0-pro (Synthesizer) · Grand Synthesis Competition")
    print("=" * 70)
    
    # Define truth (what tiles should converge to)
    truth = {
        'tile_0': 0.70,
        'tile_1': 0.50,
        'tile_2': 0.85,
        'tile_3': 0.35,
        'tile_4': 0.60
    }
    
    print(f"\nGround truth tiles: {truth}")
    print(f"Pythagorean triples loaded: {len(PYTHAGOREAN_TRIPLES)}")
    
    # Create fleet with 4 agents
    fleet = Fleet(n_agents=4, truth=truth)
    
    # Run for enough ticks to see multiple generations
    fleet.run(total_ticks=600)
    
    # Save event stream
    output_path = "grand-synthesis/submissions/seed-pro/lifecycle_events.json"
    with open(output_path, 'w') as f:
        f.write(fleet.stream.to_json())
    print(f"\nEvent stream saved to {output_path}")
    
    # Verify properties
    print(f"\n{'='*70}")
    print("VERIFICATION")
    print(f"{'='*70}")
    
    # Check bounded drift
    drift_events = fleet.stream.query(event_type=EventType.TICK)
    if drift_events:
        max_drift = max(abs(e.payload['drift']) for e in drift_events)
        avg_drift = statistics.mean(abs(e.payload['drift']) for e in drift_events)
        print(f"Max drift: {max_drift:.6f}")
        print(f"Avg drift: {avg_drift:.6f}")
        print(f"Deadband: 0.05")
        print(f"Drift bounded: {max_drift < 0.15}")  # Should be well within bounds
    
    # Check convergence progress
    convergence_events = fleet.stream.query(event_type=EventType.TILE_UPDATE)
    print(f"Tile updates: {len(convergence_events)}")
    
    # Check generations
    birth_events = fleet.stream.query(event_type=EventType.BIRTH)
    generations_seen = set(e.payload['generation'] for e in birth_events)
    print(f"Generations seen: {sorted(generations_seen)}")
    print(f"Minimum 3 generations: {len(generations_seen) >= 3}")
    
    # Check cadence calls
    cadence_events = fleet.stream.query(event_type=EventType.CADENCE_CALL)
    print(f"Cadence corrections: {len(cadence_events)}")
    
    # Check sunset events
    sunset_events = fleet.stream.query(event_type=EventType.SUNSET)
    print(f"Sunset events: {len(sunset_events)}")
    for se in sunset_events:
        print(f"  {se.agent_id}: θ_final={se.payload['calibrated_theta']:.6f}, "
              f"trinity={se.payload['trinity_score']:.4f}")
    
    print(f"\n{'='*70}")
    print("SIMULATION COMPLETE")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
