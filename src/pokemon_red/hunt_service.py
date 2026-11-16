"""A coalesced, cancellable hunt proposal from immutable owner-thread snapshots."""
import json
from .travel_service import TravelService

class HuntService(TravelService):
    worker='hunt_worker.py'
    def arguments(self,target):return [json.dumps(target)]
