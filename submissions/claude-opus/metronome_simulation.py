#!/usr/bin/env python3
"""
Metronome Architecture Simulation
==================================
Demonstrates N agents with local metronome simulation achieving bounded drift
without central clock. Shows cadence-caller handoff and sunset/inheritance.

Reproducible: seeded RNG.
Run: python metronome_simulation.py
"""

import json
import math
import random
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from fractions import Fraction

SEED = 42
random.seed(SEED)


# ──────────────────────────────────────────────
# Metronome Specification
# ──────────────────────────────────────────────

@dataclass
class Theta:
    """Metronome specification: the shared constraint."""
    T: float              # period (seconds)
    phi0: float           # phase origin (epoch seconds)
    epsilon: float        # deadband tolerance
    delta: float          # hard drift bound

    def __repr__(self):
        return f"θ(T={self.T:.2f}, φ₀={self.phi0:.1f}, ε={self.epsilon:.3f}, δ={self.delta:.3f})"


# ──────────────────────────────────────────────
# Agent States
# ──────────────────────────────────────────────

class AgentState:
    INIT = "INIT"
    BOOTSTRAP = "BOOTSTRAP"
    STEADY = "STEADY"
    DRIFTING = "DRIFTING"
    RECOVERING = "RECOVERING"
    DESYNCED = "DESYNCED"
    SUNSET = "SUNSET"


# ──────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────

class Agent:
    def __init__(self, agent_id: str, clock_skew: float, noise_amp: float):
        self.agent_id = agent_id
        self.state = AgentState.INIT
        self.theta: Optional[Theta] = None
        self.is_cadence_caller = False

        # Clock model: C_local(t) = t + rho*t + eta(t)
        self.rho = clock_skew       # systematic drift rate
        self.noise_amp = noise_amp  # noise amplitude

        # Tracking
        self.current_beat = 0
        self.errors: list[float] = []
        self.beat_log: list[dict] = []
        self.drift_reports: list[dict] = []
        self.sunset_packet: Optional[dict] = None
        self.successor_theta: Optional[Theta] = None

    def local_clock(self, true_time: float) -> float:
        """Simulate local clock with drift and noise."""
        noise = random.gauss(0, self.noise_amp)
        return true_time + self.rho * true_time + noise

    def bootstrap(self, theta: Theta):
        """Receive θ and enter steady state."""
        self.theta = theta
        self.state = AgentState.STEADY
        self.current_beat = 0

    def tick(self, true_time: float) -> dict:
        """Process one time step. Returns beat event or None."""
        if self.state in (AgentState.INIT, AgentState.BOOTSTRAP, AgentState.SUNSET):
            return None

        C = self.local_clock(true_time)
        expected = self.theta.phi0 + self.current_beat * self.theta.T
        error = C - expected
        self.errors.append(error)

        # Deadband check
        abs_error = abs(error)

        result = {
            "agent": self.agent_id,
            "true_time": true_time,
            "local_time": C,
            "beat": self.current_beat,
            "error": error,
            "abs_error": abs_error,
            "state": self.state,
        }

        if abs_error < self.theta.epsilon:
            # In deadband — emit beat, no correction
            self.state = AgentState.STEADY
            self.current_beat += 1
            result["action"] = "emit_beat"
            result["correction"] = 0.0
        elif abs_error < self.theta.delta:
            # Drifting — gentle correction
            self.state = AgentState.DRIFTING
            correction = error * 0.5  # proportional correction
            self.theta = Theta(
                self.theta.T,
                self.theta.phi0 + correction,  # adjust phase
                self.theta.epsilon,
                self.theta.delta,
            )
            self.current_beat += 1
            result["action"] = "gentle_correction"
            result["correction"] = correction
        else:
            # Desynchronized — aggressive correction
            self.state = AgentState.RECOVERING
            correction = error * 0.9  # aggressive correction
            self.theta = Theta(
                self.theta.T,
                self.theta.phi0 + correction,
                self.theta.epsilon,
                self.theta.delta,
            )
            self.current_beat += 1
            result["action"] = "aggressive_correction"
            result["correction"] = correction

        self.beat_log.append(result)
        return result

    def generate_drift_report(self) -> dict:
        """Generate a drift report for the cadence caller."""
        if not self.errors:
            return {"agent": self.agent_id, "drift": 0.0, "error_int8": 0}
        recent = self.errors[-10:]  # last 10 samples
        avg_drift = sum(recent) / len(recent)
        # INT8 saturation encoding
        if self.theta:
            error_int8 = max(-128, min(127, round(avg_drift / self.theta.epsilon * 127)))
        else:
            error_int8 = 0
        report = {"agent": self.agent_id, "drift": avg_drift, "error_int8": error_int8}
        self.drift_reports.append(report)
        return report

    def prepare_sunset(self) -> dict:
        """Prepare sunset packet with calibrated θ."""
        if not self.theta:
            return {}

        recent_errors = self.errors[-100:] if self.errors else []
        self.sunset_packet = {
            "agent_id": self.agent_id,
            "theta": {
                "T": self.theta.T,
                "phi0": self.theta.phi0,
                "epsilon": self.theta.epsilon,
                "delta": self.theta.delta,
            },
            "drift_history": recent_errors[-20:],
            "calibration": {
                "clock_skew_estimate": self.rho,
                "noise_amplitude": self.noise_amp,
                "avg_error": sum(recent_errors) / max(len(recent_errors), 1),
            },
            "state": self.state,
            "sunset_timestamp": self.beat_log[-1]["true_time"] if self.beat_log else 0,
        }
        self.state = AgentState.SUNSET
        return self.sunset_packet


# ──────────────────────────────────────────────
# Cadence Caller
# ──────────────────────────────────────────────

class CadenceCaller:
    """Elected role: listens to fleet drift and proposes θ adjustments."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.agent.is_cadence_caller = True

    def collect_drifts(self, agents: list[Agent]) -> list[dict]:
        """Collect drift reports from all agents."""
        return [a.generate_drift_report() for a in agents if a.state != AgentState.SUNSET]

    def propose_adjustment(self, drift_reports: list[dict], current_theta: Theta) -> Theta:
        """Compute weighted median of fleet phase and propose new θ."""
        if not drift_reports:
            return current_theta

        # Weighted median drift
        drifts = sorted([r["drift"] for r in drift_reports])
        n = len(drifts)
        if n % 2 == 1:
            median_drift = drifts[n // 2]
        else:
            median_drift = (drifts[n // 2 - 1] + drifts[n // 2]) / 2

        # Grant: adjust phase to fleet center
        new_phi0 = current_theta.phi0 + median_drift * 0.5  # gentle, granted not forced
        return Theta(current_theta.T, new_phi0, current_theta.epsilon, current_theta.delta)

    def handoff(self, new_caller_agent: Agent):
        """Transfer cadence caller role."""
        self.agent.is_cadence_caller = False
        new_caller_agent.is_cadence_caller = True
        return CadenceCaller(new_caller_agent)


# ──────────────────────────────────────────────
# Fleet Simulation
# ──────────────────────────────────────────────

class Fleet:
    def __init__(self, N: int, theta: Theta, seed: int = SEED):
        random.seed(seed)
        self.N = N
        self.theta = theta
        self.agents: list[Agent] = []
        self.caller: Optional[CadenceCaller] = None
        self.caller_index = 0
        self.events: list[dict] = []

        # Create agents with heterogeneous clocks
        for i in range(N):
            clock_skew = random.gauss(0, 0.0001)   # ~100ppm typical
            noise_amp = random.uniform(0.001, 0.01)  # 1-10ms noise
            agent = Agent(f"agent_{i}", clock_skew, noise_amp)
            agent.bootstrap(Theta(theta.T, theta.phi0, theta.epsilon, theta.delta))
            self.agents.append(agent)

        # First agent is initial cadence caller
        self.caller = CadenceCaller(self.agents[0])

    def step(self, true_time: float) -> list[dict]:
        """Advance simulation by one tick."""
        results = []
        for agent in self.agents:
            if agent.state != AgentState.SUNSET:
                r = agent.tick(true_time)
                if r:
                    results.append(r)
        return results

    def cadence_call_round(self, true_time: float):
        """Perform one cadence caller round: collect drifts, propose adjustment."""
        drift_reports = self.caller.collect_drifts(self.agents)
        new_theta = self.caller.propose_adjustment(drift_reports, self.theta)

        # Agents accept the granted θ (power granted, not forced)
        self.theta = new_theta
        for agent in self.agents:
            if agent.state != AgentState.SUNSET and not agent.is_cadence_caller:
                # Agents adopt the new phase but keep their own corrections
                agent.theta = Theta(
                    new_theta.T,
                    new_theta.phi0,
                    agent.theta.epsilon,
                    agent.theta.delta,
                )

        event = {
            "type": "cadence_call",
            "time": true_time,
            "caller": self.caller.agent.agent_id,
            "median_drift": new_theta.phi0 - self.agents[0].theta.phi0,
            "n_reports": len(drift_reports),
        }
        self.events.append(event)
        return event

    def rotate_caller(self):
        """Rotate cadence caller to next agent."""
        active = [a for a in self.agents if a.state != AgentState.SUNSET]
        if not active:
            return
        self.caller_index = (self.caller_index + 1) % len(active)
        new_caller = active[self.caller_index]
        self.caller = self.caller.handoff(new_caller)
        self.events.append({
            "type": "caller_rotation",
            "new_caller": new_caller.agent_id,
        })

    def sunset_agent(self, agent_index: int) -> dict:
        """Sunset an agent and optionally create a successor."""
        agent = self.agents[agent_index]
        sunset_packet = agent.prepare_sunset()

        # Create successor that inherits θ
        successor = Agent(
            f"agent_{agent_index}_successor",
            random.gauss(0, 0.0001),
            random.uniform(0.001, 0.01),
        )
        # Inherit calibrated θ from sunset packet
        inherited_theta = Theta(
            sunset_packet["theta"]["T"],
            sunset_packet["theta"]["phi0"],
            sunset_packet["theta"]["epsilon"],
            sunset_packet["theta"]["delta"],
        )
        successor.successor_theta = inherited_theta
        successor.bootstrap(inherited_theta)

        # Inherit current beat count so successor is in sync
        successor.current_beat = agent.current_beat

        self.agents[agent_index] = successor
        self.events.append({
            "type": "sunset",
            "departing": sunset_packet["agent_id"],
            "successor": successor.agent_id,
            "inherited_phi0": inherited_theta.phi0,
        })
        return sunset_packet

    def max_inter_agent_drift(self) -> float:
        """Compute maximum drift between any two agents."""
        active = [a for a in self.agents if a.state != AgentState.SUNSET]
        if len(active) < 2:
            return 0.0
        max_drift = 0.0
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                if active[i].errors and active[j].errors:
                    drift = abs(active[i].errors[-1] - active[j].errors[-1])
                    max_drift = max(max_drift, drift)
        return max_drift


# ──────────────────────────────────────────────
# Main Simulation
# ──────────────────────────────────────────────

def run_simulation():
    print("=" * 70)
    print("METRONOME ARCHITECTURE SIMULATION")
    print("=" * 70)

    # Configuration
    N = 6
    T = 1.0       # 1 second period
    phi0 = 0.0
    epsilon = T * 0.05   # 5% deadband
    delta = T * 0.15     # 15% hard bound
    theta = Theta(T, phi0, epsilon, delta)

    print(f"\nConfiguration:")
    print(f"  Agents: {N}")
    print(f"  θ = {theta}")
    print(f"  Seed: {SEED}")
    print()

    fleet = Fleet(N, theta, seed=SEED)

    # Print agent clock parameters
    print("Agent Clock Parameters:")
    for a in fleet.agents:
        print(f"  {a.agent_id}: ρ={a.rho:.6f}, η_amp={a.noise_amp:.4f}")
    print()

    # ─── Phase 1: Steady State (100 beats) ───
    print("─" * 50)
    print("PHASE 1: STEADY STATE (100 beats)")
    print("─" * 50)

    max_drifts = []
    for beat in range(100):
        true_time = beat * T
        results = fleet.step(true_time)
        max_drift = fleet.max_inter_agent_drift()
        max_drifts.append(max_drift)

        if beat % 25 == 0:
            states = {a.agent_id: a.state for a in fleet.agents}
            print(f"  Beat {beat:3d} | max_drift={max_drift:.6f}s | states={list(states.values())}")

    print(f"\n  Phase 1 Summary:")
    print(f"    Max drift over 100 beats: {max(max_drifts):.6f}s")
    print(f"    Mean drift: {sum(max_drifts)/len(max_drifts):.6f}s")
    print(f"    Deadband (ε): {epsilon:.3f}s")
    print(f"    All drifts within deadband: {max(max_drifts) < epsilon}")

    # ─── Phase 2: Cadence Calling (50 beats with periodic adjustment) ───
    print(f"\n{'─' * 50}")
    print("PHASE 2: CADENCE CALLING (50 beats, caller rounds every 10 beats)")
    print("─" * 50)

    cadence_drifts = []
    for beat in range(100, 150):
        true_time = beat * T
        fleet.step(true_time)

        if beat % 10 == 0:
            event = fleet.cadence_call_round(true_time)
            max_drift = fleet.max_inter_agent_drift()
            cadence_drifts.append(max_drift)
            print(f"  Beat {beat:3d} | caller={event['caller']} | "
                  f"drift={max_drift:.6f}s | reports={event['n_reports']}")

        if beat % 25 == 0:
            fleet.rotate_caller()

    print(f"\n  Phase 2 Summary:")
    print(f"    Max drift with cadence calling: {max(cadence_drifts):.6f}s")
    print(f"    Mean drift with cadence: {sum(cadence_drifts)/len(cadence_drifts):.6f}s")

    # ─── Phase 3: Stress Test — Increase Noise ───
    print(f"\n{'─' * 50}")
    print("PHASE 3: STRESS TEST (increased noise, 50 beats)")
    print("─" * 50)

    # Increase noise on all agents
    for a in fleet.agents:
        a.noise_amp *= 5  # 5x noise
        a.rho *= 3        # 3x clock skew

    stress_drifts = []
    for beat in range(150, 200):
        true_time = beat * T
        fleet.step(true_time)

        if beat % 10 == 0:
            fleet.cadence_call_round(true_time)
            max_drift = fleet.max_inter_agent_drift()
            stress_drifts.append(max_drift)
            print(f"  Beat {beat:3d} | drift={max_drift:.6f}s (5x noise, 3x skew)")

    print(f"\n  Phase 3 Summary:")
    print(f"    Max drift under stress: {max(stress_drifts):.6f}s")
    print(f"    Mean drift under stress: {sum(stress_drifts)/len(stress_drifts):.6f}s")

    # ─── Phase 4: Sunset and Inheritance ───
    print(f"\n{'─' * 50}")
    print("PHASE 4: SUNSET AND INHERITANCE")
    print("─" * 50)

    # Sunset agent 2
    sunset_packet = fleet.sunset_agent(2)
    print(f"\n  Agent 2 sunsetting:")
    print(f"    Calibrated φ₀: {sunset_packet['theta']['phi0']:.6f}")
    print(f"    Clock skew estimate: {sunset_packet['calibration']['clock_skew_estimate']:.6f}")
    print(f"    Avg error (last 100): {sunset_packet['calibration']['avg_error']:.6f}")
    print(f"    Drift history (last 5): {sunset_packet['drift_history'][-5:]}")

    # Continue simulation with successor
    print(f"\n  Successor inherits θ and continues:")
    successor_drifts = []
    for beat in range(200, 250):
        true_time = beat * T
        fleet.step(true_time)
        max_drift = fleet.max_inter_agent_drift()
        successor_drifts.append(max_drift)

        if beat % 10 == 0:
            fleet.cadence_call_round(true_time)
            print(f"    Beat {beat:3d} | drift={max_drift:.6f}s (successor active)")

    print(f"\n  Phase 4 Summary:")
    print(f"    Max drift after sunset/inheritance: {max(successor_drifts):.6f}s")
    print(f"    Mean drift after sunset: {sum(successor_drifts)/len(successor_drifts):.6f}s")

    # ─── Phase 5: Multiple Simultaneous Sunsets ───
    print(f"\n{'─' * 50}")
    print("PHASE 5: MULTIPLE SIMULTANEOUS SUNSETS")
    print("─" * 50)

    # Sunset agents 0 and 4 simultaneously
    fleet.sunset_agent(0)
    fleet.sunset_agent(4)
    print(f"  Sunsetting agents 0 and 4 simultaneously")
    print(f"  Active agents: {[a.agent_id for a in fleet.agents if a.state != AgentState.SUNSET]}")

    multi_sunset_drifts = []
    for beat in range(250, 300):
        true_time = beat * T
        fleet.step(true_time)
        max_drift = fleet.max_inter_agent_drift()
        multi_sunset_drifts.append(max_drift)

        if beat % 10 == 0:
            fleet.cadence_call_round(true_time)
            print(f"    Beat {beat:3d} | drift={max_drift:.6f}s (multi-successor)")

    print(f"\n  Phase 5 Summary:")
    print(f"    Max drift after multi-sunset: {max(multi_sunset_drifts):.6f}s")
    print(f"    Mean drift after multi-sunset: {sum(multi_sunset_drifts)/len(multi_sunset_drifts):.6f}s")

    # ─── Final Report ───
    print(f"\n{'=' * 70}")
    print("FINAL REPORT")
    print("=" * 70)

    all_drifts = max_drifts + cadence_drifts + stress_drifts + successor_drifts + multi_sunset_drifts
    print(f"\n  Total beats simulated: 300")
    print(f"  Agents: {N} initial → {N} (with successors)")
    print(f"  Global max drift: {max(all_drifts):.6f}s")
    print(f"  Global mean drift: {sum(all_drifts)/len(all_drifts):.6f}s")
    print(f"  Deadband (ε): {epsilon:.3f}s")
    print(f"  Hard bound (δ): {delta:.3f}s")

    # Drift bound verification
    rho_max = max(abs(a.rho) for a in fleet.agents)
    eta_max = max(a.noise_amp for a in fleet.agents)
    theoretical_bound = 2 * (rho_max * T + eta_max) + epsilon
    print(f"\n  Theoretical drift bound: {theoretical_bound:.6f}s")
    print(f"  Observed max drift: {max(all_drifts):.6f}s")
    print(f"  Bound holds: {max(all_drifts) < theoretical_bound}")

    # Event summary
    event_types = {}
    for e in fleet.events:
        t = e["type"]
        event_types[t] = event_types.get(t, 0) + 1
    print(f"\n  Events: {event_types}")

    # State distribution (final)
    final_states = {}
    for a in fleet.agents:
        s = a.state
        final_states[s] = final_states.get(s, 0) + 1
    print(f"  Final agent states: {final_states}")

    # INT8 encoding demo
    print(f"\n  INT8 Encoding Demo (last drift round):")
    for a in fleet.agents[:3]:
        if a.state != AgentState.SUNSET and a.errors:
            report = a.generate_drift_report()
            print(f"    {a.agent_id}: drift={report['drift']:+.6f}s → INT8={report['error_int8']}")

    print(f"\n{'=' * 70}")
    print("SIMULATION COMPLETE — All results reproducible with seed={}".format(SEED))
    print("=" * 70)

    return {
        "config": {"N": N, "T": T, "epsilon": epsilon, "delta": delta, "seed": SEED},
        "results": {
            "global_max_drift": max(all_drifts),
            "global_mean_drift": sum(all_drifts) / len(all_drifts),
            "theoretical_bound": theoretical_bound,
            "bound_holds": max(all_drifts) < theoretical_bound,
            "event_counts": event_types,
        },
    }


if __name__ == "__main__":
    results = run_simulation()
