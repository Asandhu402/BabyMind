"""Tests for bounded delegation over the existing BabyMind role registry."""
import json
import unittest
from types import SimpleNamespace

from babymind.agents import AGENTS
from babymind.teamwork import _validate_plan, run_team


def plan(*tasks):
    return json.dumps({'tasks': list(tasks)})


def task(agent_id, brief='Analyze this.', deps=()):
    return {'agent_id': agent_id, 'task': brief, 'depends_on': list(deps)}


class FakeCoordinator:
    def __init__(self, plans, failures=()):
        self.plans = list(plans)
        self.failures = set(failures)
        self.planner_calls = []
        self.calls = []
        self.provider = self

    def complete(self, system, user):
        self.planner_calls.append((system, user))
        return self.plans.pop(0)

    def ask(self, agent_id, prompt, *, use_memory=False):
        self.calls.append((agent_id, prompt, use_memory))
        if agent_id in self.failures:
            raise RuntimeError('role failed')
        return SimpleNamespace(response=f'output from {agent_id}')


class TeamworkTests(unittest.TestCase):
    def test_plan_selects_from_all_50_and_passes_dependency_to_next_role(self):
        coordinator = FakeCoordinator([plan(task('BM-03', 'Analyze code'),
                                             task('BM-34', 'Review the analysis', ['BM-03']))])
        result = run_team(coordinator, 'Help improve my app', history='Prior context', use_memory=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([c[0] for c in coordinator.calls], ['BM-03', 'BM-34', 'BM-01'])
        self.assertTrue(all(c[2] for c in coordinator.calls))
        self.assertIn('output from BM-03', coordinator.calls[1][1])
        self.assertIn('Help improve my app', coordinator.calls[-1][1])
        self.assertIn('Prior context', coordinator.calls[-1][1])
        self.assertIn('Team contributions (unverified', result['response'])
        for role in AGENTS:
            self.assertIn(role.agent_id + ': ' + role.name, coordinator.planner_calls[0][0])
        self.assertIn('cannot use tools', coordinator.calls[0][1].lower())

    def test_failure_skips_dependent_and_does_not_synthesize(self):
        coordinator = FakeCoordinator([plan(task('BM-03'), task('BM-34', deps=['BM-03']))], ['BM-03'])
        result = run_team(coordinator, 'Help improve my app')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual([c[0] for c in coordinator.calls], ['BM-03'])
        self.assertEqual([role['status'] for role in result['roles']], ['failed', 'skipped'])
        self.assertIn('could not complete a synthesis', result['response'])

    def test_invalid_plan_is_retried_then_rejected_without_role_calls(self):
        coordinator = FakeCoordinator(['not json', plan(task('BM-03', deps=['BM-34']), task('BM-34', deps=['BM-03']))])
        with self.assertRaises(ValueError):
            run_team(coordinator, 'Help improve my app')
        self.assertEqual(len(coordinator.planner_calls), 2)
        self.assertEqual(coordinator.calls, [])

    def test_fenced_json_is_accepted_and_unrelated_role_output_is_not_a_dependency(self):
        raw = plan(task('BM-03'), task('BM-04'), task('BM-34', deps=['BM-03']))
        coordinator = FakeCoordinator(['```json\n' + raw + '\n```'])
        result = run_team(coordinator, 'Design an app')
        self.assertEqual(result['status'], 'completed')
        review = next(call for call in coordinator.calls if call[0] == 'BM-34')
        self.assertIn('output from BM-03', review[1])
        self.assertNotIn('output from BM-04', review[1])

    def test_retry_can_recover(self):
        coordinator = FakeCoordinator(['nope', plan(task('BM-03'), task('BM-34'))])
        self.assertEqual(run_team(coordinator, 'Help improve my app')['status'], 'completed')
        self.assertIn('invalid', coordinator.planner_calls[1][1])

    def test_invalid_plans_and_inputs_are_rejected(self):
        invalid = [plan(task('BM-03')), plan(task('BM-03'), task('BM-03')),
                   plan(task('BM-03'), task('BM-99')),
                   plan(task('BM-03'), task('BM-34', deps=['BM-49'])),
                   plan(task('BM-03'), task('BM-34', deps=['BM-03','BM-03'])),
                   plan(task('BM-03', '\ud800'), task('BM-34')),
                   plan(*(task(f'BM-{i:02}') for i in range(1, 6)))]
        for raw in invalid:
            with self.subTest(raw=repr(raw)[:100]), self.assertRaises(ValueError):
                _validate_plan(raw)
        for goal in ('', 'x' * 2001, '\ud800'):
            coordinator = FakeCoordinator([])
            with self.assertRaises(ValueError):
                run_team(coordinator, goal)
            self.assertEqual(coordinator.planner_calls, [])

    def test_failed_synthesis_returns_unverified_role_outputs(self):
        coordinator = FakeCoordinator([plan(task('BM-03'), task('BM-34'))], ['BM-01'])
        result = run_team(coordinator, 'Help improve my app')
        self.assertEqual(result['status'], 'partial')
        self.assertIn('output from BM-03', result['response'])
        self.assertIn('Coordinator error', result['response'])
