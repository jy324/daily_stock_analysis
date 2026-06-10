# -*- coding: utf-8 -*-
"""Tests for the DecisionSignal lifecycle state machine (workflow B.2)."""

from __future__ import annotations

import unittest

from src.services.decision_signal_service import (
    InvalidSignalTransition,
    SignalStateMachine,
    is_terminal_state,
)


class SignalStateMachineTestCase(unittest.TestCase):
    def test_legal_transitions_are_allowed(self) -> None:
        legal = [
            ("generated", "waiting_entry"),
            ("generated", "entered"),       # market entry can enter directly
            ("generated", "expired"),
            ("generated", "invalidated"),
            ("waiting_entry", "entered"),
            ("waiting_entry", "expired"),
            ("waiting_entry", "invalidated"),
            ("entered", "target_hit"),
            ("entered", "stop_hit"),
            ("entered", "expired"),
            ("entered", "invalidated"),
        ]
        for src, dst in legal:
            self.assertTrue(SignalStateMachine.can_transition(src, dst), f"{src}->{dst}")
            SignalStateMachine.assert_transition(src, dst)  # must not raise

    def test_illegal_transitions_are_rejected(self) -> None:
        illegal = [
            ("generated", "target_hit"),    # cannot win before entering
            ("generated", "stop_hit"),
            ("waiting_entry", "target_hit"),
            ("entered", "waiting_entry"),    # no going back
            ("entered", "generated"),
            ("target_hit", "entered"),       # terminal
            ("stop_hit", "expired"),         # terminal
            ("expired", "invalidated"),      # terminal
            ("invalidated", "generated"),    # terminal
        ]
        for src, dst in illegal:
            self.assertFalse(SignalStateMachine.can_transition(src, dst), f"{src}->{dst}")
            with self.assertRaises(InvalidSignalTransition):
                SignalStateMachine.assert_transition(src, dst)

    def test_terminal_states(self) -> None:
        for state in ("target_hit", "stop_hit", "expired", "invalidated"):
            self.assertTrue(is_terminal_state(state))
        for state in ("generated", "waiting_entry", "entered"):
            self.assertFalse(is_terminal_state(state))

    def test_unknown_state_is_rejected(self) -> None:
        self.assertFalse(SignalStateMachine.can_transition("nonsense", "entered"))
        with self.assertRaises(InvalidSignalTransition):
            SignalStateMachine.assert_transition("generated", "nonsense")


if __name__ == "__main__":
    unittest.main()
