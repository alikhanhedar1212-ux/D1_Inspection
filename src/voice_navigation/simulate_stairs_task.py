"""Deterministic complete mission demonstration: no ROS, microphone or motion."""
import json
from pathlib import Path
from stairs_task import StairsTask


def simulate():
    now = [0.]
    machine = StairsTask(clock=lambda: now[0])
    log = []
    machine.start()
    while machine.state != 'complete':
        if machine.pending:
            effect = machine.pending
            log.append({'seconds': now[0], 'state': machine.state,
                        'simulated_effect': effect.kind, 'target': effect.value})
            machine.done(effect.token)
        elif machine.state.endswith('_delay'):
            log.append({'seconds': now[0], 'simulated_wait_seconds': 5})
            now[0] += 5
            machine.tick()
        elif machine.awaiting_confirmation:
            log.append({'seconds': now[0], 'simulated_user': '确认', 'door': machine.door})
            machine.confirm()
        else:
            raise RuntimeError(machine.state)
    log.append({'seconds': now[0], 'state': machine.state, 'stopped_before_stairs': True})
    return {'mode': 'simulation_only_no_motion', 'steps': log}


if __name__ == '__main__':
    result = simulate()
    path = Path(__file__).parent/'stairs_simulation.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
