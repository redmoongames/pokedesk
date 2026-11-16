"""Client SDK for a script launched by the running game's Automation tab."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket


class ControlLost(RuntimeError):
    """The player stopped the bot, closed the game or took over the controls."""

class HandedOff(Exception):
    """Normal early completion: further decisions belong to the player."""


class Bot:
    execution = None

    def __init__(self):
        try:
            self.token = os.environ["POKEMON_BOT_TOKEN"]
            port = int(os.environ["POKEMON_BOT_PORT"])
            self.project_dir = Path(os.environ["POKEMON_PROJECT_DIR"])
            manifest=os.environ.get('POKEMON_RUN_MANIFEST')
            self.execution=json.loads(Path(manifest).read_text())['execution'] if manifest else None
        except (KeyError, ValueError) as error:
            raise RuntimeError("Запускай этот скрипт через вкладку «Автоматизация» в игре.") from error
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.settimeout(None)  # Pausing the game also pauses frame-based commands.
        self.reader = self.socket.makefile("rb")

    def _call(self, method, **args):
        try:
            packet = {"token": self.token, "method": method, "args": args}
            if self.execution is not None:packet['execution']=self.execution
            self.socket.sendall((json.dumps(packet, ensure_ascii=False) + "\n").encode())
            line = self.reader.readline(8 * 1024 * 1024)  # Full fourteen-box inventory.
            if not line:
                raise ControlLost("Сессия бота остановлена")
            response = json.loads(line)
        except (OSError, ValueError) as error:
            raise ControlLost("Связь с игрой закрыта") from error
        if not response.get("ok"):
            if response.get("cancelled"):
                raise ControlLost(response.get("error"))
            raise RuntimeError(response.get("error", "Ошибка команды"))
        return response.get("result")

    def state(self):
        """Fresh coordinates, money, party HP/XP and session state, as a dict."""
        return self._call("state")

    def map(self,name=None):
        """Read-only current map: tiles [collision, behavior, elevation, encounter]."""
        return self._call('map',name=name) if name else self._call('map')

    def inventory(self):
        """Fresh read-only party and all fourteen PC boxes; stable Pokémon UIDs."""
        return self._call('inventory')

    def expect_interaction(self,context='travel'):
        """Built-in training guards permit only expected healing/PC dialogs."""
        return self._call('expect_interaction',context=context)

    def safety_profile(self,profile='training'):
        """Enable per-frame training guards for this automation session."""
        return self._call('safety_profile',profile=profile)

    def travel_policy(self,map_name,trainer_ids=()):
        return self._call('travel_policy',map=map_name,trainer_ids=list(trainer_ids))

    def training_item(self,uid,*,take=False):return self._call('training_item',uid=uid,take=take,item=197)

    def cut_tree(self,map_name,local_id,point):
        return self._call('cut_tree',map=map_name,local_id=local_id,point=list(point))

    def teleport_to_clinic(self,clinic):
        """Verified field Teleport; returns teleported=False for walking fallback."""
        return self._call('field_teleport',clinic=clinic)

    def move_plan(self,uid,goal,final_moves,*,evolution_mode='natural',approved_plan_id=None):
        """Install a freshly verified level-up/evolution move plan on the game thread."""
        return self._call('move_plan',uid=uid,goal=goal,final_moves=list(final_moves),evolution_mode=evolution_mode,approved_plan_id=approved_plan_id)

    def press(self, button, frames=2, *, release_frames=1):
        """Hold one or more GBA buttons for exact emulated frames, then release."""
        return self._call("press", button=button, frames=frames, release_frames=release_frames)

    def hold(self, button, frames=20):
        return self.press(button, frames=frames, release_frames=1)

    def walk_step(self,map_name,start,goal):
        """Exact tile entry and settling; no fixed release wait or running."""
        if getattr(self,'_legacy_steps',False):return dict(reason='legacy')
        try:return self._call('walk_step',map=map_name,start=list(start),goal=list(goal))
        except RuntimeError as error:
            if str(error)!='Неизвестная команда API':raise
            # An already-open pre-update game can keep using its old pulses.
            self._legacy_steps=True;return dict(reason='legacy')

    def walk_segment(self,map_name,start,goal,*,search=False,allow_encounters=False):
        """Validated straight corridor, sampled every frame; cancellable by player.

        Returns reason reached/battle/obstacle/unsafe/etc. No OS timing involved.
        """
        return self._call('walk_segment',map=map_name,start=list(start),goal=list(goal),search=search,allow_encounters=allow_encounters)

    def wait_frames(self, frames=60):
        if type(frames) is not int or frames < 0:
            raise ValueError("frames must be a nonnegative integer")
        result = None
        while frames:
            count = min(frames, 3600)
            result = self._call("wait_frames", frames=count)
            frames -= count
        return result

    def wait_until(self, predicate, *, timeout_frames=600, interval_frames=5):
        if type(timeout_frames) is not int or timeout_frames < 0 or type(interval_frames) is not int or interval_frames < 1:
            raise ValueError("Invalid wait limits")
        state = self.state()
        start = state["frame"]
        while True:
            if predicate(state):
                return state
            elapsed = state["frame"] - start
            if elapsed >= timeout_frames:
                raise TimeoutError("Условие не наступило за отведённое число игровых кадров")
            count = min(interval_frames, timeout_frames - elapsed)
            self.wait_frames(count)
            state = self.state()

    def log(self, message):
        return self._call("log", message=str(message))

    def event(self, code, message, **details):
        return self._call('event',code=code,message=str(message),details=details)

    def handoff(self, code, message, **details):
        self._call('handoff',code=code,message=str(message),details=details)
        raise HandedOff(message)

    def checkpoint(self, name):
        return self._call("checkpoint", name=name)

    def manage_speed(self, enabled=True, max_speed=12):
        """Opt into temporary, phase-aware pacing; manual speed keys override it."""
        return self._call('manage_speed', enabled=enabled,max_speed=max_speed)

    def set_speed(self, speed):
        return self._call("set_speed", speed=speed)

    def finish(self, *, success=True,error=None):
        return self._call("finish", success=success,error=error)

    def close(self):
        self.reader.close()
        self.socket.close()


def connect():
    return Bot()
